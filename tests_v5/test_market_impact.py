import unittest

from src.market_impact_engine import MarketImpactEngine
from tests_v5.helpers import strong_event, weak_event


class MarketImpactTests(unittest.TestCase):
    def test_strong_event_has_high_impact(self):
        result = MarketImpactEngine().evaluate(strong_event())
        self.assertGreaterEqual(result.impact_score, 80)
        self.assertEqual(result.impact_direction, "POSITIVE")

    def test_ordinary_product_update_low_impact(self):
        result = MarketImpactEngine().evaluate(weak_event())
        self.assertLess(result.impact_score, 30)


if __name__ == "__main__":
    unittest.main()

