from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .daily_summary import build_v4_daily_summary
from .feishu import FeishuClient
from .future_events import FutureEventScanner
from .market_data import MarketDataClient, MarketSnapshot
from .news import NewsClient
from .state import StateStore
from .v4_engine import V4Engine, V4Report
from .v5_production import V5ProductionBridge

LOGGER = logging.getLogger("investment_os")
UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
REALTIME_DEFAULTS = {"BTC-USD", "SNDK", "NVDA", "MSFT", "META", "QQQ"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Investment OS V5 交易决策过滤系统")
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
    sent, failed = V5ProductionBridge(state, feishu).deliver_report(report, dry_run=dry_run)
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
    message = message + "\n\n" + build_v5_daily_addendum(report, state)
    if dry_run:
        LOGGER.info("演练模式：已生成 V5 每日决策汇总，未发送。")
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
    snapshots = MarketDataClient().fetch_all(assets)
    sent, failed, skipped = V5ProductionBridge(state, feishu).deliver_news_items(
        "news", news, snapshots, dry_run=dry_run
    )
    LOGGER.info("新闻事件V5过滤：发送%d，失败%d，过滤%d。", sent, failed, skipped)
    return sent, failed


def run_earnings_sec(
    assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    news = NewsClient().fetch_earnings_sec(assets)
    future = FutureEventScanner().scan_earnings(assets)
    snapshots = MarketDataClient().fetch_all(assets)
    sent, failed, skipped = V5ProductionBridge(state, feishu).deliver_news_items(
        "earnings-sec", news, snapshots, dry_run=dry_run
    )
    for event in future:
        state.upsert_event(
            event_id=f"future:{event.source}:{event.event_time.isoformat()}:{event.name}",
            kind="future",
            title=event.name,
            source=event.source,
            source_url=event.url,
            event_time=event.event_time,
            assets=event.assets,
            category=event.expected_impact,
            workflow="earnings-sec",
        )
    state.save()
    LOGGER.info("财报/SEC V5过滤：发送%d，失败%d，过滤%d。", sent, failed, skipped)
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
    sent, failed, skipped = V5ProductionBridge(state, feishu).deliver_news_items(
        "macro", news, context, dry_run=dry_run
    )
    for event in future:
        state.upsert_event(
            event_id=f"future:{event.source}:{event.event_time.isoformat()}:{event.name}",
            kind="future",
            title=event.name,
            source=event.source,
            source_url=event.url,
            event_time=event.event_time,
            assets=event.assets,
            category=event.expected_impact,
            workflow="macro",
        )
    state.save()
    LOGGER.info("宏观事件V5风险过滤：发送%d，失败%d，过滤%d。", sent, failed, skipped)
    return sent, failed


def build_v5_daily_addendum(report: V4Report, state: StateStore) -> str:
    bridge = V5ProductionBridge(state, FeishuClient())
    results = [bridge.evaluate_decision(decision, report.generated_at) for decision in report.decisions]
    alertable = [
        result
        for result in results
        if result.grade.grade in {"S", "A"} or result.final_action.final_action in {"BUY", "WAIT", "WATCH", "AVOID"}
    ]
    filtered = [result for result in results if not result.should_send_feishu]
    top = sorted(
        alertable,
        key=lambda item: (
            {"BUY": 5, "WAIT": 4, "WATCH": 3, "AVOID": 2}.get(item.final_action.final_action, 1),
            item.impact.impact_score,
            item.entry.opportunity_score,
        ),
        reverse=True,
    )[:5]
    lines = [
        "【Investment OS V5 交易过滤层】",
        "最终动作统一由 FINAL_ACTION 生成，V4评分不得绕过V5直接触发BUY。",
        "",
        "【S/A机会与动作】",
    ]
    if not top:
        lines.append("暂无达到V5推送门槛的S/A机会。")
    else:
        for result in top:
            lines.append(
                "{}｜{}级｜{}｜{}｜机会{}｜风险{}".format(
                    result.signal_record.symbol,
                    result.grade.grade,
                    result.entry.entry_model,
                    result.final_action.final_action,
                    result.entry.opportunity_score,
                    result.entry.risk_score,
                )
            )
    lines.extend(
        [
            "",
            "【过滤统计】",
            f"本轮评估：{len(results)}",
            f"被过滤：{len(filtered)}",
            "过滤原则：B/C级、普通新闻、普通波动、重复事件、无交易价值信息不发送。",
        ]
    )
    return "\n".join(lines)


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
                "【Investment OS V5 连通性测试】\n"
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
        LOGGER.exception("本次V5分析出现未处理错误（敏感响应内容不会记录）。")
        return 1
    LOGGER.info("扫描时间：%s", started.isoformat())
    LOGGER.info("运行模式：%s", args.mode)
    LOGGER.info("本模式扫描资产数量：%d", scanned_count)
    LOGGER.info("生成并发送消息数量：%d", sent)
    LOGGER.info("发送失败或因未配置跳过数量：%d", failed)
    LOGGER.info("V5生产模式：实时消息必须经过TradeFilterLayer与FINAL_ACTION。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
