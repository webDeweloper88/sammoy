import threading
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
import test_wash_logic
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.auth import current_user
from app import system_api


class SystemControlTests(unittest.TestCase):
    def test_hardware_installation_refuses_closed_or_funded_station(self):
        payload=system_api.HardwareRequest(request_id=uuid4())
        with patch.object(system_api.httpx,'Client') as host:
            with self.assertRaises(HTTPException) as error:
                system_api.request_hardware_apply(payload,{'complete':True})
            self.assertEqual(error.exception.status_code,403)
            runtime=Mock(lock=threading.RLock(),snapshot=Mock(return_value={'state':{'creditSum':1}}))
            with patch.object(system_api,'wash_runtime',runtime):
                with self.assertRaises(HTTPException) as error:
                    system_api.request_hardware_apply(payload,{'complete':False})
                self.assertEqual(error.exception.status_code,409)
            host.assert_not_called()

    def test_hardware_installation_sends_fixed_action_and_returns_receipt_only(self):
        payload=system_api.HardwareRequest(request_id=uuid4())
        runtime=Mock(lock=threading.RLock(),snapshot=Mock(return_value={'state':{}}))
        with patch.object(system_api,'wash_runtime',runtime),patch.object(system_api.httpx,'Client') as host:
            response=host.return_value.__enter__.return_value.post.return_value
            response.status_code=202
            response.json.return_value={'ok':True,'request_id':str(payload.request_id),'action':'hardware','status':'accepted','actor':'private'}
            result=system_api.request_hardware_apply(payload,{'complete':False})
            self.assertNotIn('actor',result)
            self.assertEqual(host.return_value.__enter__.return_value.post.call_args.kwargs['json'],
                             {'action':'hardware','request_id':str(payload.request_id),'actor':'installer'})
            response.status_code=409
            with self.assertRaises(HTTPException):system_api.request_hardware_apply(payload,{'complete':False})

    def payload(self, action='reboot', **kwargs):
        return system_api.Action(action=action, request_id=uuid4(), confirmation=action.upper(), **kwargs)

    def test_full_reset_needs_admin_isolation_and_fresh_authentication(self):
        for role, action, isolation, issued, code in (
            ('owner','full',True,100,403), ('admin','full',False,100,409),
            ('admin','full',True,1,401), ('admin','reboot',False,110,401)):
            with self.subTest(role=role, action=action, code=code):
                with self.assertRaises(HTTPException) as error:
                    system_api.validate_action(self.payload(action, cluster_isolated=isolation), {'role':role}, issued, 101)
                self.assertEqual(error.exception.status_code, code)
        system_api.validate_action(self.payload('full', cluster_isolated=True), {'role':'admin'},100,101)

    def test_confirmation_and_enum_are_checked(self):
        p=self.payload();p.confirmation='wrong'
        with self.assertRaises(HTTPException):
            system_api.validate_action(p,{'role':'owner'},100,101)
        with self.assertRaises(ValueError):
            self.payload('shell')

    def test_no_auth_or_busy_station_never_reaches_host(self):
        app=FastAPI();app.include_router(system_api.router);client=TestClient(app)
        body=self.payload().model_dump(mode='json')
        self.assertEqual(client.post('/api/system/actions',json=body).status_code,401)
        app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner'}
        runtime=Mock(lock=threading.RLock(),snapshot=Mock(return_value={'state':{'creditSum':1}}))
        with patch.object(system_api,'wash_runtime',runtime),patch.object(system_api,'decode_access_token',return_value={'iat':100}),patch.object(system_api.time,'time',return_value=101),patch.object(system_api.httpx,'Client') as host:
            self.assertEqual(client.post('/api/system/actions',json=body,headers={'Authorization':'Bearer fresh'}).status_code,409)
            host.assert_not_called()


    def test_reset_receipt_survives_revoked_login_and_is_read_only(self):
        app=FastAPI();app.include_router(system_api.router);client=TestClient(app)
        request_id=str(uuid4())
        response=Mock(status_code=200,json=Mock(return_value={'ok':True,'request_id':request_id,'action':'full','status':'completed','actor':'private'}))
        with patch.object(system_api.httpx,'Client') as host:
            host.return_value.__enter__.return_value.get.return_value=response
            result=client.get('/api/system/actions/'+request_id)
            self.assertEqual(result.status_code,200);self.assertEqual(result.json()['status'],'completed')
            self.assertNotIn('actor',result.json());self.assertEqual(result.headers['cache-control'],'no-store')
            host.return_value.__enter__.return_value.post.assert_not_called()
            response.status_code=404
            self.assertEqual(client.get('/api/system/actions/'+str(uuid4())).status_code,404)
        self.assertEqual(client.get('/api/system/actions/not-a-uuid').status_code,422)
