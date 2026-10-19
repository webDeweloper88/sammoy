import threading
import unittest
from unittest.mock import Mock
import httpx
from fastapi import HTTPException
from app.admin_service import OUTPUTS, test_relay, all_off, require_idle

class AdminTests(unittest.TestCase):
    def runtime(self,**state):
        return Mock(device_type='wash',lock=threading.RLock(),snapshot=Mock(return_value={'state':{'creditSum':0,**state}}))
    def factory(self,handler):return lambda **kwargs:httpx.Client(transport=httpx.MockTransport(handler),**kwargs)
    def test_every_unfinished_session_is_guarded(self):
        for state in ({'creditSum':1},{'activeMode':'water'},{'requestedOutput':'water'},{'armedMode':'foam'},{'activeSessionId':5},{'vipRemainingSeconds':1}):
            with self.subTest(state=state),self.assertRaises(HTTPException):require_idle(self.runtime(**state))
    def test_relay_requires_confirmation(self):
        with self.assertRaises(HTTPException):test_relay(self.runtime(),'http://io','water','foam')
    def test_relay_verifies_all_off(self):
        calls=[]
        def handler(req):
            calls.append((req.method,req.url.path))
            return httpx.Response(200,json={'ok':True,'modbus_ok':True,'outputs':dict.fromkeys(OUTPUTS,False)})
        test_relay(self.runtime(),'http://io','water','water',self.factory(handler))
        self.assertEqual(calls,[('GET','/io'),('POST','/outputs/water/test'),('POST','/outputs/water'),('GET','/io')])
    def test_missing_output_readback_blocks_test(self):
        calls=[]
        def handler(req):calls.append(req.method);return httpx.Response(200,json={'modbus_ok':True,'outputs':{}})
        with self.assertRaises(HTTPException):test_relay(self.runtime(),'http://io','water','water',self.factory(handler))
        self.assertEqual(calls,['GET'])
    def test_all_off_attempts_every_output_and_keeps_credit(self):
        r=self.runtime(creditSum=1744);calls=[]
        def handler(req):
            calls.append(req.url.path)
            if req.url.path=='/outputs/water':return httpx.Response(503,json={'detail':'failure'})
            return httpx.Response(200,json={'modbus_ok':True,'outputs':dict.fromkeys(OUTPUTS,False)})
        with self.assertRaises(HTTPException):all_off(r,'http://io',self.factory(handler))
        self.assertEqual(calls,[f'/outputs/{name}' for name in OUTPUTS]+['/io'])
        r.select_mode.assert_called_once_with('pause');self.assertEqual(r.snapshot()['state']['creditSum'],1744)

    def test_fog_tests_all_eight_outputs_including_purge(self):
        from app.device_profiles import FOG_OUTPUTS
        for name in FOG_OUTPUTS:
            r=self.runtime();r.device_type='dry_fog';calls=[]
            def handler(req):
                calls.append(req.url.path)
                return httpx.Response(200,json={'ok':True,'modbus_ok':True,'outputs':dict.fromkeys(FOG_OUTPUTS,False)})
            test_relay(r,'http://io',name,name,self.factory(handler))
            self.assertIn('/outputs/'+name+'/test',calls)
        with self.assertRaises(HTTPException):test_relay(r,'http://io','water','water',self.factory(handler))
    def test_fog_all_off_uses_fog_map(self):
        from app.device_profiles import FOG_OUTPUTS
        r=self.runtime();r.device_type='dry_fog';calls=[]
        def handler(req):
            calls.append(req.url.path)
            return httpx.Response(200,json={'modbus_ok':True,'outputs':dict.fromkeys(FOG_OUTPUTS,False)})
        all_off(r,'http://io',self.factory(handler))
        self.assertEqual(calls,[f'/outputs/{name}' for name in FOG_OUTPUTS]+['/io'])
