from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.main import (
    build_v5_daily_addendum,
    run_daily,
    run_earnings_sec,
    run_macro,
    run_news_events,
    run_realtime,
)
from src.state import StateStore
from src.trade_filter_layer import TradeFilterLayer
from src.v5_dry_run import NOW, scenarios
from src.v5_production import V5ProductionBridge


class FakeFeishu:
    configured = True

    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, message: str) -> bool:
        self.messages.append(message)
        return True


class V5ProductionIntegrationTests(unittest.TestCase):
    def test_realtime_mode_calls_v5_trade_filter_layer(self):
        rankings = SimpleNamespace(comprehensive=(), risk=())
        report = SimpleNamespace(decisions=(), rankings=rankings, alpha_candidates=(), future_events=())
        with patch("src.main.analyze_market", return_value=({}, report)), patch(
            "src.main.V5ProductionBridge"
        ) as bridge_cls:
            bridge = bridge_cls.return_value
            bridge.deliver_report.return_value = (1, 0)
            sent, failed = run_realtime([], Mock(), Mock(), dry_run=True)
        self.assertEqual((sent, failed), (1, 0))
        bridge.deliver_report.assert_called_once_with(report, dry_run=True)

    def test_news_mode_goes_through_v5_noise_filter_bridge(self):
        with patch("src.main.NewsClient") as news_cls, patch(
            "src.main.MarketDataClient"
        ) as market_cls, patch("src.main.V5ProductionBridge") as bridge_cls:
            news_cls.return_value.fetch_company_news.return_value = []
            market_cls.return_value.fetch_all.return_value = {}
            bridge_cls.return_value.deliver_news_items.return_value = (0, 0, 0)
            sent, failed = run_news_events([], Mock(), Mock(), dry_run=True)
        self.assertEqual((sent, failed), (0, 0))
        bridge_cls.return_value.deliver_news_items.assert_called_once()

    def test_earnings_mode_goes_through_v5_impact_bridge(self):
        with patch("src.main.NewsClient") as news_cls, patch(
            "src.main.FutureEventScanner"
        ) as future_cls, patch("src.main.MarketDataClient") as market_cls, patch(
            "src.main.V5ProductionBridge"
        ) as bridge_cls:
            news_cls.return_value.fetch_earnings_sec.return_value = []
            future_cls.return_value.scan_earnings.return_value = []
            market_cls.return_value.fetch_all.return_value = {}
            bridge_cls.return_value.deliver_news_items.return_value = (0, 0, 0)
            sent, failed = run_earnings_sec([], Mock(), Mock(), dry_run=True)
        self.assertEqual((sent, failed), (0, 0))
        bridge_cls.return_value.deliver_news_items.assert_called_once()

    def test_macro_mode_goes_through_v5_risk_filter_bridge(self):
        with patch("src.main.NewsClient") as news_cls, patch(
            "src.main.FutureEventScanner"
        ) as future_cls, patch("src.main.MarketDataClient") as market_cls, patch(
            "src.main.V5ProductionBridge"
        ) as bridge_cls:
            news_cls.return_value.fetch_macro.return_value = []
            future_cls.return_value.scan_macro.return_value = []
            market_cls.return_value.fetch_all.return_value = {}
            bridge_cls.return_value.deliver_news_items.return_value = (0, 0, 0)
            sent, failed = run_macro([], Mock(), Mock(), dry_run=True)
        self.assertEqual((sent, failed), (0, 0))
        bridge_cls.return_value.deliver_news_items.assert_called_once()

    def test_daily_mode_keeps_summary_and_adds_v5_filter_layer(self):
        report = SimpleNamespace(decisions=(), generated_at=datetime.now())
        with patch("src.main.analyze_market", return_value=({}, report)):
            sent, failed = run_daily([], [], Mock(), Mock(), dry_run=True)
        self.assertEqual((sent, failed), (0, 0))
        addendum = build_v5_daily_addendum(report, Mock())
        self.assertEqual("", addendum)

    def test_final_action_matrix_is_enforced_in_production_chain(self):
        layer = TradeFilterLayer()
        expected = {
            "garbage_news": ("NO_TRADE_VALUE", "AVOID", False),
            "s_wait_pullback": ("WAIT_FOR_PULLBACK", "WAIT", False),
            "s_entry_confirmed": ("ENTRY_CONFIRMED", "BUY", True),
            "s_do_not_chase": ("DO_NOT_CHASE", "WAIT", False),
            "a_wait_pullback": ("WAIT_FOR_PULLBACK", "WATCH", False),
            "a_entry_confirmed": ("ENTRY_CONFIRMED", "BUY", True),
        }
        for name, (entry_model, final_action, send) in expected.items():
            with self.subTest(name=name):
                result = layer.evaluate(scenarios()[name], NOW)
                self.assertEqual(result.entry.entry_model, entry_model)
                self.assertEqual(result.final_action.final_action, final_action)
                self.assertEqual(result.should_send_feishu, send)

    def test_wait_is_not_pushed_and_buy_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = StateStore(f"{tmpdir}/alerts.json")
            feishu = FakeFeishu()
            bridge = V5ProductionBridge(state, feishu)
            wait_result = bridge.layer.evaluate(scenarios()["s_wait_pullback"], NOW)
            buy_result = bridge.layer.evaluate(scenarios()["s_entry_confirmed"], NOW)

            self.assertFalse(bridge._deliver_result(wait_result, NOW, dry_run=False))
            self.assertTrue(bridge._deliver_result(buy_result, NOW, dry_run=False))
            self.assertFalse(bridge._deliver_result(buy_result, NOW, dry_run=False))
            self.assertEqual(len(feishu.messages), 1)

    def test_feishu_formatter_reads_final_action(self):
        result = TradeFilterLayer().evaluate(scenarios()["s_wait_pullback"], NOW)
        self.assertEqual(result.final_action.final_action, "WAIT")
        self.assertFalse(result.should_send_feishu)
        self.assertEqual("", result.feishu_message)


if __name__ == "__main__":
    unittest.main()
