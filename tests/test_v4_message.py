import unittest
from datetime import datetime, timezone

from src.alert_manager import AlertManager, format_v4_message
from src.investment_score import V4_ACTIONS, InvestmentScoreResult
from src.ranking import RankingReport
from src.state import StateStore
from src.v4_engine import V4AssetDecision, V4Report
from tests.v4_helpers import flow, snapshot, valuation


class FakeFeishu:
    configured = True
    def send(self, message):
        return True


def decision():
    snap = snapshot()
    score = InvestmentScoreResult("NVDA", 75, 50, 66, 70, 80, (), "等待回踩", "高机会、中风险，等待回踩。")
    return V4AssetDecision("NVDA", snap, score, flow(), valuation(), None, None, None, "同行数据", (), "官方事实暂不可用", "系统推断", "待验证", ("跌破支撑",), ("风险1", "风险2", "风险3"), "审慎总结。")


class V4MessageTests(unittest.TestCase):
    def test_message_contains_all_sections_and_allowed_action(self):
        item = decision()
        message = format_v4_message(item, datetime.now(timezone.utc))
        for section in ("【评分】", "【催化剂】", "【Alpha判断】", "【资金】", "【估值】", "【技术位置】", "【执行建议】"):
            self.assertIn(section, message)
        self.assertIn(item.score.action, V4_ACTIONS)

    def test_same_asset_is_merged_once(self):
        item = decision()
        empty = RankingReport((), (), (), (), (), ())
        report = V4Report((item, item), empty, {"NVDA": item.score}, (), {"NVDA": item.flow}, {"NVDA": item.valuation}, {}, (), datetime.now(timezone.utc))
        sent, failed = AlertManager(FakeFeishu(), StateStore("/tmp/investment-os-v4-test.json")).deliver_v4(report, dry_run=True)
        self.assertEqual((sent, failed), (1, 0))


if __name__ == "__main__":
    unittest.main()
