import unittest

from src.noise_filter import NoiseFilter
from tests_v5.helpers import NOW, weak_event


class NoiseFilterTests(unittest.TestCase):
    def test_garbage_news_not_pushed(self):
        result = NoiseFilter().evaluate(weak_event(), NOW)
        self.assertTrue(result.is_noise)
        self.assertGreaterEqual(result.noise_score, 70)

    def test_duplicate_news_is_noise(self):
        nf = NoiseFilter()
        event = weak_event().__class__(
            event_id="dup",
            symbol="ABC",
            title="Earnings beat with guidance raise",
            source="Company PR",
            published_at=NOW,
            revenue_impact=20,
            profit_impact=20,
            guidance_impact=20,
        )
        self.assertFalse(nf.evaluate(event, NOW).is_noise)
        self.assertTrue(nf.evaluate(event, NOW).is_noise)


if __name__ == "__main__":
    unittest.main()

