import unittest
from datetime import UTC,datetime,timedelta
from app.wallet_domain import WalletState,WalletPolicy,WalletConflict,apply_command


class VipDomainTests(unittest.TestCase):
    def setUp(self):
        self.state=WalletState('VIP');self.now=datetime(2026,10,7,12,tzinfo=UTC);self.policy=WalletPolicy()
        self.apply('configure_vip',profile={'id':1,'code':'VIP','name':'VIP','enabled':True,'grant_seconds':600,'max_uses_per_day':1},enabled=True,status='active')
    def apply(self,action,**kwargs):
        self.state,result=apply_command(self.state,{'action':action,**kwargs},now=self.now,policy=self.policy)
        return result
    def grant(self,post=2,assignment='a',visit='v'):
        return self.apply('grant_vip',post_no=post,assignment_id=assignment,visit_id=visit)
    def checkpoint(self,remaining=9000,pause=10000):
        return self.apply('checkpoint_vip',post_no=2,assignment_id='a',remaining_sum=remaining,pause_millis=pause)
    def release(self):return self.apply('return_vip',post_no=2,assignment_id='a')
    def test_cross_post_continuation_keeps_remaining_and_one_daily_use(self):
        self.grant();self.checkpoint();self.release()
        result=self.grant(7,'b','attempt-new-visit')
        self.assertTrue(result['continued']);self.assertEqual(result['balance_sum'],9000)
        self.assertEqual(result['pause_millis'],10000)
        self.assertEqual(sum(self.state.vip_uses.values()),1)
        self.assertEqual(self.state.wallet_sum,0);self.assertEqual(self.state.external_income_sum,0)
    def test_second_post_cannot_use_active_vip(self):
        self.grant()
        with self.assertRaises(WalletConflict):self.grant(7,'b')
    def test_same_day_new_visit_expires_and_hits_daily_limit(self):
        self.grant();self.release();self.now+=timedelta(minutes=30)
        with self.assertRaises(WalletConflict):self.grant(7,'b','new')
    def test_next_day_new_grant_gets_new_pause_budget(self):
        self.grant();self.checkpoint(0,0);self.release();self.now+=timedelta(days=1)
        r=self.grant(7,'b','tomorrow')
        self.assertFalse(r['continued']);self.assertEqual(r['pause_millis'],60000)
        self.assertEqual(r['balance_sum'],15000)
    def test_snapshot_roundtrip_cannot_renew_vip_allowance(self):
        from dataclasses import asdict
        self.grant();self.checkpoint();self.state=WalletState(**asdict(self.state));self.release()
        self.assertEqual(self.grant(7,'b')['pause_millis'],10000)
    def test_checkpoint_cannot_mint_time_or_pause(self):
        self.grant()
        for remaining,pause in [(15001,10000),(9000,60001),(-1,0)]:
            with self.assertRaises(WalletConflict):self.checkpoint(remaining,pause)
    def test_owner_type_change_does_not_erase_money(self):
        money=WalletState('CARD')
        money,_=apply_command(money,{'action':'import_opening','amount_sum':35000},now=self.now,policy=self.policy)
        with self.assertRaises(WalletConflict):apply_command(money,{'action':'configure_vip','profile':self.state.vip_profile},now=self.now,policy=self.policy)
    def test_card_block_and_profile_disable_stop_new_grants(self):
        self.apply('configure_vip',profile=self.state.vip_profile,enabled=False,status='blocked')
        with self.assertRaises(WalletConflict):self.grant()
    def test_removing_and_recreating_card_does_not_reset_daily_uses(self):
        self.grant();self.checkpoint(0,0);self.release();profile=self.state.vip_profile
        self.apply('remove_vip');self.apply('configure_vip',profile=profile)
        with self.assertRaises(WalletConflict):self.grant(7,'b','new')
