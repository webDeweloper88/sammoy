import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from contextlib import contextmanager
from app.local_card_pause import KEY, save, restore, consume
from app.wash_logic import WashRuntime

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)

class VisitTests(unittest.TestCase):
    def test_repeated_transfers_never_refill_fractional_allowance(self):
        metadata = {'name': 'kept'}
        for _ in range(5):
            metadata = save(metadata, 'wash', 24.25, 60, now=NOW)
            self.assertEqual(restore(metadata, 'wash', 60, NOW), 24.25)
            metadata = consume(metadata, 'wash')
        self.assertEqual(metadata, {'name': 'kept'})

    def test_zero_stays_zero_until_exact_expiry(self):
        m=save({}, 'wash', 0, 60, now=NOW)
        self.assertEqual(restore(m,'wash',60,NOW+timedelta(minutes=29,seconds=59)),0)
        self.assertEqual(restore(m,'wash',60,NOW+timedelta(minutes=30)),60)

    def test_lower_limit_and_combined_balance_cannot_increase_allowance(self):
        m=save({},'wash',10,60,now=NOW)
        combined=save(m,'wash',50,60,existing_balance=5000,now=NOW)
        self.assertEqual(restore(combined,'wash',60,NOW),10)
        self.assertEqual(restore(combined,'wash',5,NOW),5)

    def test_expired_visit_new_cash_and_legacy_card(self):
        m=save({},'wash',0,60,now=NOW)
        self.assertEqual(restore(m,'wash',60,NOW+timedelta(minutes=31)),60)
        fresh=save(m,'wash',30,60,existing_balance=0,now=NOW)
        self.assertEqual(restore(fresh,'wash',60,NOW),30)
        self.assertEqual(restore({},'wash',60,NOW),60)

    def test_malformed_and_nonfinite_fail_closed(self):
        for value in [None,{}, {'schema':1,'remaining_seconds':60,'expires_at':'bad'}]:
            self.assertEqual(restore({KEY:{'wash':value}},'wash',60,NOW),0)
        for value in [float('nan'),float('inf'),True,-10]:
            self.assertEqual(restore(save({},'wash',value,60,now=NOW),'wash',60,NOW),0)

    def test_service_budgets_and_other_metadata_remain_separate(self):
        m=save({'other':123},'wash',20,60,now=NOW)
        m=save(m,'dry_fog',120,300,existing_balance=1000,now=NOW)
        used=consume(m,'wash')
        self.assertNotIn('wash',used[KEY])
        self.assertEqual(restore(used,'dry_fog',300,NOW),120)
        self.assertEqual(used['other'],123)

class RuntimeTests(unittest.TestCase):
    def test_load_restores_and_immediately_persists_budget_for_reboot(self):
        runtime=WashRuntime(); runtime._record_credit_locked=Mock();runtime.active_session_id=9
        card={'bonus_sum':0,'metadata':save({},'wash',24.25,60)}
        conn=Mock();conn.execute.return_value.fetchone.side_effect=[card,{'balance_sum':0}]
        @contextmanager
        def database():yield conn
        with patch('app.wash_logic.db',database):
            runtime._use_customer_balance_locked('test-card',10000,{})
        self.assertEqual(runtime.state['_pauseBudgetFloat'],24.25)
        self.assertEqual(runtime.state['freePauseRemaining'],25)
        runtime._ensure_pause_budget_locked()
        self.assertEqual(runtime.state['_pauseBudgetFloat'],24.25)
        writes=[args for args,kw in conn.execute.call_args_list if 'metadata=metadata ||' in args[0]]
        self.assertEqual(writes[0][1][1].obj['free_pause_remaining'],24.25)
        debit=[args for args,kw in conn.execute.call_args_list if 'SET balance_sum = 0' in args[0]][0]
        self.assertNotIn(KEY,debit[1][0].obj)

    def test_save_persists_budget_with_money_and_keeps_bonus(self):
        runtime=WashRuntime();runtime.active_session_id=9
        runtime.state.update(creditSum=10000,_creditFloat=10000,bonusSum=2000,_bonusFloat=2000,
                             _pauseBudgetInitialized=True,_pauseBudgetFloat=24.25,freePauseRemaining=25)
        runtime._flush_usage_locked=Mock();runtime._close_session_locked=Mock()
        conn=Mock();conn.execute.return_value.fetchone.side_effect=[{'metadata':{'name':'kept'},'balance_sum':0},{'balance_sum':10000}]
        @contextmanager
        def database():yield conn
        with patch('app.wash_logic.db',database):runtime._save_remaining_to_customer_card_locked('test-card',{})
        write=[args for args,kw in conn.execute.call_args_list if 'SET balance_sum = balance_sum +' in args[0]][0]
        self.assertEqual(write[1][0:2],(10000,2000))
        self.assertEqual(restore(write[1][2].obj,'wash',60),24.25)
        self.assertEqual(write[1][2].obj['name'],'kept')
        self.assertEqual(runtime.state['creditSum'],0)

if __name__=='__main__':unittest.main()
