import unittest

from app.connectivity import GatewayConnectivity


class GatewayConnectivityTests(unittest.TestCase):
    def test_initial_result_is_available_immediately(self):
        state = GatewayConnectivity()

        self.assertIsNone(state.observe(gateway_url="https://gateway.test", success=True, latency_ms=18))
        self.assertTrue(state.snapshot()["internetOnline"])
        self.assertEqual(state.snapshot()["internetLatencyMs"], 18)

    def test_transitions_are_debounced(self):
        state = GatewayConnectivity(offline_threshold=3, online_threshold=2)
        state.observe(gateway_url="https://gateway.test", success=True)

        self.assertIsNone(state.observe(gateway_url="https://gateway.test", success=False))
        self.assertIsNone(state.observe(gateway_url="https://gateway.test", success=False))
        self.assertEqual(
            state.observe(gateway_url="https://gateway.test", success=False),
            (True, False),
        )
        self.assertIsNone(state.observe(gateway_url="https://gateway.test", success=True))
        self.assertEqual(
            state.observe(gateway_url="https://gateway.test", success=True),
            (False, True),
        )

    def test_gateway_change_resets_previous_result(self):
        state = GatewayConnectivity()
        state.observe(gateway_url="https://first.test", success=True)

        self.assertIsNone(state.observe(gateway_url="https://second.test", success=False))
        self.assertFalse(state.snapshot()["internetOnline"])


if __name__ == "__main__":
    unittest.main()
