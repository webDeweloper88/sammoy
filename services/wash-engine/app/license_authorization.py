"""Offline verification of a hardware-bound licence; network loss is not expiry."""
import base64
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN='labrix.license-authorization.v1'

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def decode(value):return base64.urlsafe_b64decode(value+'='*(-len(value)%4))
def public_key():return Path(__file__).with_name('license-public-key.txt').read_text().strip()

def verify(envelope,config,hardware,*,nonce=None,previous=None,key=None):
    try:
        body={k:v for k,v in envelope.items() if k!='signature'}
        Ed25519PublicKey.from_public_bytes(decode(key or public_key())).verify(decode(envelope['signature']),canonical(body))
        if not (body['schema']==DOMAIN):raise ValueError("Invalid licence authorization")
        if not (body['site_code']==config['site_code'] and int(body['post_no'])==int(config['post_no'])):raise ValueError("Invalid licence authorization")
        if not (hardware.get('hardware_fingerprint_hash') and body['hardware_fingerprint_hash']==hardware['hardware_fingerprint_hash']):raise ValueError("Invalid licence authorization")
        if not (nonce is None or body['nonce']==nonce):raise ValueError("Invalid licence authorization")
        issued=datetime.fromisoformat(body['issued_at']).astimezone(UTC)
        license=body['license']
        if not (license['site_code']==body['site_code'] and int(license['post_no'])==int(body['post_no'])):raise ValueError("Invalid licence authorization")
        if not (license['authorization_mode']=='local_signed' and license.get('online_lease_until') is None):raise ValueError("Invalid licence authorization")
        if not (isinstance(license['enabled'],bool) and isinstance(license['locked'],bool)):raise ValueError("Invalid licence authorization")
        if not (license['license_duration_type']=='permanent' or license.get('valid_until') or license['locked']):raise ValueError("Invalid licence authorization")
        if previous:
            if not (issued>=datetime.fromisoformat(previous['issued_at']).astimezone(UTC)):raise ValueError("Invalid licence authorization")
            current=license.get('lifecycle') or {};prior=previous['license'].get('lifecycle') or {}
            if not (int(current.get('controller_generation',1))>=int(prior.get('controller_generation',1))):raise ValueError("Invalid licence authorization")
            if not (int(current.get('revision',0))>=int(prior.get('revision',0))):raise ValueError("Invalid licence authorization")
        return dict(license),issued
    except Exception as exc:
        raise ValueError('Invalid signed licence or controller binding') from exc

class LicenseClock:
    """Monotonic progress within a boot; persisted high-water mark across boots."""
    def __init__(self):self.lock=threading.Lock();self.anchor=None;self.tick=None
    def now(self,*,issued=None,persisted=None,wall=None):
        with self.lock:
            tick=time.monotonic();wall=wall or datetime.now(UTC)
            candidates=[wall] if self.anchor is None else []
            if issued:candidates.append(issued)
            if persisted:candidates.append(persisted)
            if self.anchor is not None:candidates.append(self.anchor+timedelta(seconds=max(0,tick-self.tick)))
            self.anchor=max(candidates);self.tick=tick
            return self.anchor
    def reset(self,issued):
        with self.lock:self.anchor=issued;self.tick=time.monotonic()
clock=LicenseClock()

def verify_commissioning(envelope,config,hardware,*,key=None):
    """Existing signed installer files remain valid local cash-only licences."""
    try:
        body={k:v for k,v in envelope.items() if k!='signature'}
        Ed25519PublicKey.from_public_bytes(decode(key or public_key())).verify(decode(envelope['signature']),canonical(body))
        if body['schema']!='sammoy.commissioning-response.v1':raise ValueError()
        if body['site_code']!=config['site_code'] or int(body['post_no'])!=int(config['post_no']):raise ValueError()
        code=body['offline_code'].split('.')
        if len(code)!=3 or code[0]!='OL1':raise ValueError()
        grant=json.loads(decode(code[1]))
        if grant['site']!=config['site_code'] or int(grant['post'])!=int(config['post_no']):raise ValueError()
        if not hardware.get('hardware_fingerprint_hash') or grant['hardware_fingerprint_hash']!=hardware['hardware_fingerprint_hash']:raise ValueError()
        if grant['action']!='activate' or grant['operation_mode']!='offline_cash_only' or grant['license_duration_type']!='permanent':raise ValueError()
        return {'site_code':config['site_code'],'post_no':int(config['post_no']),'enabled':True,'locked':False,
                'license_duration_type':'permanent','operation_mode':'offline_cash_only','authorization_mode':'local_signed',
                'online_lease_until':None,'valid_until':None,'hardware_bound':True},datetime.fromtimestamp(grant['iat'],UTC)
    except Exception as exc:raise ValueError('Invalid signed commissioning licence') from exc
