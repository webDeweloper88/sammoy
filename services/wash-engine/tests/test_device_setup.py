import unittest
from copy import deepcopy
from unittest.mock import patch,Mock
from pydantic import ValidationError
from app.device_setup import DevicePolicy,LocalDevice,apply_award,require_idle,fog_kiosk_config,policy_from_row
from app.kiosk_defaults import normalize_kiosk_settings
from app.wallet_domain import WalletConflict
from fastapi import HTTPException
from app import device_setup
from app.wallet_replication import WalletUnavailable

class DeviceSetupTests(unittest.TestCase):
    def test_standby_reads_primary_policy_with_its_own_identity(self):
        cfg={'primary_post':1,'local_post':2,'peer_urls':{'1':'http://10.0.0.8','2':'http://10.0.0.7'}}
        with patch('app.wallet_client.discover_configuration',return_value=cfg),patch('app.wallet_api.rpc',return_value={'ok':True,'policy':{'enabled':True},'configuration':{'local_post':1}}):
            result=device_setup.read_policy({'login':'installer'})
        self.assertEqual(result['configuration']['local_post'],2)
        self.assertEqual(result['configuration']['primary_post'],1)
        self.assertTrue(result['policy']['enabled'])

    def test_standby_write_returns_conflict_instead_of_500(self):
        with patch('app.wallet_api.configuration',return_value={'primary_post':1,'local_post':2}),patch('app.wallet_api.coordinator') as coordinator:
            with self.assertRaises(HTTPException) as error:
                device_setup.save_policy(DevicePolicy(device_types={'1':'wash','2':'dry_fog'}),{'login':'installer'})
            self.assertEqual(error.exception.status_code,409)
            coordinator.assert_not_called()

    def test_unavailable_primary_read_returns_503_instead_of_500(self):
        with patch('app.wallet_client.discover_configuration',side_effect=WalletUnavailable('Primary unavailable')):
            with self.assertRaises(HTTPException) as error:device_setup.read_policy({'login':'installer'})
        self.assertEqual(error.exception.status_code,503)

    def test_duplicate_peer_addresses_rejected_before_setup(self):
        from app.wallet_api import setup,SetupRequest
        with patch('app.wallet_api.configuration') as config:
            with self.assertRaises(HTTPException) as error:
                setup(SetupRequest(primary_post=1,standby_post=2,peer_urls={'1':'http://10.0.0.8','2':'http://10.0.0.8:80/'}),{'login':'installer'})
            self.assertEqual(error.exception.status_code,422)
            config.assert_not_called()

    def test_policy_roundtrip_and_strict_inputs(self):
        p=DevicePolicy(device_types={'1':'wash','2':'dry_fog'},bonus_mode='separate').model_dump()
        self.assertEqual(policy_from_row({'state':{'service_configuration':{'device_policy':p}}}),p)
        for change in ({'bonus_mode':'bad'},{'shared':{'enabled':True,'percent':101}},{'device_types':{'1':'unknown'}}):
            with self.assertRaises(ValidationError):DevicePolicy(**{**p,**change})
        with self.assertRaises(ValidationError):LocalDevice(type='unknown')
    def test_existing_session_keeps_bonus_until_next_session(self):
        r=Mock(device_type='dry_fog');r.params={'topUpBonus':{'enabled':True,'percent':10}};r.state={'creditSum':1000}
        p=DevicePolicy(device_types={'2':'dry_fog'},bonus_mode='separate',dry_fog={'enabled':True,'percent':20}).model_dump()
        apply_award(r,{'device_policy':p});self.assertEqual(r.params['topUpBonus']['percent'],10)
        r.state={};apply_award(r,{'device_policy':p});self.assertEqual(r.params['topUpBonus']['percent'],20);self.assertEqual(r.params['bonusDomain'],'dry_fog')
    def test_pending_cash_or_job_prevents_type_change(self):
        for key in ('creditSum','activeSessionId','walletTransferPending','walletCashHeld','requestedOutput'):
            r=Mock(state={key:1})
            with self.assertRaises(WalletConflict):require_idle(r)
    def test_fog_kiosk_has_only_seven_client_services_and_keeps_custom_labels(self):
        c=normalize_kiosk_settings({'programs':[{'id':'aroma_1','label':{'uz':'MY SCENT'}}]})
        result=fog_kiosk_config(c)
        self.assertEqual(len(result['programs']),7);self.assertNotIn('purge',[p['id'] for p in result['programs']])
        self.assertEqual(result['programs'][0]['label']['uz'],'MY SCENT')
        self.assertEqual(result['brand']['name'],'LABRIX AROMA')

    def test_commissioned_fog_starts_without_contacting_reset_standby(self):
        cfg={'enabled':True,'primary_post':1,'standby_post':2,'local_post':1,'device_wallet_enabled':True,'device_types':{'1':'dry_fog'}}
        runtime=Mock(device_type='dry_fog')
        with patch('app.config.settings.device_type','dry_fog'),patch('app.wallet_api.configuration',return_value=cfg),patch.object(device_setup,'local_status',return_value={'requested':{'type':'dry_fog'}}),patch('app.wallet_client.require_device_wallet_support',side_effect=WalletUnavailable('Peer response authentication failed')) as proof,patch('app.wallet_api.rpc') as rpc:
            device_setup.startup_guard(runtime)
            proof.assert_not_called();rpc.assert_not_called()
            cfg['device_wallet_enabled']=False
            with self.assertRaises(RuntimeError):device_setup.startup_guard(runtime)
            cfg['device_wallet_enabled']=True;cfg['device_types']['1']='wash'
            with self.assertRaises(RuntimeError):device_setup.startup_guard(runtime)

    def test_pending_wash_request_does_not_crash_commissioned_fog(self):
        cfg={'enabled':True,'primary_post':1,'standby_post':2,'local_post':1,'device_wallet_enabled':True,'device_types':{'1':'dry_fog'}}
        runtime=Mock(device_type='dry_fog')
        with patch('app.config.settings.device_type','dry_fog'),patch('app.wallet_api.configuration',return_value=cfg),patch.object(device_setup,'local_status',return_value={'requested':{'type':'wash'}}):
            device_setup.startup_guard(runtime)
            cfg['device_types']['1']='wash'
            with self.assertRaises(RuntimeError):device_setup.startup_guard(runtime)
