"""Version 1 of the signed LABRIX application-release protocol (no OS updates)."""
import base64
from datetime import datetime, timezone
import json
import re
from urllib.parse import urlsplit
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SERVICES = {'wash-engine', 'io-helper', 'kiosk-ui', 'telegram-reports'}
SHA = re.compile(r'^[a-f0-9]{64}$')
MAX_ARCHIVE = 2 * 1024**3

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()

def validate_manifest(m, now=None):
    keys = {'schema','product','release_no','version','hardware','arch','channel','issued_at','expires_at',
            'notes','artifact','services','db_contract','agent_protocol','wallet_protocol','runtime_contract'}
    if not isinstance(m, dict) or set(m) != keys:
        raise ValueError('Invalid release fields')
    if any(type(m[k]) is not int for k in ('schema','agent_protocol','wallet_protocol','runtime_contract')):raise ValueError('Invalid protocol number')
    if m['schema'] != 1 or m['product'] != 'labrix-wash' or m['agent_protocol'] != 1 or m['wallet_protocol'] != 1 or m['runtime_contract'] != 1:
        raise ValueError('Unsupported release protocol')
    if type(m['release_no']) is not int or not 1 <= m['release_no'] <= 2**53-1:
        raise ValueError('Invalid release number')
    if not isinstance(m['version'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}',m['version']):
        raise ValueError('Invalid version')
    if m['hardware'] != 'cubie-a7a' or m['arch'] != 'aarch64' or m['channel'] != 'stable':
        raise ValueError('Unsupported hardware/channel')
    now = now or datetime.now(timezone.utc)
    try:
        issued=datetime.fromisoformat(m['issued_at'].replace('Z','+00:00'))
        expires=datetime.fromisoformat(m['expires_at'].replace('Z','+00:00'))
        if issued.tzinfo is None or expires.tzinfo is None or issued > now or expires <= now or not 0 < (expires-issued).total_seconds() <= 180*86400:
            raise ValueError('Expired or invalid release dates')
    except (AttributeError,TypeError):raise ValueError('Invalid release dates') from None
    if not isinstance(m['notes'],dict) or set(m['notes']) != {'ru','uz','en'} or any(not isinstance(v,str) or not 1<=len(v)<=4000 for v in m['notes'].values()):
        raise ValueError('Invalid release notes')
    if not isinstance(m['services'],dict) or not m['services'] or not set(m['services']) <= SERVICES:
        raise ValueError('Invalid services')
    if any(not isinstance(v,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',v) for v in m['services'].values()):
        raise ValueError('Invalid image digest')
    if not isinstance(m['db_contract'],str) or not SHA.fullmatch(m['db_contract']):raise ValueError('Invalid database contract')
    a=m['artifact']
    if not isinstance(a,dict) or set(a) != {'url','sha256','bytes','unpacked_bytes','image_bytes'}:
        raise ValueError('Invalid artifact')
    if not isinstance(a['sha256'],str) or not SHA.fullmatch(a['sha256']):raise ValueError('Invalid artifact hash')
    if any(type(a[k]) is not int or not 0<a[k]<=16*1024**3 for k in ('bytes','unpacked_bytes','image_bytes')) or a['bytes']>MAX_ARCHIVE:
        raise ValueError('Invalid artifact size')
    u=urlsplit(a['url'])
    if u.scheme!='https' or u.netloc!='pay.labrix.uz' or u.path!='/api/v1/software/artifacts/'+a['sha256'] or u.query or u.fragment:
        raise ValueError('Artifact origin is not allowed')
    return m

def verify_release(envelope, public_pem, now=None):
    if not isinstance(envelope,dict) or set(envelope) != {'manifest','signature'}:
        raise ValueError('Invalid signed envelope')
    if len(canonical(envelope))>65536:raise ValueError('Release metadata is too large')
    try:
        key=serialization.load_pem_public_key(public_pem)
        if not isinstance(key,Ed25519PublicKey):raise ValueError('Ed25519 key required')
        sig=base64.b64decode(envelope['signature'],validate=True)
        if len(sig)!=64:raise ValueError('Invalid signature')
        key.verify(sig,canonical(envelope['manifest']))
    except Exception:raise ValueError('Invalid release signature') from None
    return validate_manifest(envelope['manifest'],now)

DATABASE_CONTRACT_PROGRAM = "import ast,hashlib,json,pathlib,re\nroot=pathlib.Path('/app/app');items=[]\nfor p in sorted(root.rglob('*.py')):\n for node in ast.walk(ast.parse(p.read_text())):\n  if isinstance(node,ast.Constant) and isinstance(node.value,str) and re.search(r'\\b(?:CREATE|ALTER|DROP|TRUNCATE)\\s+(?:TABLE|INDEX|TYPE|SCHEMA|EXTENSION|FUNCTION|TRIGGER|VIEW)\\b',node.value,re.I):items.append((str(p.relative_to(root)),node.value))\nfor p in sorted(root.rglob('*.sql')):items.append((str(p.relative_to(root)),p.read_text()))\nitems.append(('db.py', (root/'db.py').read_text()))\nprint(hashlib.sha256(json.dumps(sorted(items),sort_keys=True,separators=(',',':')).encode()).hexdigest())\n"
