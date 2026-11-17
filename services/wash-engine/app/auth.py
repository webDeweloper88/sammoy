from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from .db import db
from .security import decode_access_token


bearer = HTTPBearer(auto_error=False)


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "login": row["login"],
        "role": row["role"],
        "display_name": row["display_name"],
        "must_change_password": bool(row.get("must_change_password", False)),
        "auth_method": row.get("auth_method", "password"),
        "service_card_id": row.get("service_card_id"),
    }


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict[str, Any]:
    # PostgreSQL and password/card checks are synchronous: keep them off the
    # event loop used by customer wash-state requests.
    user = await run_in_threadpool(authenticated_user, credentials)
    if user['auth_method'] == 'nfc_pin':
        from .service_access import critical, consume_grant
        if critical(request.url.path, request.method) and not consume_grant(
            request.headers.get('X-Owner-Confirmation'), user, request.method,
            request.url.path, await request.body(),
        ):
            raise HTTPException(428, 'owner_password_required')
    return user


def authenticated_user(credentials: HTTPAuthorizationCredentials | None) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    try:
        payload = decode_access_token(credentials.credentials)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    with db() as conn:
        revoked = conn.execute(
            """
            SELECT 1
            FROM auth_revoked_tokens
            WHERE jti = %s AND expires_at > now()
            """,
            (jti,),
        ).fetchone()
        if revoked:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token revoked")

        user = conn.execute(
            """
            SELECT id, login, role, display_name, password_hash, active,
                   must_change_password, auth_version
            FROM auth_users
            WHERE id = %s
            """,
            (int(user_id),),
        ).fetchone()

    if not user or not user["active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    if int(payload.get("auth_version") or 0) != int(user.get("auth_version") or 1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    user.update(auth_method=payload.get('auth_method', 'password'),
                service_card_id=payload.get('service_card_id'), _jti=jti)
    if user['auth_method'] == 'nfc_pin':
        with db() as conn:
            card = conn.execute("SELECT 1 FROM owner_service_cards WHERE id=%s AND owner_id=%s AND active", (user['service_card_id'],user['id'])).fetchone()
            session = conn.execute("UPDATE owner_service_sessions SET last_seen_at=now() WHERE jti=%s AND last_seen_at>now()-interval '2 minutes' RETURNING jti", (jti,)).fetchone() if card else None
            conn.commit()
        if not session:
            raise HTTPException(401, 'service_session_expired')
    return user


def require_role(*roles: str):
    def dependency(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        if user.get("must_change_password"):
            raise HTTPException(
                status.HTTP_428_PRECONDITION_REQUIRED,
                "Password change required",
            )
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        return user

    return dependency


def token_exp_from_payload(credentials: HTTPAuthorizationCredentials) -> datetime:
    payload = decode_access_token(credentials.credentials)
    return datetime.fromtimestamp(int(payload["exp"]), UTC)
