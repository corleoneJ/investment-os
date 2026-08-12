import unittest

from src.trade_filter_layer import TradeFilterLayer
from tests_v5.helpers import NOW, context, weak_event


class FeishuFormatTests(unittest.TestCase):
    def test_s_grade_buy_message_format(self):
        result = TradeFilterLayer().evaluate(context(), NOW)
        self.assertTrue(result.should_send_feishu)
        text = result.feishu_message
        for section in (
            "【Investment OS V5 买入信号】",
            "【核心结论】",
            "【事件】",
            "【资金】",
            "【技术】",
            "【买入计划】",
            "【风险】",
            "【执行建议】",
            "【失效条件】",
        ):
            self.assertIn(section, text)
        self.assertIn("当前动作：BUY", text)
        self.assertIn("允许小额首仓", text)

    def test_wait_for_pullback_message_has_no_buy_language(self):
        result = TradeFilterLayer().evaluate(
            context(market=context().market.__class__(
                **{
                    **context().market.__dict__,
                    "pullback_confirmed": False,
                    "broke_resistance": False,
                }
            )),
            NOW,
        )
        self.assertTrue(result.should_send_feishu)
        self.assertEqual(result.entry.entry_model, "WAIT_FOR_PULLBACK")
        self.assertEqual(result.final_action.final_action, "WAIT")
        self.assertNotIn("BUY", result.feishu_message)
        self.assertNotIn("立即", result.feishu_message)
        self.assertNotIn("允许小额首仓", result.feishu_message)

    def test_noise_has_no_feishu_message(self):
        result = TradeFilterLayer().evaluate(context(event=weak_event()), NOW)
        self.assertTrue(result.noise.is_noise)
        self.assertFalse(result.should_send_feishu)
        self.assertEqual(result.feishu_message, "")


if __name__ == "__main__":
    unittest.main()
