import unittest
from datetime import UTC, datetime, timedelta
from app.wallet_domain import WalletConflict, WalletPolicy, WalletState, apply_command


class WalletDomainTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 12, tzinfo=UTC)
        self.policy = WalletPolicy()
        self.state = WalletState('7C212602')

    def apply(self, action, **kwargs):
        self.state, result = apply_command(self.state, {"action":action, **kwargs}, now=self.now, policy=self.policy)
        return result

    def opening(self, amount=35000):
        self.apply('import_opening', amount_sum=amount)

    def load(self, post=2, assignment='a', visit='v'):
        result = self.apply('reserve_load',post_no=post,assignment_id=assignment,visit_id=visit)
        self.apply('accept_load',post_no=post,assignment_id=assignment)
        return result

    def post(self, action, **kwargs):
        a=self.state.assignment
        return self.apply(action, post_no=a['post_no'],assignment_id=a['id'],**kwargs)

    def save(self):
        self.post('prepare_return')
        return self.post('complete_return')

    def test_post_two_to_seven_next_day_keeps_35000(self):
        self.opening();self.load();self.save()
        self.now += timedelta(days=1)
        self.load(7,'b','next-day')
        self.assertEqual(self.state.assignment['balance_sum'],35000)
        self.assertEqual(self.state.wallet_sum,0)
        self.assertEqual(self.state.visit['pause_millis'],60000)
        self.assertEqual(self.state.external_income_sum,0)

    def test_repeat_taps_and_post_changes_do_not_renew_pause(self):
        self.opening();self.load()
        self.post('consume_pause',elapsed_millis=50000);self.save()
        for i in range(5):
            self.now += timedelta(minutes=1)
            self.load(7,'a'+str(i),'ignored-new-visit'+str(i))
            self.assertEqual(self.state.visit['id'],'v')
            self.assertEqual(self.state.visit['pause_millis'],10000)
            self.save()

    def test_exact_timeout_and_owner_policy_snapshot(self):
        self.policy=WalletPolicy(visit_timeout_minutes=45)
        self.opening();self.load();self.post('consume_pause',elapsed_millis=60000)
        self.policy=WalletPolicy(visit_timeout_minutes=1)
        self.save();self.now+=timedelta(minutes=44,seconds=59)
        self.load(7,'b','not-new');self.assertEqual(self.state.visit['pause_millis'],0)
        self.save();self.now+=timedelta(minutes=45)
        self.load(2,'c','new');self.assertEqual(self.state.visit['pause_millis'],60000)
        self.assertEqual(self.state.visit['timeout_minutes'],1)

    def test_no_heartbeat_timeout_releases_funded_card(self):
        self.opening();self.load();self.now+=timedelta(days=5)
        with self.assertRaises(WalletConflict):self.apply('reserve_load',post_no=7,assignment_id='b',visit_id='b')
        self.assertEqual(self.state.assignment['post_no'],2)

    def test_reserved_and_returning_balances_cannot_be_spent(self):
        self.opening();self.apply('reserve_load',post_no=2,assignment_id='a',visit_id='v')
        with self.assertRaises(WalletConflict):self.post('spend',amount_sum=1)
        self.post('accept_load');self.post('prepare_return')
        with self.assertRaises(WalletConflict):self.post('spend',amount_sum=1)
        with self.assertRaises(WalletConflict):self.post('post_credit',amount_sum=1,source='cash')

    def test_cash_card_click_sum_and_no_duplicate_income(self):
        self.opening();self.load()
        self.post('post_credit',amount_sum=10000,source='cash')
        self.post('register_payment',intent_id='click:123',amount_sum=20000)
        self.apply('confirm_payment',intent_id='click:123',amount_sum=20000)
        self.apply('confirm_payment',intent_id='click:123',amount_sum=20000)
        self.assertEqual(self.state.assignment['balance_sum'],65000)
        self.post('spend',amount_sum=12000);self.save()
        self.assertEqual(self.state.wallet_sum,53000)
        self.assertEqual(self.state.external_income_sum,30000)
        self.state.validate()

    def test_late_click_not_added_to_new_assignment(self):
        self.opening();self.load();self.post('register_payment',intent_id='click:123',amount_sum=20000)
        self.save();self.load(7,'b','same-visit')
        result=self.apply('confirm_payment',intent_id='click:123',amount_sum=20000)
        self.assertEqual(result['destination'],'wallet')
        self.assertEqual(self.state.wallet_sum,20000)
        self.assertEqual(self.state.assignment['balance_sum'],35000)

    def test_click_racing_return_goes_to_wallet(self):
        self.opening();self.load();self.post('register_payment',intent_id='click:123',amount_sum=20000)
        self.post('prepare_return');self.apply('confirm_payment',intent_id='click:123',amount_sum=20000)
        self.post('complete_return');self.assertEqual(self.state.wallet_sum,55000)

    def test_wrong_post_rejected_without_mutation(self):
        self.opening();self.load();original=self.state
        with self.assertRaises(WalletConflict):self.apply('spend',post_no=7,assignment_id='a',amount_sum=1)
        self.assertIs(self.state,original);self.assertEqual(self.state.assignment['balance_sum'],35000)

    def test_exhausted_pause_reports_paid_remainder(self):
        self.opening();self.load();result=self.post('consume_pause',elapsed_millis=65000)
        self.assertEqual(result['consumed_millis'],60000)
        self.assertEqual(result['unpaid_millis'],5000)
        self.assertEqual(self.state.visit['pause_millis'],0)

    def test_invalid_and_negative_inputs_rejected(self):
        for amount in (-1,0,True,1.2):
            with self.assertRaises(WalletConflict):self.apply('import_opening',amount_sum=amount)
        with self.assertRaises(WalletConflict):WalletPolicy(visit_timeout_minutes=0)
        self.opening();self.load()
        with self.assertRaises(WalletConflict):self.post('spend',amount_sum=35001)
        self.assertEqual(self.state.assignment['balance_sum'],35000)

    def test_serialized_restart_retains_consumed_pause_and_bound_payment(self):
        from dataclasses import asdict
        import json
        self.opening();self.load();self.post('consume_pause',elapsed_millis=59000)
        self.post('register_payment',intent_id='click:restart',amount_sum=1000)
        self.state=WalletState(**json.loads(json.dumps(asdict(self.state))))
        self.save();self.load(7,'restarted','same-visit')
        self.assertEqual(self.state.visit['pause_millis'],1000)
        self.apply('confirm_payment',intent_id='click:restart',amount_sum=1000)
        self.assertEqual(self.state.wallet_sum,1000)
        self.assertEqual(self.state.assignment['balance_sum'],35000)

    def test_confirmed_payment_cannot_hide_amount_mismatch(self):
        self.opening();self.load();self.post('register_payment',intent_id='click:one',amount_sum=1)
        self.apply('confirm_payment',intent_id='click:one',amount_sum=1)
        for wrong in (True,2,0):
            with self.assertRaises(WalletConflict):self.apply('confirm_payment',intent_id='click:one',amount_sum=wrong)
        self.assertEqual(self.state.external_income_sum,1)

    def test_unregistered_online_and_unknown_actions_rejected(self):
        with self.assertRaises(WalletConflict):self.apply('confirm_payment',intent_id='unknown',amount_sum=1000)
        with self.assertRaises(WalletConflict):self.apply('release_disconnected_post')


if __name__=='__main__':unittest.main()
