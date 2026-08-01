import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.event_pipeline import EventScanManager, news_event_id
from src.main import REALTIME_DEFAULTS, load_realtime_assets
from src.news import NewsItem
from src.state import StateStore, stable_event_id

ROOT = Path(__file__).resolve().parents[1]


class FakeFeishu:
    configured = True

    def send(self, message):
        return True


class FrequencySplitTests(unittest.TestCase):
    def test_realtime_assets_include_required_and_marked_assets(self):
        assets = [
            {"symbol": symbol, "type": "stock"}
            for symbol in sorted(REALTIME_DEFAULTS)
        ]
        assets.append({"symbol": "GOOG", "type": "stock", "high_priority": True})
        selected = {item["symbol"] for item in load_realtime_assets(assets)}
        self.assertTrue(REALTIME_DEFAULTS <= selected)
        self.assertIn("GOOG", selected)

    def test_same_event_is_supplemented_not_recreated(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory) / "state.json")
            event_id = stable_event_id("news", "https://example.test/event")
            now = datetime.now(timezone.utc)
            first = state.upsert_event(
                event_id=event_id, kind="news", title="事件", source="官方",
                source_url="https://example.test/event", event_time=now,
                assets=("NVDA",), category="财报", workflow="news",
            )
            state.mark_events_notified([event_id], now)
            second = state.upsert_event(
                event_id=event_id, kind="news", title="事件补充", source="官方",
                source_url="https://example.test/event", event_time=now,
                assets=("AVGO",), category="财报", workflow="earnings-sec",
            )
            self.assertEqual(first["event_id"], second["event_id"])
            self.assertEqual(len(state.data["events"]), 1)
            self.assertTrue(second["notified"])
            self.assertEqual(second["workflows"], ["earnings-sec", "news"])
            self.assertEqual(second["assets"], ["AVGO", "NVDA"])

    def test_same_semantic_news_from_two_sources_has_one_event_id(self):
        now = datetime.now(timezone.utc)
        first = NewsItem(
            "NVDA earnings exceed expectations", "SEC", now,
            "https://sec.example/filing", ("NVDA",), "财报", True, False,
        )
        second = NewsItem(
            "NVDA reports quarterly results", "Reuters", now,
            "https://media.example/story", ("NVDA",), "财报", True, False,
        )
        self.assertEqual(news_event_id(first), news_event_id(second))

    def test_sent_event_is_not_pushed_by_another_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory) / "state.json")
            item = NewsItem(
                "NVDA earnings exceed expectations", "官方", datetime.now(timezone.utc),
                "https://example.test/earnings", ("NVDA",), "财报", True, False,
            )
            manager = EventScanManager(ROOT, FakeFeishu(), state)
            first = manager.deliver("news", "新闻", [item], [])
            second = manager.deliver("earnings-sec", "财报", [item], [])
            self.assertEqual(first[:2], (1, 0))
            self.assertEqual(second, (0, 0, 1))

    def test_workflow_crons_and_manual_backtest(self):
        expected = {
            "realtime-monitor.yml": 'cron: "*/5 * * * *"',
            "news-event-scan.yml": 'cron: "*/10 * * * *"',
            "earnings-sec-scan.yml": 'cron: "*/30 * * * *"',
            "macro-scan.yml": 'cron: "0 * * * *"',
            "daily-summary.yml": 'cron: "5 12 * * *"',
        }
        workflow_dir = ROOT / ".github" / "workflows"
        for filename, cron in expected.items():
            text = (workflow_dir / filename).read_text(encoding="utf-8")
            self.assertIn("workflow_dispatch:", text)
            self.assertIn(cron, text)
            self.assertIn("concurrency:", text)
        backtest = (workflow_dir / "backtest.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", backtest)
        self.assertNotIn("schedule:", backtest)
        config_test = (workflow_dir / "config-test.yml").read_text(encoding="utf-8")
        self.assertIn("push:", config_test)
        self.assertIn("pull_request:", config_test)


if __name__ == "__main__":
    unittest.main()
