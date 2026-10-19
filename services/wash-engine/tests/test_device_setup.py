import unittest
from copy import deepcopy
from unittest.mock import patch,Mock
from pydantic import ValidationError
from app.device_setup import DevicePolicy,LocalDevice,apply_award,require_idle,fog_kiosk_config,policy_from_row
from app.kiosk_defaults import normalize_kiosk_settings
from app.wallet_domain import WalletConflict

class DeviceSetupTests(unittest.TestCase):
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
