import unittest
from unittest.mock import patch,AsyncMock,Mock
from fastapi import HTTPException
from app import main
class InstallReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_hardware_endpoint_uses_commissioning_access_and_strict_body(self):
        from fastapi.testclient import TestClient
        from uuid import uuid4
        client=TestClient(main.app)
        body={'request_id':str(uuid4())}
        with patch.object(main,'get_commissioning_state',return_value={'complete':False}),patch.object(main,'request_hardware_apply',return_value={'ok':True,'status':'accepted'}) as apply:
            self.assertEqual(client.post('/api/commissioning/hardware',json=body).status_code,403)
            apply.assert_not_called()
            headers={'X-Commissioning-Client-IP':'127.0.0.1'}
            self.assertEqual(client.post('/api/commissioning/hardware',json={**body,'command':'sh'},headers=headers).status_code,422)
            apply.assert_not_called()
            self.assertEqual(client.post('/api/commissioning/hardware',json=body,headers=headers).status_code,200)
            self.assertEqual(str(apply.call_args.args[0].request_id),body['request_id'])
        with patch.object(main,'get_commissioning_state',return_value={'complete':True}):
            self.assertEqual(client.post('/api/commissioning/hardware',json=body,headers=headers).status_code,403)

    async def test_successful_http_does_not_prove_modbus_ready(self):
        with patch.object(main,'get_license_settings',return_value={'site_code':'S','site_token':'T'}),patch.object(main,'get_hardware_identity',return_value={'complete':True}),patch.object(main,'apply_license_to_runtime',return_value={'locked':False}),patch.object(main,'io_request',AsyncMock(return_value={'status':'ok','modbus_ok':False})),patch.object(main,'db') as db:
            with self.assertRaises(HTTPException) as caught:await main.commissioning_complete(Mock())
            self.assertEqual(caught.exception.status_code,409);db.assert_not_called()
    async def test_installed_post_cannot_reconfigure_network_without_admin(self):
        with patch.object(main,'get_commissioning_state',return_value={'complete':True}),patch('app.admin_api.network_request',new_callable=AsyncMock) as request:
            with self.assertRaises(HTTPException):await main.commissioning_network_action('apply',{'interface':'eth0'})
            request.assert_not_awaited()
    async def test_preinstall_network_uses_existing_rollback_agent(self):
        with patch.object(main,'get_commissioning_state',return_value={'complete':False}),patch('app.admin_api.network_request',new_callable=AsyncMock,return_value={'pending':{'id':'checkpoint'}}) as request,patch('app.admin_service.require_idle') as idle:
            result=await main.commissioning_network_action('apply',{'interface':'eth0'})
            idle.assert_called_once();request.assert_awaited_once_with('/apply','POST',{'interface':'eth0'});self.assertEqual(result['pending']['id'],'checkpoint')

    async def test_funded_session_cannot_be_activated_or_completed(self):
        from app.schema import CommissioningClaimRequest
        with patch.object(main.wash_runtime,'snapshot',return_value={'state':{'creditSum':1000}}),patch.object(main,'db') as db:
            for action in (lambda:main.commissioning_complete(Mock()),lambda:main.commissioning_claim(CommissioningClaimRequest(gateway_url='https://activation.invalid',activation_code='ABCD1234',click_enabled=False))):
                with self.assertRaises(HTTPException) as caught:await action()
                self.assertEqual(caught.exception.status_code,409)
            db.assert_not_called()

    async def test_telegram_setup_closed_after_install(self):
        with patch.object(main,'get_commissioning_state',return_value={'complete':True}),patch.object(main,'telegram_setup_request',new_callable=AsyncMock) as request:
            with self.assertRaises(HTTPException):await main.commissioning_telegram_status()
            with self.assertRaises(HTTPException):await main.commissioning_telegram_action('configure-auto',{})
            request.assert_not_awaited()
    async def test_installer_cannot_replace_paired_owner(self):
        with patch.object(main,'get_commissioning_state',return_value={'complete':False}),patch('app.admin_service.require_idle'),patch.object(main,'get_license_settings',return_value={'site_code':'S'}),patch.object(main,'apply_license_to_runtime',return_value={'locked':False}),patch('app.wallet_api.configuration',return_value={'enabled':False}),patch.object(main,'owner_telegram_action',new_callable=AsyncMock) as action:
            with self.assertRaises(HTTPException):await main.commissioning_telegram_action('pairing',{'reset_owner':True})
            action.assert_not_awaited()

    async def test_temporary_wifi_closed_after_install(self):
        with patch.object(main,'get_commissioning_state',return_value={'complete':True}),patch('app.admin_api.network_request',new_callable=AsyncMock) as request:
            for action in ('temporary-connect','temporary-disconnect'):
                with self.assertRaises(HTTPException):await main.commissioning_network_action(action,{})
            with self.assertRaises(HTTPException):await main.commissioning_internet()
            request.assert_not_awaited()
    async def test_temporary_wifi_requires_idle_and_forwards_to_agent(self):
        with patch.object(main,'get_commissioning_state',return_value={'complete':False}),patch('app.admin_api.network_request',new_callable=AsyncMock,return_value={'ok':True}) as request,patch('app.admin_service.require_idle') as idle:
            for action in ('temporary-connect','temporary-disconnect'):
                await main.commissioning_network_action(action,{})
                request.assert_awaited_with('/'+action,'POST',{})
            self.assertEqual(idle.call_count,2)
    async def test_hotspot_cleanup_is_explicit_at_completion(self):
        from app.schema import CommissioningCompleteRequest
        self.assertFalse(CommissioningCompleteRequest(confirmation='READY').disconnect_temporary_wifi)
        with patch('app.admin_service.require_idle'),patch.object(main,'get_license_settings',return_value={'site_code':'S','site_token':'T','post_no':1}),patch.object(main,'get_hardware_identity',return_value={'complete':True}),patch.object(main,'apply_license_to_runtime',return_value={'locked':False}),patch.object(main,'io_request',AsyncMock(return_value={'modbus_ok':True})),patch('app.device_setup.local_status',return_value={'active_type':'wash','requested':{'type':'wash'}}),patch.object(main,'db'),patch.object(main,'commissioning_status',AsyncMock(return_value={'ok':True})),patch('app.admin_api.network_request',AsyncMock(return_value={'scheduled':True})) as request:
            result=await main.commissioning_complete(CommissioningCompleteRequest(confirmation='READY',disconnect_temporary_wifi=True))
            request.assert_awaited_once_with('/temporary-finish','POST',{})
            self.assertTrue(result['temporary_wifi_cleanup']['scheduled'])
    async def test_internet_check_before_activation_uses_configured_gateway(self):
        response=Mock();client=AsyncMock();client.get.return_value=response
        with patch.object(main,'get_commissioning_state',return_value={'complete':False}),patch.object(main,'get_license_settings',return_value={'gateway_url':'https://pay.labrix.uz','site_code':''}),patch.object(main.httpx,'AsyncClient') as factory:
            factory.return_value.__aenter__.return_value=client
            self.assertTrue((await main.commissioning_internet())['reachable'])
            client.get.assert_awaited_once_with('https://pay.labrix.uz/health')
