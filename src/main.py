from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .alerts import detect_alerts, format_alert
from .daily_summary import build_daily_summary
from .feishu import FeishuClient
from .market_data import MarketDataClient, MarketSnapshot
from .news import NewsClient, NewsItem
from .scoring import Scores, calculate_scores
from .state import StateStore

LOGGER = logging.getLogger("investment_os")
UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Investment OS 云端监控")
    parser.add_argument("--mode", choices=("realtime", "daily"), default="realtime")
    parser.add_argument("--state", default=str(ROOT / "state" / "alerts.json"))
    parser.add_argument("--dry-run", action="store_true", help="只扫描并生成消息，不发送")
    parser.add_argument("--test-message", action="store_true", help="发送一条飞书连通性测试消息")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def scan(assets: list[dict]) -> tuple[dict[str, MarketSnapshot], list[NewsItem], dict[str, Scores]]:
    market_assets = assets + [{"symbol": "DX-Y.NYB", "type": "macro"}]
    snapshots = MarketDataClient().fetch_all(market_assets)
    news = NewsClient().fetch(assets)
    scores = {
        symbol: calculate_scores(
            snapshot, [item for item in news if symbol in item.assets]
        )
        for symbol, snapshot in snapshots.items()
        if symbol != "DX-Y.NYB"
    }
    return snapshots, news, scores


def run_realtime(
    assets: list[dict],
    thresholds: dict,
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    snapshots, news, scores = scan(assets)
    now = datetime.now(UTC)
    triggered = 0
    duplicates = 0
    dedup = thresholds["dedup"]

    if not feishu.configured and not dry_run:
        LOGGER.warning("未配置 FEISHU_WEBHOOK：扫描继续，发送阶段将跳过。")

    for asset in assets:
        symbol = asset["symbol"]
        snapshot = snapshots[symbol]
        if snapshot.error:
            LOGGER.warning("%s 数据暂不可用；已跳过技术信号。", symbol)
        elif not snapshot.fresh:
            LOGGER.info("%s 行情数据时间较旧；仅保留数据，不触发实时预警。", symbol)
        related_news = [item for item in news if symbol in item.assets]
        candidates = detect_alerts(snapshot, scores[symbol], related_news, thresholds)
        for candidate in candidates:
            if candidate.news and state.news_seen(candidate.news.fingerprint):
                duplicates += 1
                continue
            allowed = state.should_send_alert(
                symbol,
                candidate.alert_type,
                candidate.strength,
                now,
                cooldown_minutes=dedup["cooldown_minutes"],
                strengthening_ratio=dedup["strengthening_ratio"],
                strengthening_points=dedup["strengthening_points"],
            )
            if not allowed:
                duplicates += 1
                # 同一类型冷却期内出现的另一条新闻不应在数小时后作为旧闻补发。
                if candidate.news and not dry_run:
                    state.record_news(candidate.news.fingerprint, now)
                continue
            message = format_alert(candidate, snapshot, related_news)
            if dry_run:
                LOGGER.info("演练模式命中：%s / %s（未发送）", symbol, candidate.alert_type)
                triggered += 1
                continue
            if feishu.send(message):
                triggered += 1
                state.record_alert(
                    symbol,
                    candidate.alert_type,
                    candidate.strength,
                    now,
                    candidate.reasons[0],
                )
                if candidate.news:
                    state.record_news(candidate.news.fingerprint, now)

    # BTC 的跨市场背景用于判断日志和消息上下文，不单独创造阈值外的信号。
    _log_btc_context(snapshots)
    state.save()
    return triggered, duplicates


def run_daily(
    assets: list[dict],
    state: StateStore,
    feishu: FeishuClient,
    dry_run: bool,
) -> tuple[int, int]:
    snapshots, news, scores = scan(assets)
    visible = {key: value for key, value in snapshots.items() if key != "DX-Y.NYB"}
    message = build_daily_summary(
        visible, scores, news, state.data.get("history", []), datetime.now(UTC)
    )
    if dry_run:
        LOGGER.info("演练模式：已生成每日汇总，未发送。")
        return 1, 0
    sent = feishu.send(message)
    state.save()
    return (1 if sent else 0), 0


def _log_btc_context(snapshots: dict[str, MarketSnapshot]) -> None:
    qqq = snapshots.get("QQQ")
    dxy = snapshots.get("DX-Y.NYB")
    qqq_text = _context_change(qqq)
    dxy_text = _context_change(dxy)
    LOGGER.info("BTC 跨市场背景：美股风险偏好(QQQ)=%s；美元指数代理=%s。", qqq_text, dxy_text)


def _context_change(snapshot: MarketSnapshot | None) -> str:
    if not snapshot or snapshot.error or snapshot.changes.get("1h") is None:
        return "数据暂不可用"
    return f"1小时 {snapshot.changes['1h']:+.2f}%（数据时间 {snapshot.data_time.isoformat()}）"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s｜%(levelname)s｜%(message)s")
    args = parse_args()
    started = datetime.now(UTC)
    watchlist = load_json(ROOT / "config" / "watchlist.json")
    thresholds = load_json(ROOT / "config" / "thresholds.json")
    assets = watchlist["assets"]
    state = StateStore(args.state)
    state.load()
    feishu = FeishuClient()

    if args.test_message:
        if args.dry_run:
            LOGGER.info("演练模式：跳过飞书连通性测试消息。")
        else:
            feishu.send(
                "【Investment OS 连通性测试】\n"
                "飞书 Webhook 配置有效。本消息不代表市场预警，也不构成投资建议。"
            )

    try:
        if args.mode == "daily":
            triggered, duplicates = run_daily(assets, state, feishu, args.dry_run)
        else:
            triggered, duplicates = run_realtime(
                assets, thresholds, state, feishu, args.dry_run
            )
    except Exception:
        LOGGER.exception("本次扫描出现未处理错误（敏感响应内容不会记录）。")
        return 1
    LOGGER.info("扫描时间：%s", started.isoformat())
    LOGGER.info("扫描资产数量：%d", len(assets))
    LOGGER.info("触发信号数量：%d", triggered)
    LOGGER.info("跳过的重复信号数量：%d", duplicates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
