"""Local Owner service cards, isolated from financial card operations."""
import hashlib
import secrets
import threading
import time
from datetime import UTC, datetime
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .db import db
from .security import hash_password, verify_password, create_access_token

SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS owner_service_cards (
 id BIGSERIAL PRIMARY KEY, uid TEXT UNIQUE NOT NULL,
 owner_id BIGINT NOT NULL REFERENCES auth_users(id), name TEXT NOT NULL,
 pin_hash TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
 failures INTEGER NOT NULL DEFAULT 0, locked_until TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS owner_service_sessions (
 jti TEXT PRIMARY KEY, owner_id BIGINT NOT NULL REFERENCES auth_users(id),
 card_id BIGINT NOT NULL REFERENCES owner_service_cards(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now());
'''
_lock = threading.RLock()
_pending = None
_enrollment = None
_grants = {}


def idle(runtime):
    s = runtime.state
    return not (int(s.get('creditSum') or 0) or s.get('activeMode') or
                runtime.active_session_id or s.get('walletTransferPending') or
                s.get('walletPending') or s.get('requestedOutput'))


def enrollment_problem(conn, runtime, uid):
    """Check again at commit; preserve history and never discard card money."""
    if conn.execute('SELECT 1 FROM owner_service_cards WHERE uid=%s', (uid,)).fetchone():
        return 'service_card_in_use'
    card = conn.execute('SELECT card_type,balance_sum,vip_profile_id,status FROM rfid_cards WHERE uid=%s FOR UPDATE', (uid,)).fetchone()
    if card and (card['card_type'] != 'customer' or card['vip_profile_id'] is not None):
        return 'service_card_not_customer'
    if card and (int(card['balance_sum']) != 0 or card['status'] not in ('active', 'blocked')):
        return 'service_card_has_balance' if int(card['balance_sum']) else 'service_card_in_use'
    if conn.execute("SELECT 1 FROM wash_sessions s WHERE s.card_uid=%s AND (s.status IN ('open','running') OR EXISTS (SELECT 1 FROM recovery_credits r WHERE r.wash_session_id=s.id AND r.status='unclaimed' AND r.amount_sum>0)) LIMIT 1", (uid,)).fetchone():
        return 'service_card_pending'
    if conn.execute("SELECT 1 FROM shared_wallet_post_jobs WHERE uid=%s AND status='pending' LIMIT 1", (uid,)).fetchone():
        return 'service_card_pending'
    # A local service registry cannot reserve an identity on other posts.
    # Shared cards need a separate, replicated conversion protocol.
    if conn.execute('SELECT 1 FROM shared_wallet_cards WHERE uid=%s LIMIT 1', (uid,)).fetchone():
        return 'service_card_shared'
    if runtime.shared_wallet_enabled:
        from .wallet_client import inspect
        try:
            if inspect(uid):
                return 'service_card_shared'
        except Exception:
            return 'service_wallet_unavailable'
    return None


def intercept(runtime, uid):
    """Called under the wash lock, before any monetary card handling."""
    global _pending, _enrollment
    with _lock, db() as conn:
        card = conn.execute('SELECT id, active FROM owner_service_cards WHERE uid=%s', (uid,)).fetchone()
        if _enrollment and _enrollment['until'] > time.monotonic():
            if not idle(runtime):
                runtime.state['lastRfidStatus'] = 'service_busy'
            else:
                problem = enrollment_problem(conn, runtime, uid)
                _enrollment['uid'] = None if problem else uid
                _enrollment['error'] = problem
                runtime.state['lastRfidStatus'] = 'service_card_captured'
            return True
        if not card:
            return False
        runtime.state['lastRfidStatus'] = 'service_card_disabled'
        if card['active'] and idle(runtime):
            # Repeated reader events must not extend an existing challenge forever.
            if not _pending or _pending['card_id'] != card['id'] or _pending['until'] <= time.monotonic():
                _pending = dict(card_id=card['id'], nonce=secrets.token_urlsafe(32), until=time.monotonic()+45)
            runtime.state['lastRfidStatus'] = 'service_pin_required'
        elif card['active']:
            runtime.state['lastRfidStatus'] = 'service_busy'
        return True


def critical(path, method):
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return False
    return path.startswith(('/api/owner/rfid', '/api/owner/vip',
                            '/api/owner/wallet', '/api/owner/site', '/api/owner/software',
                            '/api/owner/updates', '/api/owner/telegram', '/api/system',
                            '/api/wallet-management', '/api/software', '/api/updates', '/api/auth/account', '/api/owner/device'))


def consume_grant(key, user, method, path, body):
    with _lock:
        grant = _grants.pop(key, None)
    return bool(grant and grant['until'] > time.monotonic() and grant['jti'] == user['_jti']
                and grant['method'] == method and grant['path'] == path
                and grant['digest'] == hashlib.sha256(body).hexdigest())


class Enroll(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    pin: str = Field(pattern=r'^[0-9]{4,12}$')
    password: str = Field(min_length=1, max_length=200)

class Password(BaseModel):
    password: str = Field(min_length=1, max_length=200)

class Pin(BaseModel):
    challenge: str = Field(min_length=1, max_length=100)
    pin: str = Field(pattern=r'^[0-9]{4,12}$')

class Confirmation(Password):
    method: str = Field(pattern='^(POST|PUT|PATCH|DELETE)$')
    path: str = Field(min_length=1, max_length=500)
    body: str = Field(default='', max_length=1_000_000)


def audit(conn, event, owner_id, card_id=None):
    from psycopg.types.json import Jsonb
    conn.execute("INSERT INTO system_events(event_type,message,context) VALUES(%s,%s,%s)",
                 (event, 'Owner service-card access', Jsonb(dict(owner_id=owner_id, card_id=card_id))))


def record_session(jti, user):
    with db() as conn:
        conn.execute("DELETE FROM owner_service_sessions WHERE created_at<now()-interval '1 day'")
        conn.execute('INSERT INTO owner_service_sessions(jti,owner_id,card_id) VALUES(%s,%s,%s)', (jti,user['id'],user['service_card_id']))
        conn.commit()


def register(app, runtime):
    from .auth import require_role, public_user
    owner = require_role('owner')
    router = APIRouter()

    def password_check(user, password):
        # Share the password-login lockout to prevent a card session guessing it.
        with db() as conn:
            row = conn.execute('SELECT failure_count, locked_until FROM auth_login_attempts WHERE login=%s FOR UPDATE', (user['login'],)).fetchone()
            if row and row['locked_until'] and row['locked_until'] > datetime.now(UTC):
                raise HTTPException(429, 'service_password_locked')
            if not verify_password(password, user['password_hash']):
                conn.execute('''INSERT INTO auth_login_attempts(login,failure_count,locked_until) VALUES(%s,1,NULL)
                    ON CONFLICT(login) DO UPDATE SET failure_count=auth_login_attempts.failure_count+1,
                    locked_until=CASE WHEN auth_login_attempts.failure_count+1>=5 THEN now()+interval '5 minutes' ELSE NULL END,
                    updated_at=now()''', (user['login'],))
                conn.commit()
                raise HTTPException(403, 'service_password_invalid')
            conn.execute('DELETE FROM auth_login_attempts WHERE login=%s', (user['login'],))
            conn.commit()

    @router.get('/api/auth/service-challenge')
    def challenge():
        with runtime.lock, _lock:
            if not idle(runtime) or not _pending or _pending['until'] <= time.monotonic():
                return {'challenge': None}
            return {'challenge': _pending['nonce']}

    @router.post('/api/auth/service-pin')
    def login_pin(payload: Pin):
        global _pending
        with runtime.lock, _lock, db() as conn:
            if not idle(runtime) or not _pending or _pending['until'] <= time.monotonic() or not secrets.compare_digest(payload.challenge, _pending['nonce']):
                raise HTTPException(409, 'service_challenge_expired')
            card = conn.execute('SELECT * FROM owner_service_cards WHERE id=%s FOR UPDATE', (_pending['card_id'],)).fetchone()
            if not card or not card['active']:
                _pending = None
                raise HTTPException(403, 'service_card_disabled')
            if card['locked_until'] and card['locked_until'] > datetime.now(UTC):
                raise HTTPException(429, 'service_pin_locked')
            if not verify_password(payload.pin, card['pin_hash']):
                conn.execute("UPDATE owner_service_cards SET failures=failures+1, locked_until=CASE WHEN failures+1>=5 THEN now()+interval '5 minutes' ELSE NULL END WHERE id=%s", (card['id'],))
                conn.commit()
                raise HTTPException(403, 'service_pin_invalid')
            user = conn.execute('SELECT * FROM auth_users WHERE id=%s', (card['owner_id'],)).fetchone()
            if not user or not user['active'] or user['role'] != 'owner' or user['must_change_password']:
                raise HTTPException(403, 'service_owner_unavailable')
            conn.execute('UPDATE owner_service_cards SET failures=0,locked_until=NULL WHERE id=%s', (card['id'],))
            conn.commit()
            _pending = None
            user.update(auth_method='nfc_pin', service_card_id=card['id'])
            audit(conn, 'owner_service_card_login', user['id'], card['id'])
            conn.commit()
            token, jti, expires = create_access_token(user)
            record_session(jti, user)
            return dict(access_token=token, expires_at=expires.isoformat(), user=public_user(user))

    @router.post('/api/auth/confirm-action')
    def confirm(payload: Confirmation, user: Annotated[dict, Depends(owner)]):
        password_check(user, payload.password)
        with _lock:
            for key in list(_grants):
                if _grants[key]['until'] <= time.monotonic():
                    del _grants[key]
            key = secrets.token_urlsafe(32)
            _grants[key] = dict(jti=user['_jti'], method=payload.method, path=payload.path,
                                digest=hashlib.sha256(payload.body.encode()).hexdigest(), until=time.monotonic()+30)
        return {'grant': key}

    @router.get('/api/owner/service-cards')
    def cards(user: Annotated[dict, Depends(owner)]):
        with db() as conn:
            rows = conn.execute('SELECT id,name,active,created_at FROM owner_service_cards WHERE owner_id=%s ORDER BY id', (user['id'],)).fetchall()
        return {'cards': rows}

    @router.post('/api/owner/service-cards/enroll')
    def enroll(payload: Enroll, user: Annotated[dict, Depends(owner)]):
        global _enrollment
        password_check(user, payload.password)
        with runtime.lock, _lock:
            if not idle(runtime):
                raise HTTPException(409, 'service_station_busy')
            _enrollment = dict(owner_id=user['id'], jti=user['_jti'], name=payload.name, pin_hash=hash_password(payload.pin), until=time.monotonic()+60, uid=None, error=None)
        return {'ok': True}

    @router.get('/api/owner/service-cards/enrollment')
    def enrollment(user: Annotated[dict, Depends(owner)]):
        with _lock:
            current = _enrollment if _enrollment and _enrollment['owner_id'] == user['id'] and _enrollment['jti'] == user['_jti'] and _enrollment['until'] > time.monotonic() else None
            return {'waiting': bool(current), 'captured': bool(current and current['uid']), 'error': current['error'] if current else None}

    @router.post('/api/owner/service-cards/finish')
    def finish(user: Annotated[dict, Depends(owner)]):
        global _enrollment
        with runtime.lock, _lock, db() as conn:
            current = _enrollment
            if not current or current['owner_id'] != user['id'] or current['jti'] != user['_jti'] or current['until'] <= time.monotonic() or not current['uid'] or not idle(runtime):
                raise HTTPException(409, 'service_enrollment_expired')
            problem = enrollment_problem(conn, runtime, current['uid'])
            if problem:
                current['uid'] = None
                current['error'] = problem
                raise HTTPException(409, problem)
            service_card = conn.execute('INSERT INTO owner_service_cards(uid,owner_id,name,pin_hash) VALUES(%s,%s,%s,%s) RETURNING id', (current['uid'],user['id'],current['name'],current['pin_hash'])).fetchone()
            # Keep the row and ledger links, but retire its payment identity in
            # the same transaction that reserves the UID for Owner access.
            conn.execute("UPDATE rfid_cards SET card_type='service',enabled=FALSE,status='blocked',updated_at=now() WHERE uid=%s", (current['uid'],))
            audit(conn, 'owner_service_card_created', user['id'], service_card['id'])
            conn.commit()
            _enrollment = None
        return {'ok': True}

    @router.post('/api/owner/service-cards/cancel')
    def cancel(user: Annotated[dict, Depends(owner)]):
        global _enrollment
        with _lock:
            if _enrollment and _enrollment['owner_id'] == user['id'] and _enrollment['jti'] == user['_jti']:
                _enrollment = None
        return {'ok': True}

    @router.delete('/api/owner/service-cards/{card_id}')
    def revoke(card_id: int, payload: Password, user: Annotated[dict, Depends(owner)]):
        password_check(user, payload.password)
        with db() as conn:
            conn.execute('UPDATE owner_service_cards SET active=FALSE WHERE id=%s AND owner_id=%s', (card_id,user['id']))
            audit(conn, 'owner_service_card_revoked', user['id'], card_id)
            conn.commit()
        return {'ok': True}
    app.include_router(router)
