import unittest
from datetime import datetime, timedelta, timezone

from src.data_quality import ProviderState, evaluate_data_quality, provider_status


class DataQualityTests(unittest.TestCase):
    def test_stale_provider_reduces_quality(self):
        stale = provider_status(status=ProviderState.STALE, source="测试", source_url="", data_timestamp=datetime.now(timezone.utc) - timedelta(days=1), confidence=50)
        result = evaluate_data_quality({"价格": 1, "估值": None}, [stale])
        self.assertLess(result.score, 60)
        self.assertIn("STALE", result.warnings[0])


if __name__ == "__main__":
    unittest.main()
