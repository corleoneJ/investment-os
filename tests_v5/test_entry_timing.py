import unittest

from src.entry_timing import EntryTimingEngine
from src.market_impact_engine import MarketImpactEngine
from src.price_reaction import PriceReactionAnalyzer
from src.risk_reward import RiskRewardEngine
from tests_v5.helpers import context, flow, market, valuation


class EntryTimingTests(unittest.TestCase):
    def evaluate(self, ctx):
        impact = MarketImpactEngine().evaluate(ctx.event)
        reaction = PriceReactionAnalyzer().evaluate(ctx.market)
        rr = RiskRewardEngine().plan(ctx.market, ctx.valuation)
        return EntryTimingEngine().evaluate(
            impact, reaction, ctx.market, ctx.flow, ctx.valuation, rr
        )

    def test_strong_event_but_overheated_cannot_buy(self):
        ctx = context(
            market=market(post_1d_change_pct=18, post_5d_change_pct=28, rsi=82, vwap_deviation_pct=9)
        )
        decision = self.evaluate(ctx)
        self.assertNotEqual(decision.status, "BUY")
        self.assertEqual(decision.entry_model, "DO_NOT_CHASE")

    def test_no_fund_confirmation_cannot_buy(self):
        ctx = context(flow=flow(money_flow_confirmed=False))
        decision = self.evaluate(ctx)
        self.assertNotEqual(decision.status, "BUY")
        self.assertIn("资金未确认", decision.reasons)

    def test_pullback_confirmation_can_buy(self):
        decision = self.evaluate(context())
        self.assertEqual(decision.status, "READY")
        self.assertEqual(decision.entry_model, "ENTRY_CONFIRMED")

    def test_wait_for_pullback_is_not_buy(self):
        ctx = context(market=market(pullback_confirmed=False, broke_resistance=False))
        decision = self.evaluate(ctx)
        self.assertNotEqual(decision.status, "BUY")
        self.assertEqual(decision.entry_model, "WAIT_FOR_PULLBACK")

    def test_default_unknown_value_is_wait(self):
        ctx = context(valuation=valuation(opportunity_score=45, risk_score=55))
        decision = self.evaluate(ctx)
        self.assertEqual(decision.status, "WAIT")


if __name__ == "__main__":
    unittest.main()
