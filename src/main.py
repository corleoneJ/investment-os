from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .alert_manager import AlertManager
from .daily_summary import build_v4_daily_summary
from .event_pipeline import EventScanManager
from .feishu import FeishuClient
from .future_events import FutureEventScanner
from .market_data import MarketDataClient, MarketSnapshot
from .news import NewsClient
from .state import StateStore
from .v4_engine import V4Engine, V4Report

LOGGER = logging.getLogger("investment_os")
UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
REALTIME_DEFAULTS = {"BTC-USD", "SNDK", "NVDA", "MSFT", "META", "QQQ"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Investment OS V4 AI投资决策系统")
    parser.add_argument(
        "--mode",
        choices=("realtime", "news", "earnings", "macro", "daily"),
        default="realtime",
    )
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


def load_realtime_assets(assets: list[dict]) -> list[dict]:
    return [
        asset
        for asset in assets
        if asset["symbol"] in REALTIME_DEFAULTS or asset.get("high_priority") is True
    ]


def analyze_market(
    assets: list[dict], state: StateStore
) -> tuple[dict[str, MarketSnapshot], V4Report]:
    market_assets = [*assets, {"symbol": "DX-Y.NYB", "type": "macro"}]
    snapshots = MarketDataClient().fetch_all(market_assets)
    report = V4Engine(ROOT).build(
        [item["symbol"] for item in assets],
        snapshots,
        state.cached_news(),
        state.cached_future_events(),
    )
    return snapshots, report


def run_realtime(
    assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    snapshots, report = analyze_market(assets, state)
    _log_data_quality(assets, snapshots)
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
    all_assets = list({item["symbol"]: item for item in [*assets, *candidate_assets]}.values())
    snapshots, report = analyze_market(all_assets, state)
    visible = {
        key: value
        for key, value in snapshots.items()
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


def run_news_events(
    assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    news = NewsClient().fetch_company_news(assets)
    sent, failed, _ = EventScanManager(ROOT, feishu, state).deliver(
        "news", "新闻与产业链事件", news, [], dry_run=dry_run
    )
    return sent, failed


def run_earnings_sec(
    assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    news = NewsClient().fetch_earnings_sec(assets)
    future = FutureEventScanner().scan_earnings(assets)
    sent, failed, _ = EventScanManager(ROOT, feishu, state).deliver(
        "earnings-sec", "财报与SEC事件", news, future, dry_run=dry_run
    )
    return sent, failed


def run_macro(
    assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    news = NewsClient().fetch_macro(assets)
    future = FutureEventScanner().scan_macro(assets)
    wanted = [asset for asset in assets if asset["symbol"] in {"BTC-USD", "QQQ"}]
    context_assets = [
        *wanted,
        {"symbol": "DX-Y.NYB", "type": "macro"},
        {"symbol": "^TNX", "type": "macro"},
    ]
    context = MarketDataClient().fetch_all(context_assets)
    sent, failed, _ = EventScanManager(ROOT, feishu, state).deliver(
        "macro", "宏观风险事件", news, future, dry_run=dry_run, market_context=context
    )
    return sent, failed


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
    all_assets = list({item["symbol"]: item for item in [*assets, *candidate_assets]}.values())
    realtime_assets = load_realtime_assets(assets)
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
            scanned_count = len(all_assets)
        elif args.mode == "news":
            sent, failed = run_news_events(all_assets, state, feishu, args.dry_run)
            scanned_count = len(all_assets)
        elif args.mode == "earnings":
            sent, failed = run_earnings_sec(all_assets, state, feishu, args.dry_run)
            scanned_count = len(all_assets)
        elif args.mode == "macro":
            sent, failed = run_macro(assets, state, feishu, args.dry_run)
            scanned_count = 4
        else:
            sent, failed = run_realtime(realtime_assets, state, feishu, args.dry_run)
            scanned_count = len(realtime_assets)
    except Exception:
        LOGGER.exception("本次V4分析出现未处理错误（敏感响应内容不会记录）。")
        return 1
    LOGGER.info("扫描时间：%s", started.isoformat())
    LOGGER.info("运行模式：%s", args.mode)
    LOGGER.info("本模式扫描资产数量：%d", scanned_count)
    LOGGER.info("生成并发送消息数量：%d", sent)
    LOGGER.info("发送失败或因未配置跳过数量：%d", failed)
    LOGGER.info("V4观察模式：频率限制=关闭，评分发送门槛=关闭；同轮同资产消息已合并。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
