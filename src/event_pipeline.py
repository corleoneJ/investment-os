from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .feishu import FeishuClient
from .future_events import FutureEvent
from .industry_graph import IndustryGraph
from .market_data import MarketSnapshot
from .news import NewsItem
from .state import StateStore, stable_event_id

LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
BEIJING = ZoneInfo("Asia/Shanghai")


class EventScanManager:
    """跨工作流事件入库、合并和技术去重；不实施评分或频率阈值。"""

    def __init__(self, root: Path, feishu: FeishuClient, state: StateStore) -> None:
        self.graph = IndustryGraph.from_yaml(root / "config" / "industry_graph.yaml")
        self.feishu = feishu
        self.state = state

    def deliver(
        self,
        workflow: str,
        heading: str,
        news: list[NewsItem],
        future_events: list[FutureEvent],
        dry_run: bool = False,
        market_context: dict[str, MarketSnapshot] | None = None,
    ) -> tuple[int, int, int]:
        entries: list[dict] = []
        news_by_id: dict[str, NewsItem] = {}
        for item in news:
            if not item.is_major:
                continue
            event_id = news_event_id(item)
            news_by_id[event_id] = item
            entries.append(
                self.state.upsert_event(
                    event_id=event_id,
                    kind="news",
                    title=item.title,
                    source=item.source,
                    source_url=item.url,
                    event_time=item.published_at,
                    assets=item.assets,
                    category=item.category,
                    workflow=workflow,
                    is_major=item.is_major,
                    is_negative=item.is_negative,
                )
            )
        for event in future_events:
            event_id = stable_event_id(
                "future", event.source, event.url, event.name, event.event_time.isoformat()
            )
            entries.append(
                self.state.upsert_event(
                    event_id=event_id,
                    kind="future",
                    title=event.name,
                    source=event.source,
                    source_url=event.url,
                    event_time=event.event_time,
                    assets=event.assets,
                    category=event.expected_impact,
                    workflow=workflow,
                )
            )
        unique = {entry["event_id"]: entry for entry in entries}
        pending = [entry for entry in unique.values() if not entry.get("notified")]
        skipped = len(unique) - len(pending)
        self.state.save()
        LOGGER.info(
            "%s：采集事件%d，待通知%d，技术去重%d。",
            heading,
            len(unique),
            len(pending),
            skipped,
        )
        if not pending:
            return 0, 0, skipped
        message = format_event_digest(
            heading, pending, news_by_id, self.graph, market_context or {}
        )
        if dry_run:
            LOGGER.info("演练模式：已生成一条%s合并消息，未发送。", heading)
            return 1, 0, skipped
        if not self.feishu.configured:
            LOGGER.warning("未配置 FEISHU_WEBHOOK：事件已入共享状态，合并消息跳过发送。")
            return 0, 1, skipped
        if not self.feishu.send(message):
            return 0, 1, skipped
        now = datetime.now(UTC)
        self.state.mark_events_notified([entry["event_id"] for entry in pending], now)
        self.state.data["history"].append(
            {
                "time": now.isoformat(),
                "asset": "、".join(sorted({asset for entry in pending for asset in entry["assets"]})),
                "type": f"{workflow}合并事件",
                "event_ids": [entry["event_id"] for entry in pending],
                "summary": f"{heading}合并推送，共{len(pending)}个新事件。",
            }
        )
        self.state.save()
        return 1, 0, skipped


def format_event_digest(
    heading: str,
    entries: list[dict],
    news_by_id: dict[str, NewsItem],
    graph: IndustryGraph,
    market_context: dict[str, MarketSnapshot],
) -> str:
    facts: list[str] = []
    inferences: list[str] = []
    affected: set[str] = set()
    for index, entry in enumerate(entries[:12], 1):
        affected.update(entry.get("assets", []))
        event_time = parse_event_time(entry.get("event_time"))
        facts.append(
            f"{index}. [{entry['event_id']}] {entry['title']}｜{entry['source']}｜"
            f"{event_time.astimezone(BEIJING):%m-%d %H:%M}"
        )
        item = news_by_id.get(entry["event_id"])
        impacts = graph.match(item) if item else []
        if impacts:
            chains = [" → ".join(impact.path) for impact in impacts[:5]]
            inferences.append(f"- {entry['event_id']}：" + "；".join(chains))
    context_lines = []
    for symbol in ("BTC-USD", "QQQ", "DX-Y.NYB", "^TNX"):
        snapshot = market_context.get(symbol)
        if snapshot:
            context_lines.append(
                f"{symbol}：{_price(None if snapshot.error else snapshot.price)}｜"
                f"1小时 {_pct(snapshot.changes.get('1h'))}｜"
                f"数据时间 {snapshot.data_time.astimezone(BEIJING):%m-%d %H:%M}"
            )
    return f"""【Investment OS V4 {heading}】

扫描时间：{datetime.now(UTC).astimezone(BEIJING):%Y-%m-%d %H:%M:%S}（北京时间）
本轮新事件：{len(entries)}
影响资产：{"、".join(sorted(affected)) or "数据暂不可用"}

【已确认事实/官方日历】
{chr(10).join(facts)}

【产业链系统推断】
{chr(10).join(inferences) or "本轮未匹配到可配置产业链路径；不把新闻标题包装成确定性机会。"}

【宏观与市场上下文】
{chr(10).join(context_lines) or "本工作流未采集实时行情；请结合实时决策消息。"}

【执行原则】
事件仅作为研究线索；等待资金、估值与技术位置确认，不追高，不使用杠杆或一次性重仓。

风险提示：仅供辅助分析，不构成收益保证。"""


def parse_event_time(value: str | None) -> datetime:
    try:
        parsed = datetime.fromisoformat(value or "")
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def news_event_id(item: NewsItem) -> str:
    """优先按资产、日期和事件语义归一，来源不同也可补充同一事件。"""
    text = f"{item.title} {item.category}".lower()
    signatures = {
        "earnings": ("earnings", "10-q", "10-k", "财报", "业绩"),
        "guidance": ("guidance", "outlook", "指引"),
        "ai_capex": ("ai capex", "capital expenditure", "资本开支"),
        "merger": ("merger", "acquisition", "并购", "收购"),
        "investigation": ("investigation", "accounting", "调查", "会计"),
        "lawsuit": ("lawsuit", "litigation", "诉讼"),
        "management": ("ceo", "chief executive", "管理层"),
        "btc_etf": ("bitcoin etf", "btc etf", "比特币etf"),
        "regulation": ("regulation", "regulatory", "监管"),
    }
    signature = next(
        (name for name, terms in signatures.items() if any(term in text for term in terms)),
        None,
    )
    if signature and item.assets:
        return stable_event_id(
            "semantic-news",
            signature,
            item.published_at.astimezone(UTC).date().isoformat(),
            ",".join(sorted(item.assets)),
        )
    return stable_event_id("news", item.url or item.title)


def _price(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:,.2f}"


def _pct(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:+.2f}%"
