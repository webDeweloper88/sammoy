import unittest

from app.reporting import reconcile_session_credit


class ReportReconciliationTests(unittest.TestCase):
    def test_customer_card_save_is_an_accounted_credit_destination(self):
        result = reconcile_session_credit(
            paid_sum=26356,
            spent_sum=18000,
            customer_saved_sum=8356,
            final_credit_sum=0,
        )

        self.assertEqual(result["accounted_credit_sum"], 26356)
        self.assertEqual(result["credit_difference_sum"], 0)

    def test_open_session_credit_is_not_reported_as_a_difference(self):
        result = reconcile_session_credit(
            paid_sum=5000,
            spent_sum=1200,
            customer_saved_sum=0,
            final_credit_sum=3800,
        )

        self.assertEqual(result["credit_difference_sum"], 0)

    def test_unaccounted_credit_remains_visible_for_diagnostics(self):
        result = reconcile_session_credit(
            paid_sum=5000,
            spent_sum=4900,
            customer_saved_sum=0,
            final_credit_sum=0,
        )

        self.assertEqual(result["credit_difference_sum"], 100)


if __name__ == "__main__":
    unittest.main()
