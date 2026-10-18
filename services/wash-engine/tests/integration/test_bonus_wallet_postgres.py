from test_wallet_post_adapter_postgres import PostAdapterTests as BasePost
from app import wallet_post,bonus_credit
from unittest.mock import patch
class BonusWalletTests(BasePost):
    def setUp(self):
        super().setUp();self.extra_patch=patch.object(bonus_credit,'db',wallet_post.db);self.extra_patch.start()
        self.runtime.params['topUpBonus']={'enabled':True,'percent':10}
    def tearDown(self):self.extra_patch.stop();super().tearDown()
    def test_bonus_moves_to_other_post_once_and_is_spent_first(self):
        wallet_post.handle_card(self.runtime,'CARD',{})
        self.runtime._accept_cash_locked(50000,'bill_pulse',50,{'test':True})
        self.assertEqual((self.runtime.state['creditSum'],self.runtime.state['bonusSum']),(90000,5000))
        spent=self.runtime._charge_active_locked('water',80)
        self.runtime._track_usage_locked('water','active',80,spent)
        wallet_post.handle_card(self.runtime,'CARD',{})
        s=self.primary.inspect('CARD')['state']
        self.assertEqual((s['wallet_sum'],s['wallet_bonus_sum'],s['bonus_issued_sum'],s['external_income_sum']),(88000,3000,5000,50000))
        self.post_no=7
        wallet_post.handle_card(self.runtime,'CARD',{})
        self.assertEqual((self.runtime.state['creditSum'],self.runtime.state['bonusSum']),(88000,3000))
        wallet_post.handle_card(self.runtime,'CARD',{})
        self.assertEqual(self.primary.inspect('CARD')['state']['bonus_issued_sum'],5000)
        self.assertEqual(self.primary.state_digest(),self.backup.state_digest())
    def test_anonymous_bonus_binds_to_shared_card(self):
        self.runtime._accept_cash_locked(50000,'bill_pulse',50,{'test':True})
        wallet_post.handle_card(self.runtime,'CARD',{})
        s=self.primary.inspect('CARD')['state']
        self.assertEqual((s['wallet_sum'],s['wallet_bonus_sum'],s['opening_sum'],s['external_income_sum']),(90000,5000,85000,0))
    def test_spend_then_topup_keeps_new_bonus_on_return(self):
        wallet_post.handle_card(self.runtime,'CARD',{})
        spent=self.runtime._charge_active_locked('water',400)
        self.runtime._track_usage_locked('water','active',400,spent)
        self.runtime._accept_cash_locked(10000,'bill_pulse',10,{'test':True})
        wallet_post.handle_card(self.runtime,'CARD',{})
        s=self.primary.inspect('CARD')['state']
        self.assertEqual((s['wallet_sum'],s['wallet_bonus_sum'],s['bonus_spent_sum'],s['spent_sum']),(36000,1000,0,10000))
