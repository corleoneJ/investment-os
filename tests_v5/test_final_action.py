import unittest

from src.trade_filter_layer import TradeFilterLayer
from tests_v5.helpers import NOW, context, market, valuation, weak_event


class FinalActionConsistencyTests(unittest.TestCase):
    def evaluate(self, ctx):
        return TradeFilterLayer().evaluate(ctx, NOW)

    def test_wait_for_pullback_plus_buy_is_invalid(self):
        result = self.evaluate(
            context(
                market=market(pullback_confirmed=False, broke_resistance=False),
                valuation=valuation(opportunity_score=86, risk_score=42),
            )
        )
        self.assertEqual(result.grade.grade, "S")
        self.assertEqual(result.entry.entry_model, "WAIT_FOR_PULLBACK")
        self.assertEqual(result.final_action.final_action, "WAIT")
        self.assertNotEqual(result.final_action.final_action, "BUY")

    def test_do_not_chase_plus_buy_is_invalid(self):
        result = self.evaluate(
            context(
                market=market(
                    post_1d_change_pct=18,
                    post_5d_change_pct=28,
                    rsi=82,
                    vwap_deviation_pct=9,
                ),
                valuation=valuation(opportunity_score=86, risk_score=42),
            )
        )
        self.assertEqual(result.grade.grade, "S")
        self.assertEqual(result.entry.entry_model, "DO_NOT_CHASE")
        self.assertEqual(result.final_action.final_action, "WAIT")
        self.assertNotEqual(result.final_action.final_action, "BUY")

    def test_entry_confirmed_plus_buy_is_allowed(self):
        result = self.evaluate(
            context(
                market=market(pullback_confirmed=True),
                valuation=valuation(opportunity_score=86, risk_score=42),
            )
        )
        self.assertEqual(result.entry.entry_model, "ENTRY_CONFIRMED")
        self.assertEqual(result.final_action.final_action, "BUY")

    def test_buy_but_rr_below_two_is_not_allowed(self):
        result = self.evaluate(
            context(
                market=market(pullback_confirmed=True, resistance=104.0, recent_high=104.0),
                valuation=valuation(opportunity_score=86, risk_score=42, target_upside_pct=6.0),
            )
        )
        self.assertNotEqual(result.final_action.final_action, "BUY")
        self.assertFalse(result.should_send_feishu)

    def test_buy_but_low_data_quality_is_not_allowed(self):
        result = self.evaluate(
            context(
                market=market(pullback_confirmed=True),
                valuation=valuation(opportunity_score=86, risk_score=42),
                data_quality="LOW",
            )
        )
        self.assertEqual(result.entry.entry_model, "ENTRY_CONFIRMED")
        self.assertNotEqual(result.final_action.final_action, "BUY")
        self.assertFalse(result.should_send_feishu)

    def test_no_trade_value_plus_buy_is_invalid(self):
        result = self.evaluate(context(event=weak_event()))
        self.assertEqual(result.entry.entry_model, "NO_TRADE_VALUE")
        self.assertEqual(result.final_action.final_action, "AVOID")
        self.assertNotEqual(result.final_action.final_action, "BUY")


if __name__ == "__main__":
    unittest.main()
