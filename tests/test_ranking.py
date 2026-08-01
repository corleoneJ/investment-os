import unittest

from src.investment_score import InvestmentScoreResult
from src.ranking import RankingEngine
from tests.v4_helpers import flow, valuation


def score(symbol):
    return InvestmentScoreResult(symbol, 60, 30, 70, 80, 80, (), "继续持有", "测试")


class RankingTests(unittest.TestCase):
    def test_equal_scores_are_sorted_by_symbol(self):
        scores = {symbol: score(symbol) for symbol in ("NVDA", "AVGO")}
        report = RankingEngine().build(scores, [], {s: flow(s) for s in scores}, {s: valuation(s) for s in scores})
        self.assertEqual([item.symbol for item in report.comprehensive], ["AVGO", "NVDA"])


if __name__ == "__main__":
    unittest.main()
