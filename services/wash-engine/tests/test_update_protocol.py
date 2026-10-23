import base64
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.update_protocol import canonical,verify_release

class ReleaseProtocolTests(unittest.TestCase):
    def setUp(self):
        self.key=Ed25519PrivateKey.generate()
        self.public=self.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        now=datetime.now(timezone.utc)
        self.m={'schema':1,'product':'labrix-wash','release_no':1,'version':'2026.10.23.1','hardware':'cubie-a7a','arch':'aarch64','channel':'stable','issued_at':(now-timedelta(minutes=1)).isoformat(),'expires_at':(now+timedelta(days=1)).isoformat(),'notes':{'ru':'Исправление','uz':'Tuzatish','en':'Fix'},'artifact':{'url':'https://pay.labrix.uz/api/v1/software/artifacts/'+'a'*64,'sha256':'a'*64,'bytes':100,'unpacked_bytes':1000,'image_bytes':2000},'services':{'wash-engine':'sha256:'+'b'*64},'db_contract':'c'*64,'agent_protocol':1,'wallet_protocol':1,'runtime_contract':1}
    def envelope(self,m=None):
        m=m or self.m
        return {'manifest':m,'signature':base64.b64encode(self.key.sign(canonical(m))).decode()}
    def test_signed_release_round_trip(self):self.assertEqual(verify_release(self.envelope(),self.public),self.m)
    def test_every_signed_field_is_bound(self):
        for field,value in [('version','evil'),('release_no',200),('notes',{'ru':'x','uz':'x','en':'x'}),('services',{'wash-engine':'sha256:'+'e'*64})]:
            e=self.envelope();e['manifest']=deepcopy(e['manifest']);e['manifest'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify_release(e,self.public)
    def test_wrong_key_cannot_authorize_release(self):
        other=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaises(ValueError):verify_release(self.envelope(),other)
    def test_signed_but_unsafe_manifest_is_rejected(self):
        variants=[]
        for field,value in [('arch','x86_64'),('hardware','other-board'),('release_no',True),('agent_protocol',2),('expires_at','2000-01-01T00:00:00Z')]:
            m=deepcopy(self.m);m[field]=value;variants.append(m)
        for url in ('http://pay.labrix.uz/a','https://evil.example/a','https://pay.labrix.uz@evil.example/a','https://pay.labrix.uz/api/v1/software/artifacts/'+'a'*64+'?redirect=1'):
            m=deepcopy(self.m);m['artifact']['url']=url;variants.append(m)
        m=deepcopy(self.m);m['services']['postgres']='sha256:'+'d'*64;variants.append(m)
        for m in variants:
            with self.subTest(manifest=m),self.assertRaises(ValueError):verify_release(self.envelope(m),self.public)
