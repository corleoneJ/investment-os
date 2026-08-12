import unittest

from src.early_opportunity import EarlyOpportunityDetector
from src.trade_filter_layer import TradeFilterLayer
from tests_v5.helpers import NOW, sndk_early_context


class EarlyOpportunityTests(unittest.TestCase):
    def test_early_alpha_logic(self):
        result = EarlyOpportunityDetector().evaluate(sndk_early_context())
        self.assertEqual(result.signal, "EARLY_ALPHA")
        self.assertGreaterEqual(result.early_event_score, 70)

    def test_sndk_simulated_case_enters_a_pool(self):
        result = TradeFilterLayer().evaluate(sndk_early_context(), NOW)
        self.assertEqual(result.early.signal, "EARLY_ALPHA")
        self.assertEqual(result.grade.grade, "A")
        self.assertEqual(result.entry.status, "WATCH")
        self.assertTrue(result.should_send_feishu)


if __name__ == "__main__":
    unittest.main()

