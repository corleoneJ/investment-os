from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .alert_manager import AlertManager
from .daily_summary import build_daily_summary
from .decision_engine import DecisionEngine, DecisionReport
from .feishu import FeishuClient
from .industry_analyzer import IndustryAnalyzer
from .llm_adapter import build_llm_adapter
from .market_data import MarketSnapshot
from .scanner import Scanner, ScanResult
from .scoring import Scores, calculate_scores
from .state import StateStore

LOGGER = logging.getLogger("investment_os")
UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Investment OS V3 AI投资决策系统")
    parser.add_argument("--mode", choices=("realtime", "daily"), default="realtime")
    parser.add_argument("--state", default=str(ROOT / "state" / "alerts.json"))
    parser.add_argument("--dry-run", action="store_true", help="只分析并生成消息，不发送")
    parser.add_argument("--test-message", action="store_true", help="发送一条飞书连通性测试消息")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def analyze(assets: list[dict]) -> tuple[ScanResult, dict[str, Scores], DecisionReport]:
    scan_result = Scanner().scan(assets)
    scores = {
        symbol: calculate_scores(
            snapshot,
            [item for item in scan_result.news if symbol in item.assets],
        )
        for symbol, snapshot in scan_result.snapshots.items()
        if symbol != "DX-Y.NYB"
    }
    industry = IndustryAnalyzer(load_json(ROOT / "config" / "industry_map.json"))
    llm = build_llm_adapter(ROOT / "config" / "llm_providers.json")
    report = DecisionEngine(industry, llm).decide(
        scan_result.snapshots,
        scan_result.news,
        scan_result.future_events,
        scores,
    )
    return scan_result, scores, report


def run_realtime(
    assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    scan_result, _, report = analyze(assets)
    _log_data_quality(assets, scan_result.snapshots)
    sent, failed = AlertManager(feishu, state).deliver(
        report, scan_result.snapshots, dry_run=dry_run
    )
    _log_decision_center(report)
    return sent, failed


def run_daily(
    assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    scan_result, _, report = analyze(assets)
    visible = {
        key: value
        for key, value in scan_result.snapshots.items()
        if key != "DX-Y.NYB"
    }
    message = build_daily_summary(
        report,
        visible,
        state.data.get("history", []),
        datetime.now(UTC),
    )
    if dry_run:
        LOGGER.info("演练模式：已生成 V3 每日决策汇总，未发送。")
        return 1, 0
    sent = feishu.send(message)
    state.save()
    return (1 if sent else 0), (0 if sent else 1)


def _log_data_quality(assets: list[dict], snapshots: dict[str, MarketSnapshot]) -> None:
    for asset in assets:
        symbol = asset["symbol"]
        snapshot = snapshots[symbol]
        if snapshot.error:
            LOGGER.warning("%s 行情数据暂不可用；决策已降低可信度。", symbol)
        elif not snapshot.fresh:
            LOGGER.info("%s 行情数据时间较旧；不把旧数据描述为实时事实。", symbol)


def _log_decision_center(report: DecisionReport) -> None:
    opportunity_text = "、".join(
        f"{item.asset}({item.score})" for item in report.opportunities[:5]
    )
    risk_text = "、".join(f"{item.asset}({item.score})" for item in report.risks[:5])
    LOGGER.info("决策中心机会TOP5：%s", opportunity_text or "数据暂不可用")
    LOGGER.info("决策中心风险TOP5：%s", risk_text or "数据暂不可用")
    LOGGER.info("未来7天已确认事件数量：%d", len(report.future_events))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s｜%(levelname)s｜%(message)s")
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    args = parse_args()
    started = datetime.now(UTC)
    assets = load_json(ROOT / "config" / "watchlist.json")["assets"]
    state = StateStore(args.state)
    state.load()
    feishu = FeishuClient()

    if args.test_message:
        if args.dry_run:
            LOGGER.info("演练模式：跳过飞书连通性测试消息。")
        else:
            feishu.send(
                "【Investment OS V3 连通性测试】\n"
                "飞书 Webhook 配置有效。本消息不是投资决策，也不构成收益保证。"
            )

    try:
        if args.mode == "daily":
            sent, failed = run_daily(assets, state, feishu, args.dry_run)
        else:
            sent, failed = run_realtime(assets, state, feishu, args.dry_run)
    except Exception:
        LOGGER.exception("本次V3分析出现未处理错误（敏感响应内容不会记录）。")
        return 1
    LOGGER.info("扫描时间：%s", started.isoformat())
    LOGGER.info("扫描资产数量：%d", len(assets))
    LOGGER.info("生成并发送消息数量：%d", sent)
    LOGGER.info("发送失败或因未配置跳过数量：%d", failed)
    LOGGER.info("V3观察模式：频率限制=关闭，评分发送门槛=关闭。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
