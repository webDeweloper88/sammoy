import unittest
from datetime import UTC,datetime
from copy import deepcopy
from app.wallet_domain import WalletState,WalletPolicy,WalletConflict,apply_command

class CustomerDomainTests(unittest.TestCase):
    def apply(self,state,command):return apply_command(state,command,now=datetime.now(UTC),policy=WalletPolicy())
    def test_metadata_update_preserves_money_and_pause(self):
        state=WalletState('ABCD',wallet_sum=35000,opening_sum=35000,visit={'id':'v','pause_millis':1234})
        updated,_=self.apply(state,{'action':'configure_customer','display_name':'Client','enabled':False,'status':'lost'})
        self.assertEqual(updated.wallet_sum,35000);self.assertEqual(updated.visit,state.visit)
        self.assertEqual(updated.status,'lost');self.assertFalse(updated.enabled);self.assertEqual(state.status,'active')
    def test_vip_cannot_be_changed_to_customer_in_this_registry(self):
        state=WalletState('ABCD',card_type='vip')
        with self.assertRaises(WalletConflict):self.apply(state,{'action':'configure_customer','enabled':True,'status':'active'})
    def test_import_is_opening_balance_not_new_revenue_and_keeps_block(self):
        command={'action':'import_local_balance','receipt_id':'local-import:test','amount_sum':35000,'status':'blocked','enabled':False}
        state,_=self.apply(WalletState('ABCD'),command)
        self.assertEqual(state.opening_sum,35000);self.assertEqual(state.external_income_sum,0)
        self.assertEqual(state.wallet_sum,35000);self.assertEqual(state.status,'blocked');self.assertFalse(state.enabled)
        repeat,_=self.apply(state,command);self.assertEqual(repeat.wallet_sum,35000)
        with self.assertRaises(WalletConflict):self.apply(state,{**command,'amount_sum':36000})
