import unittest
from unittest.mock import patch,AsyncMock,Mock
from fastapi import HTTPException
from app import main
class InstallReadinessTests(unittest.IsolatedAsyncioTestCase):
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
