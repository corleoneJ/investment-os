import unittest
from datetime import datetime, timezone

from src.industry_graph import IndustryGraph
from src.news import NewsItem


class IndustryGraphTests(unittest.TestCase):
    def test_event_maps_to_configured_chain(self):
        graph = IndustryGraph({"events": {"AI": {"keywords": ["capex"], "industry": "AI", "beneficiaries": {"GPU": {"weight": 0.9, "symbols": ["NVDA"], "lag_days": [0, 3]}}}}})
        news = NewsItem("capex increases", "公告", datetime.now(timezone.utc), "u", (), "财报", True, False)
        impact = graph.match(news)[0]
        self.assertEqual(impact.path[-1], "NVDA")
        self.assertEqual(impact.weight, 0.9)


if __name__ == "__main__":
    unittest.main()
