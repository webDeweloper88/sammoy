import unittest
from datetime import UTC,datetime,timedelta
from copy import deepcopy
from app.wallet_domain import WalletState,WalletPolicy,WalletConflict,apply_command
from app.wallet_devices import state_dump

class DeviceWalletTests(unittest.TestCase):
    def setUp(self):
        self.s=WalletState('CARD');self.now=datetime(2026,10,19,10,tzinfo=UTC)
        self.policy=WalletPolicy(bonus_mode='separate');self.kind='wash';self.i=0
    def apply(self,action,**kw):
        self.s,r=apply_command(self.s,{'wallet_protocol':2,'device_type':self.kind,'action':action,**kw},now=self.now,policy=self.policy)
        return r
    def credit(self,amount=50000,bonus=5000):
        self.i+=1
        return self.apply('wallet_credit',source='cash',receipt_id='cash:'+str(self.i),amount_sum=amount,bonus_sum=bonus,bonus_domain=self.kind if self.policy.bonus_mode=='separate' else 'shared')
    def load(self):
        self.i+=1;self.a='a'+str(self.i)
        r=self.apply('reserve_load',post_no=self.i,assignment_id=self.a,visit_id='v'+str(self.i));self.post=self.i
        self.apply('accept_load',post_no=self.post,assignment_id=self.a);return r
    def bound(self,action,**kw):return self.apply(action,post_no=self.post,assignment_id=self.a,**kw)
    def save(self):self.bound('prepare_return');self.bound('complete_return')
    def vip(self,types=None):
        self.apply('configure_vip',profile={'grant_seconds':60,'max_uses_per_day':1,**({'device_types':types} if types is not None else {})})
    def grant(self,a='vipa',post=1):
        self.a=a;self.post=post
        return self.apply('grant_vip',post_no=post,assignment_id=a,visit_id='vipvisit')

    def test_legacy_snapshot_unchanged_and_migration_preserves_old_money_bonus_pause(self):
        self.assertNotIn('device_wallet',state_dump(self.s))
        self.s=apply_command(self.s,{'action':'wallet_credit','source':'cash','receipt_id':'old','amount_sum':50000,'bonus_sum':5000},now=self.now,policy=self.policy)[0]
        self.apply('migrate_device_wallet')
        self.assertEqual((self.s.wallet_sum,self.s.wallet_bonus_sum),(55000,5000))
        self.assertEqual(self.s.device_wallet['wallet_bonus'],{'shared':5000,'wash':0,'dry_fog':0})
        with self.assertRaises(WalletConflict):apply_command(self.s,{'action':'reserve_load','post_no':1,'assignment_id':'a','visit_id':'v'},now=self.now,policy=self.policy)
        with self.assertRaises(WalletConflict):apply_command(WalletState('NEW'),{'action':'reserve_load','device_type':'dry_fog'},now=self.now,policy=self.policy)

    def test_separate_bonus_cannot_cross_device_but_money_can(self):
        self.credit();self.kind='dry_fog';r=self.load()
        self.assertEqual(r['balance_sum'],50000);self.assertEqual(self.s.wallet_sum,5000)
        self.assertEqual(self.s.wallet_bonus_sum,5000);self.bound('spend',amount_sum=1000);self.save()
        self.assertEqual(self.s.wallet_sum,54000);self.kind='wash';r=self.load()
        self.assertEqual(r['balance_sum'],54000);self.assertEqual(r['bonus_sum'],5000)
        self.bound('spend',amount_sum=3000);self.save()
        self.assertEqual(self.s.device_wallet['wallet_bonus']['wash'],2000)
        self.assertEqual(self.s.spent_sum,4000);self.assertEqual(self.s.bonus_spent_sum,3000)

    def test_only_foreign_bonus_is_not_loadable(self):
        self.credit(amount=0,bonus=5000);before=deepcopy(self.s);self.kind='dry_fog'
        with self.assertRaises(WalletConflict):self.load()
        self.assertEqual(self.s,before)

    def test_shared_bonus_remains_shared_after_policy_changes(self):
        self.policy=WalletPolicy(bonus_mode='shared');self.credit();self.policy=WalletPolicy(bonus_mode='separate')
        self.kind='dry_fog';r=self.load();self.assertEqual(r['balance_sum'],55000)
        self.bound('spend',amount_sum=3000);self.save();self.assertEqual(self.s.device_wallet['wallet_bonus']['shared'],2000)

    def test_pause_budgets_survive_device_and_post_changes(self):
        self.credit();r=self.load();self.assertEqual(r['pause_millis'],60000)
        self.bound('consume_pause',elapsed_millis=45000);self.save()
        self.kind='dry_fog';r=self.load();self.assertEqual(r['pause_millis'],300000)
        self.bound('consume_pause',elapsed_millis=100000);self.save()
        self.kind='wash';r=self.load();self.assertEqual(r['pause_millis'],15000);self.save()
        self.kind='dry_fog';r=self.load();self.assertEqual(r['pause_millis'],200000)

    def test_new_visit_renews_both_budgets_after_timeout_only(self):
        self.credit();self.load();self.bound('consume_pause',elapsed_millis=60000);self.save()
        self.now+=timedelta(minutes=29);r=self.load();self.assertEqual(r['pause_millis'],0);self.save()
        self.now+=timedelta(minutes=31);r=self.load();self.assertEqual(r['pause_millis'],60000)
        self.assertEqual(self.s.device_wallet['pause_by_type']['dry_fog'],300000)

    def test_bound_assignment_cannot_change_type_or_replenish_pause(self):
        self.credit();self.load();before=deepcopy(self.s);self.kind='dry_fog'
        with self.assertRaises(WalletConflict):self.bound('consume_pause',elapsed_millis=1)
        self.assertEqual(self.s,before);self.kind='wash'
        with self.assertRaises(WalletConflict):self.bound('checkpoint',remaining_sum=55000,remaining_bonus_sum=5000,pause_millis=60001)

    def test_checkpoint_funding_keeps_bonus_domain_and_spends_specific_first(self):
        self.credit();self.load()
        self.bound('checkpoint',remaining_sum=62000,remaining_bonus_sum=6000,pause_millis=50000,
                   funding=[{'id':'cash:new','source':'cash','amount_sum':10000,'bonus_sum':1000,'bonus_domain':'wash'}])
        self.assertEqual(self.s.device_wallet['assignment_bonus']['wash'],6000)
        self.assertEqual(self.s.spent_sum,4000);self.save()
        self.kind='dry_fog';r=self.load();self.assertEqual(r['balance_sum'],56000)

    def test_duplicate_credit_does_not_duplicate_domain_bonus(self):
        self.credit();before=deepcopy(self.s)
        r=self.apply('wallet_credit',source='cash',receipt_id='cash:1',amount_sum=50000,bonus_sum=5000,bonus_domain='wash')
        self.assertTrue(r['already_credited']);self.assertEqual(self.s.wallet_sum,before.wallet_sum)
        self.assertEqual(self.s.device_wallet,before.device_wallet)
        self.kind='dry_fog'
        with self.assertRaises(WalletConflict):self.apply('wallet_credit',source='cash',receipt_id='cash:1',amount_sum=50000,bonus_sum=5000,bonus_domain='dry_fog')

    def test_vip_default_is_wash_only_and_scope_can_allow_both(self):
        self.vip();self.kind='dry_fog'
        with self.assertRaises(WalletConflict):self.grant()
        self.kind='wash';self.grant()
        self.assertEqual(self.s.vip_uses,{'2026-10-19':1})

    def test_vip_changes_type_without_second_daily_use_or_pause_reset(self):
        self.vip(['wash','dry_fog']);r=self.grant();self.assertEqual(r['balance_sum'],1500)
        self.bound('checkpoint_vip',remaining_sum=1000,pause_millis=20000);self.bound('return_vip')
        self.kind='dry_fog';r=self.grant('fog',2)
        self.assertTrue(r['continued']);self.assertEqual(r['balance_sum'],40000)
        self.assertEqual(r['pause_millis'],300000);self.assertEqual(self.s.vip_uses,{'2026-10-19':1})
        self.bound('checkpoint_vip',remaining_sum=30000,pause_millis=250000);self.bound('return_vip')
        self.kind='wash';r=self.grant('wash2',3)
        self.assertEqual(r['balance_sum'],750);self.assertEqual(r['pause_millis'],20000)
        self.assertEqual(self.s.wallet_sum,0);self.assertEqual(self.s.external_income_sum,0)

    def test_vip_cannot_be_used_simultaneously_or_grant_again_after_daily_limit(self):
        self.vip(['wash','dry_fog']);self.grant();before=deepcopy(self.s);self.kind='dry_fog'
        with self.assertRaises(WalletConflict):self.grant('other',2)
        self.assertEqual(self.s,before);self.kind='wash';self.a='vipa';self.post=1
        self.bound('checkpoint_vip',remaining_sum=0,pause_millis=0);self.bound('return_vip')
        with self.assertRaises(WalletConflict):self.grant('next',2)

    def test_corrupt_domains_and_old_protocol_are_rejected_without_mutation(self):
        self.credit();broken=deepcopy(self.s);broken.device_wallet['wallet_bonus']['wash']+=1
        with self.assertRaises(WalletConflict):broken.validate()
        before=deepcopy(self.s)
        for extra in ({'wallet_protocol':1},{'device_type':'unknown'},{'wallet_protocol':True}):
            with self.assertRaises(WalletConflict):apply_command(self.s,{'wallet_protocol':2,'device_type':'wash','action':'reserve_load',**extra},now=self.now,policy=self.policy)
        self.assertEqual(self.s,before)

    def test_protocol_support_requires_matching_primary_and_standby(self):
        from unittest.mock import patch
        from app.wallet_client import require_device_wallet_support
        from app.wallet_replication import WalletUnavailable
        cfg={'primary_post':1,'standby_post':7,'generation':4,'single_node':False}
        def proof(cfg,post,*args):return {'device_wallet_protocol':2,'local_post':post,'primary_post':1,'generation':4}
        with patch('app.wallet_api.rpc',side_effect=proof):require_device_wallet_support(cfg)
        for change in ({'device_wallet_protocol':1},{'generation':3},{'local_post':3}):
            def old(cfg,post,*args):return {**proof(cfg,post),**(change if post==7 else {})}
            with patch('app.wallet_api.rpc',side_effect=old),self.assertRaises(WalletUnavailable):require_device_wallet_support(cfg)

    def test_pending_award_keeps_its_original_domain_after_policy_change(self):
        self.credit();self.policy=WalletPolicy(bonus_mode='shared')
        self.apply('wallet_credit',source='click',receipt_id='old-wash-award',amount_sum=10000,bonus_sum=1000,bonus_domain='wash')
        self.assertEqual(self.s.device_wallet['wallet_bonus']['wash'],6000)
        self.kind='dry_fog';r=self.load();self.assertEqual(r['balance_sum'],60000)

    def test_checkpoint_combines_shared_and_scoped_receipts_without_losing_domains(self):
        self.credit();self.load()
        self.bound('checkpoint',remaining_sum=77000,remaining_bonus_sum=7000,pause_millis=50000,
                   funding=[{'id':'shared','source':'click','amount_sum':10000,'bonus_sum':1000,'bonus_domain':'shared'},
                            {'id':'scoped','source':'cash','amount_sum':10000,'bonus_sum':1000,'bonus_domain':'wash'}])
        self.assertEqual(self.s.device_wallet['assignment_bonus'],{'shared':1000,'wash':6000,'dry_fog':0})
        self.bound('spend',amount_sum=3000)
        self.assertEqual(self.s.device_wallet['assignment_bonus'],{'shared':1000,'wash':3000,'dry_fog':0})

    def test_migrating_a_live_legacy_assignment_is_rejected(self):
        self.s=apply_command(self.s,{'action':'import_opening','amount_sum':1000},now=self.now,policy=self.policy)[0]
        self.s=apply_command(self.s,{'action':'reserve_load','post_no':1,'assignment_id':'old','visit_id':'v'},now=self.now,policy=self.policy)[0]
        before=deepcopy(self.s)
        with self.assertRaises(WalletConflict):self.apply('migrate_device_wallet')
        self.assertEqual(self.s,before)

    def test_device_pause_limits_can_be_configured_without_renewing_visit(self):
        self.policy=WalletPolicy(free_pause_millis=10000,dry_fog_pause_millis=120000)
        self.credit();self.load();self.bound('consume_pause',elapsed_millis=9000);self.save()
        self.policy=WalletPolicy(free_pause_millis=60000,dry_fog_pause_millis=300000)
        r=self.load();self.assertEqual(r['pause_millis'],1000);self.save()
        self.kind='dry_fog';r=self.load();self.assertEqual(r['pause_millis'],120000)

    def test_local_primary_capability_check_does_not_rpc_into_its_own_lock(self):
        from unittest.mock import patch
        from app.wallet_client import require_device_wallet_support
        cfg={'local_post':1,'primary_post':1,'standby_post':7,'generation':4,'single_node':False}
        def proof(cfg,post,*args):
            self.assertEqual(post,7)
            return {'device_wallet_protocol':2,'local_post':post,'primary_post':1,'generation':4}
        with patch('app.wallet_api.rpc',side_effect=proof) as rpc:
            require_device_wallet_support(cfg,local_capability=True)
            self.assertEqual(rpc.call_count,1)

    def test_late_wallet_credit_from_wash_does_not_change_active_fog_pause(self):
        self.credit();self.kind='dry_fog';self.load();self.bound('consume_pause',elapsed_millis=12345)
        before=deepcopy(self.s.device_wallet['pause_by_type'])
        self.kind='wash';self.apply('wallet_credit',source='click',receipt_id='late-wash',amount_sum=10000,bonus_sum=1000,bonus_domain='wash')
        self.assertEqual(self.s.device_wallet['pause_by_type'],before)
        self.assertEqual(self.s.device_wallet['assignment_type'],'dry_fog')
        self.assertEqual(self.s.wallet_bonus_sum,6000)
