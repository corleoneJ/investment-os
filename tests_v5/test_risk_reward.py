import unittest

from src.entry_timing import EntryTimingEngine
from src.market_impact_engine import MarketImpactEngine
from src.price_reaction import PriceReactionAnalyzer
from src.risk_reward import RiskRewardEngine
from tests_v5.helpers import context, market, valuation


class RiskRewardTests(unittest.TestCase):
    def test_dynamic_stop_uses_structure_not_fixed_percent(self):
        plan = RiskRewardEngine().plan(market(), valuation())
        self.assertIn(plan.stop_type, ("ATR止损", "技术支撑止损", "EMA20失效", "前低失效"))
        self.assertNotEqual(round(plan.stop_percent, 2), -5.0)

    def test_rr_below_threshold_cannot_buy(self):
        ctx = context(
            market=market(resistance=103, support=96, ema20=97, atr=3),
            valuation=valuation(target_upside_pct=5),
        )
        impact = MarketImpactEngine().evaluate(ctx.event)
        reaction = PriceReactionAnalyzer().evaluate(ctx.market)
        plan = RiskRewardEngine().plan(ctx.market, ctx.valuation)
        decision = EntryTimingEngine().evaluate(
            impact, reaction, ctx.market, ctx.flow, ctx.valuation, plan
        )
        self.assertLess(plan.risk_reward_ratio, 2.0)
        self.assertNotEqual(decision.status, "BUY")


if __name__ == "__main__":
    unittest.main()

