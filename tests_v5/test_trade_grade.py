import unittest

from src.entry_timing import EntryTimingEngine
from src.market_impact_engine import MarketImpactEngine
from src.price_reaction import PriceReactionAnalyzer
from src.risk_reward import RiskRewardEngine
from src.trade_grade import TradeGradeEngine
from tests_v5.helpers import context, valuation


class TradeGradeTests(unittest.TestCase):
    def test_s_grade_requires_strong_confirmations(self):
        ctx = context(valuation=valuation(opportunity_score=86, risk_score=42, target_upside_pct=30))
        impact = MarketImpactEngine().evaluate(ctx.event)
        reaction = PriceReactionAnalyzer().evaluate(ctx.market)
        rr = RiskRewardEngine().plan(ctx.market, ctx.valuation)
        entry = EntryTimingEngine().evaluate(impact, reaction, ctx.market, ctx.flow, ctx.valuation, rr)
        grade = TradeGradeEngine().evaluate(impact, entry, rr, ctx.flow, ctx.data_quality)
        self.assertEqual(grade.grade, "S")

    def test_b_grade_is_not_alert_pool(self):
        ctx = context(valuation=valuation(opportunity_score=45, risk_score=50))
        impact = MarketImpactEngine().evaluate(ctx.event)
        reaction = PriceReactionAnalyzer().evaluate(ctx.market)
        rr = RiskRewardEngine().plan(ctx.market, ctx.valuation)
        entry = EntryTimingEngine().evaluate(impact, reaction, ctx.market, ctx.flow, ctx.valuation, rr)
        grade = TradeGradeEngine().evaluate(impact, entry, rr, ctx.flow, ctx.data_quality)
        self.assertIn(grade.grade, ("A", "B"))
        if grade.grade == "B":
            self.assertFalse(grade.should_enter_alert_pool)


if __name__ == "__main__":
    unittest.main()

