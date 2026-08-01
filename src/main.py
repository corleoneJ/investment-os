from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .alert_manager import AlertManager
from .daily_summary import build_v4_daily_summary
from .feishu import FeishuClient
from .market_data import MarketSnapshot
from .scanner import Scanner, ScanResult
from .state import StateStore
from .v4_engine import V4Engine, V4Report

LOGGER = logging.getLogger("investment_os")
UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Investment OS V4 AI投资决策系统")
    parser.add_argument("--mode", choices=("realtime", "daily"), default="realtime")
    parser.add_argument("--state", default=str(ROOT / "state" / "alerts.json"))
    parser.add_argument("--dry-run", action="store_true", help="只分析并生成消息，不发送")
    parser.add_argument("--test-message", action="store_true", help="发送一条飞书连通性测试消息")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_assets() -> tuple[list[dict], list[dict]]:
    core = load_json(ROOT / "config" / "watchlist.json")["assets"]
    candidate_config = load_json(ROOT / "config" / "candidate_universe.json")
    maximum = min(50, int(candidate_config.get("max_symbols", 50)))
    candidates = [*candidate_config.get("assets", []), *candidate_config.get("manual_assets", [])]
    return core, candidates[:maximum]


def analyze(
    assets: list[dict], candidate_assets: list[dict]
) -> tuple[ScanResult, V4Report]:
    scan_result = Scanner().scan(assets, candidate_assets)
    report = V4Engine(ROOT).build(
        [item["symbol"] for item in assets],
        scan_result.snapshots,
        scan_result.news,
        scan_result.future_events,
    )
    return scan_result, report


def run_realtime(
    assets: list[dict],
    candidate_assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    scan_result, report = analyze(assets, candidate_assets)
    _log_data_quality([*assets, *candidate_assets], scan_result.snapshots)
    sent, failed = AlertManager(feishu, state).deliver_v4(report, dry_run=dry_run)
    _log_decision_center(report)
    return sent, failed


def run_daily(
    assets: list[dict],
    candidate_assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    scan_result, report = analyze(assets, candidate_assets)
    visible = {
        key: value
        for key, value in scan_result.snapshots.items()
        if key != "DX-Y.NYB"
    }
    message = build_v4_daily_summary(
        report,
        visible,
        state.data.get("history", []),
        datetime.now(UTC),
    )
    if dry_run:
        LOGGER.info("演练模式：已生成 V4 每日决策汇总，未发送。")
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


def _log_decision_center(report: V4Report) -> None:
    opportunity_text = "、".join(
        f"{item.symbol}({item.score})" for item in report.rankings.comprehensive[:5]
    )
    risk_text = "、".join(f"{item.symbol}({item.score})" for item in report.rankings.risk[:5])
    LOGGER.info("决策中心机会TOP5：%s", opportunity_text or "数据暂不可用")
    LOGGER.info("决策中心风险TOP5：%s", risk_text or "数据暂不可用")
    LOGGER.info("Alpha候选数量：%d", len(report.alpha_candidates))
    LOGGER.info("未来7天已确认事件数量：%d", len(report.future_events))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s｜%(levelname)s｜%(message)s")
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    args = parse_args()
    started = datetime.now(UTC)
    assets, candidate_assets = load_assets()
    state = StateStore(args.state)
    state.load()
    feishu = FeishuClient()

    if args.test_message:
        if args.dry_run:
            LOGGER.info("演练模式：跳过飞书连通性测试消息。")
        else:
            feishu.send(
                "【Investment OS V4 连通性测试】\n"
                "飞书 Webhook 配置有效。本消息不是投资决策，也不构成收益保证。"
            )

    try:
        if args.mode == "daily":
            sent, failed = run_daily(assets, candidate_assets, state, feishu, args.dry_run)
        else:
            sent, failed = run_realtime(assets, candidate_assets, state, feishu, args.dry_run)
    except Exception:
        LOGGER.exception("本次V4分析出现未处理错误（敏感响应内容不会记录）。")
        return 1
    LOGGER.info("扫描时间：%s", started.isoformat())
    LOGGER.info("扫描资产数量：%d（核心%d，候选%d）", len(assets) + len(candidate_assets), len(assets), len(candidate_assets))
    LOGGER.info("生成并发送消息数量：%d", sent)
    LOGGER.info("发送失败或因未配置跳过数量：%d", failed)
    LOGGER.info("V4观察模式：频率限制=关闭，评分发送门槛=关闭；同轮同资产消息已合并。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
