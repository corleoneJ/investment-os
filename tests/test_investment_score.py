import unittest

from src.investment_score import V4_ACTIONS, InvestmentScoreCalculator, decision_matrix


class InvestmentScoreTests(unittest.TestCase):
    def test_weights_must_sum_to_100(self):
        with self.assertRaises(ValueError):
            InvestmentScoreCalculator({"event_catalyst": 99})

    def test_high_opportunity_high_risk_never_buys(self):
        action, text = decision_matrix("NVDA", 92, 88, 90, 80)
        self.assertEqual(action, "不追高")
        self.assertIn("高机会、高风险", text)

    def test_low_quality_has_no_directional_conclusion(self):
        action, text = decision_matrix("QQQ", 90, 10, 20, 90)
        self.assertEqual(action, "暂缓新增")
        self.assertIn("不给方向性结论", text)
        self.assertIn(action, V4_ACTIONS)


if __name__ == "__main__":
    unittest.main()
