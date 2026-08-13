import unittest
from unittest.mock import patch

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
            "【买入理由】",
            "【触发条件】",
            "【资金确认】",
            "【技术位置】",
            "【基本面 / 催化剂】",
            "【已确认事实】",
            "【系统推断】",
            "【暂无法验证】",
            "【买入计划】",
            "【主要风险】",
            "【失效条件】",
            "【一句总结】",
        ):
            self.assertIn(section, text)
        self.assertIn("允许小额首仓", text)
        self.assertIn("当前价格：", text)
        self.assertIn("买入区间：", text)
        self.assertIn("止损：", text)
        self.assertIn("目标1：", text)
        self.assertIn("目标2：", text)
        self.assertIn("风险收益比：", text)
        reason_lines = [line for line in text.splitlines() if line.startswith(("1. ", "2. ", "3. "))]
        self.assertGreaterEqual(len(reason_lines), 3)

    def test_buy_without_three_structured_reasons_fails(self):
        with patch("src.feishu_signal_formatter._buy_reasons", return_value=["资金确认", "技术确认"]):
            with self.assertRaises(ValueError):
                TradeFilterLayer().evaluate(context(), NOW)

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
        self.assertFalse(result.should_send_feishu)
        self.assertEqual(result.entry.entry_model, "WAIT_FOR_PULLBACK")
        self.assertEqual(result.final_action.final_action, "WAIT")
        self.assertEqual(result.feishu_message, "")
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
