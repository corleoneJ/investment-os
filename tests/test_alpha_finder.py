import unittest
from datetime import datetime, timezone

from src.alpha_finder import AlphaFinder
from src.industry_graph import IndustryGraph
from src.news import NewsItem
from tests.v4_helpers import flow, snapshot, valuation


class AlphaFinderTests(unittest.TestCase):
    def test_laggard_is_distinguished_from_weak_stock(self):
        graph = IndustryGraph({"events": {"AI": {"keywords": ["capex"], "industry": "AI服务器", "hypothesis": "分析假设", "beneficiaries": {"GPU": {"weight": 1, "symbols": ["NVDA", "WEAK"], "lag_days": [0, 5]}}}}})
        news = [NewsItem("AI capex raised", "公司公告", datetime.now(timezone.utc), "https://example.test/event", ("NVDA",), "财报", True, False)]
        snapshots = {"NVDA": snapshot("NVDA", 1), "WEAK": snapshot("WEAK", -6, weak=True)}
        flows = {"NVDA": flow("NVDA"), "WEAK": flow("WEAK", 20, "资金流出")}
        valuations = {"NVDA": valuation("NVDA"), "WEAK": valuation("WEAK", growth=-10)}
        results = {item.symbol: item for item in AlphaFinder(graph).find(news, snapshots, flows, valuations, [])}
        self.assertNotEqual(results["NVDA"].action, "排除候选")
        self.assertEqual(results["WEAK"].action, "排除候选")
        self.assertLessEqual(results["WEAK"].alpha_score, 35)


if __name__ == "__main__":
    unittest.main()
