import unittest
from datetime import datetime,timezone
from app.bonus import award,policy
from app.wallet_domain import WalletState,WalletPolicy,apply_command,WalletConflict
from app.wash_logic import WashRuntime,normalize_parameters
class BonusTests(unittest.TestCase):
    def test_policy_rounding_and_disable(self):
        self.assertEqual(award(50000,{'topUpBonus':{'enabled':True,'percent':10}}),5000)
        self.assertEqual(award(999,{'topUpBonus':{'enabled':True,'percent':10}}),99)
        self.assertEqual(award(50000,{}),0)
        for p in [-1,101,True,1.5]:
            with self.assertRaises(ValueError):policy({'enabled':True,'percent':p})
    def apply(self,s,c):return apply_command(s,c,now=datetime.now(timezone.utc),policy=WalletPolicy())[0]
    def test_wallet_roundtrip_spends_bonus_first_never_reawards(self):
        s=self.apply(WalletState('ABCD'),{'action':'wallet_credit','source':'click','receipt_id':'c1','amount_sum':50000,'bonus_sum':5000})
        for i in range(3):
            s=self.apply(s,{'action':'reserve_load','post_no':2,'assignment_id':str(i),'visit_id':'visit'})
            s=self.apply(s,{'action':'accept_load','post_no':2,'assignment_id':str(i)})
            s=self.apply(s,{'action':'spend','post_no':2,'assignment_id':str(i),'amount_sum':2000})
            s=self.apply(s,{'action':'prepare_return','post_no':2,'assignment_id':str(i)})
            s=self.apply(s,{'action':'complete_return','post_no':2,'assignment_id':str(i)})
        self.assertEqual((s.wallet_sum,s.wallet_bonus_sum,s.bonus_spent_sum,s.bonus_issued_sum,s.external_income_sum),(49000,0,5000,5000,50000))
        same=self.apply(s,{'action':'wallet_credit','source':'click','receipt_id':'c1','amount_sum':50000,'bonus_sum':5000})
        self.assertEqual(same.wallet_sum,49000)
        with self.assertRaises(WalletConflict):self.apply(s,{'action':'wallet_credit','source':'click','receipt_id':'c1','amount_sum':50000,'bonus_sum':10000})
    def test_checkpoint_duplicate_and_money_conservation(self):
        s=self.apply(WalletState('ABCD'),{'action':'open_post','post_no':2,'assignment_id':'a','visit_id':'v','amount_sum':55000,'bonus_sum':5000,'pause_millis':60000})
        c={'action':'checkpoint','post_no':2,'assignment_id':'a','remaining_sum':63000,'pause_millis':50000,'funding':[{'id':'cash1','source':'cash','amount_sum':10000,'bonus_sum':1000}]}
        s=self.apply(s,c);s=self.apply(s,c)
        self.assertEqual((s.external_income_sum,s.bonus_issued_sum,s.bonus_spent_sum,s.assignment['bonus_sum']),(10000,6000,3000,3000))
    def test_paid_pause_uses_bonus_and_preserves_cash(self):
        r=WashRuntime();r.state.update(creditSum=55000,_creditFloat=55000.,bonusSum=5000,_bonusFloat=5000.)
        r._charge_paid_pause_locked(120)
        self.assertEqual((r.state['creditSum'],r.state['bonusSum']),(54000,4000))
        r._charge_active_locked('water',200)
        self.assertEqual((r.state['creditSum'],r.state['bonusSum']),(49000,0))
    def test_local_import_is_opening_not_new_payment(self):
        s=self.apply(WalletState('ABCD'),{'action':'import_local_balance','amount_sum':55000,'bonus_sum':5000,'receipt_id':'local-import:1','enabled':True,'status':'active'})
        self.assertEqual((s.opening_sum,s.external_income_sum,s.wallet_bonus_sum),(50000,0,5000))
    def test_pure_bonus_recovery_and_vip_rejection(self):
        s=self.apply(WalletState('ABCD'),{'action':'wallet_credit','amount_sum':0,'bonus_sum':3000,'receipt_id':'recovery:1','source':'cash'})
        self.assertEqual(s.wallet_sum,3000)
        with self.assertRaises(WalletConflict):self.apply(WalletState('VIP',card_type='vip'),{'action':'wallet_credit','amount_sum':100,'bonus_sum':10,'receipt_id':'v','source':'cash'})

    def test_topup_after_spending_does_not_retroactively_consume_new_bonus(self):
        s=self.apply(WalletState('ABCD'),{'action':'open_post','post_no':2,'assignment_id':'a','visit_id':'v','amount_sum':50000,'pause_millis':60000})
        s=self.apply(s,{'action':'checkpoint','post_no':2,'assignment_id':'a','remaining_sum':51000,'remaining_bonus_sum':1000,'pause_millis':60000,'funding':[{'id':'cash1','source':'cash','amount_sum':10000,'bonus_sum':1000}]})
        self.assertEqual((s.spent_sum,s.bonus_spent_sum,s.assignment['bonus_sum']),(10000,0,1000))

    def test_old_primary_is_rejected_before_bonus_transfer(self):
        from unittest.mock import patch
        from app import wallet_client,wallet_api
        from app.wallet_replication import WalletUnavailable
        cfg={'local_post':2,'primary_post':1,'generation':1}
        with patch.object(wallet_client,'discover_configuration',return_value=cfg),patch.object(wallet_api,'rpc',return_value={'local_post':1,'generation':1}) as rpc:
            with self.assertRaises(WalletUnavailable):wallet_client.execute('op','ABCD',{'action':'open_post','post_no':2,'amount_sum':55000,'bonus_sum':5000})
            self.assertEqual([c.args[2] for c in rpc.call_args_list],['status'])
