import unittest
from copy import deepcopy
from datetime import UTC,datetime,timedelta
from app.wallet_domain import WalletState,WalletPolicy,WalletConflict,apply_command

class VipImportTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,12,12,tzinfo=UTC);self.policy=WalletPolicy()
        self.state=WalletState('ABCD')
        self.profile={'id':1,'code':'VIP','name':'VIP','enabled':True,'grant_seconds':600,'max_uses_per_day':5}
        self.source={'uid':'ABCD','enabled':True,'status':'active','display_name':'Client','expires_at':None,'daily_uses':{'2026-10-12':2},'visit':None}
    def import_card(self,post=2,source=None):
        self.state,r=apply_command(self.state,{'action':'import_vip','post_no':post,'receipt_id':f'vip-import:post:{post}:ABCD','profile':self.profile,'snapshot':source or self.source},now=self.now,policy=self.policy)
        return r
    def grant(self):
        self.state,r=apply_command(self.state,{'action':'grant_vip','post_no':7,'assignment_id':'a','visit_id':'new'},now=self.now,policy=self.policy)
        return r
    def visit(self,remaining=1000,pause=10000):
        self.source['visit']={'remaining_sum':remaining,'pause_millis':pause,'expires_at':(self.now+timedelta(minutes=20)).isoformat(),'timeout_minutes':30,'water_reference':{'amount_sum':0,'duration_seconds':0}}
    def test_repeated_import_is_idempotent_and_not_money(self):
        self.import_card();before=deepcopy(self.state);self.assertTrue(self.import_card()['already_imported']);self.assertEqual(self.state,before)
        self.assertEqual((self.state.wallet_sum,self.state.opening_sum,self.state.external_income_sum),(0,0,0))
    def test_independent_sources_sum_daily_uses(self):
        self.import_card();self.import_card(3);self.assertEqual(self.state.vip_uses['2026-10-12'],4)
        self.grant();self.assertEqual(self.state.vip_uses['2026-10-12'],5)
    def test_changed_source_receipt_rejected(self):
        self.import_card();self.source['daily_uses']['2026-10-12']=3
        with self.assertRaises(WalletConflict):self.import_card()
    def test_preserved_allowance_and_pause_do_not_consume_another_daily_use(self):
        self.visit();self.import_card();r=self.grant();self.assertTrue(r['continued']);self.assertEqual((r['balance_sum'],r['pause_millis']),(1000,10000));self.assertEqual(self.state.vip_uses['2026-10-12'],2)
    def test_spent_local_visit_cannot_reset_free_pause(self):
        self.visit(0,0);self.import_card();r=self.grant();self.assertFalse(r['continued']);self.assertEqual(r['pause_millis'],0)
    def test_expired_local_visit_allows_normal_new_visit(self):
        self.visit(1000,10000);self.source['visit']['expires_at']=(self.now-timedelta(minutes=1)).isoformat();self.import_card();r=self.grant();self.assertFalse(r['continued']);self.assertEqual(r['pause_millis'],60000)
    def test_global_profile_edit_keeps_existing_pause(self):
        self.visit();self.import_card();self.grant()
        for cmd in [{'action':'checkpoint_vip','post_no':7,'assignment_id':'a','remaining_sum':900,'pause_millis':1000},{'action':'return_vip','post_no':7,'assignment_id':'a'},{'action':'configure_vip','profile':{**self.profile,'name':'Changed'},'display_name':'Client'}]:
            self.state,_=apply_command(self.state,cmd,now=self.now,policy=self.policy)
        self.assertEqual(self.grant()['pause_millis'],1000)
    def test_blocked_and_expired_flags_survive(self):
        for status in ['blocked','lost','expired']:
            self.state=WalletState('ABCD');self.source['status']=status;self.import_card()
            with self.assertRaises(WalletConflict):self.grant()
    def test_expiry_is_enforced_without_changing_status(self):
        self.source['expires_at']=(self.now-timedelta(seconds=1)).isoformat();self.import_card()
        with self.assertRaises(WalletConflict):self.grant()
    def test_money_card_cannot_be_overwritten(self):
        self.state,_=apply_command(self.state,{'action':'import_opening','amount_sum':35000},now=self.now,policy=self.policy)
        with self.assertRaises(WalletConflict):self.import_card()
    def test_active_card_cannot_import_another_source(self):
        self.import_card();self.grant()
        with self.assertRaises(WalletConflict):self.import_card(3)
    def test_conflicting_card_metadata_requires_review(self):
        self.import_card();self.source['display_name']='Other'
        with self.assertRaises(WalletConflict):self.import_card(3)
    def test_future_daily_history_is_rejected(self):
        self.source['daily_uses']={'2026-10-13':1}
        with self.assertRaises(WalletConflict):self.import_card()
    def test_revoke_discards_virtual_allowance_and_expiry_but_not_daily_usage(self):
        self.visit();self.source['expires_at']=(self.now+timedelta(days=1)).isoformat();self.import_card()
        self.state,_=apply_command(self.state,{'action':'remove_vip'},now=self.now,policy=self.policy)
        self.assertNotIn('vip_import_visits',self.state.service_configuration);self.assertNotIn('vip_expires_at',self.state.service_configuration);self.assertEqual(self.state.vip_uses['2026-10-12'],2)
