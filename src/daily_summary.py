from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .alerts import format_pct
from .market_data import MarketSnapshot
from .news import NewsItem
from .scoring import Scores

BEIJING = ZoneInfo("Asia/Shanghai")


def build_daily_summary(
    snapshots: dict[str, MarketSnapshot],
    scores: dict[str, Scores],
    news: list[NewsItem],
    history: list[dict],
    now: datetime,
) -> str:
    local_now = now.astimezone(BEIJING)
    today_events = [
        item for item in history
        if _is_today(item.get("time", ""), local_now.date().isoformat())
    ]
    available = [item for item in snapshots.values() if item.changes.get("24h") is not None]
    biggest = max(available, key=lambda item: abs(item.changes["24h"] or 0), default=None)
    reliable_scores = {
        symbol: score for symbol, score in scores.items()
        if symbol in snapshots and not snapshots[symbol].error
    }
    opportunity = sorted(
        reliable_scores.items(), key=lambda item: item[1].opportunity, reverse=True
    )[:3]
    risks = sorted(reliable_scores.items(), key=lambda item: item[1].risk, reverse=True)[:3]

    event_lines = (
        "\n".join(f"- {item['asset']}｜{item['type']}｜{item['summary']}" for item in today_events[-10:])
        if today_events else "- 今日无重大异常，维持原定定投计划。"
    )
    biggest_line = (
        f"{biggest.asset}（{format_pct(biggest.changes.get('24h'))}，数据时间 "
        f"{biggest.data_time.astimezone(BEIJING):%Y-%m-%d %H:%M}）"
        if biggest else "数据暂不可用"
    )
    news_lines = "- 当前免费数据源未发现可确认的明日事件；请关注 SEC、BLS 与美联储官方日历更新。"
    adjust = _investment_rhythm(scores, today_events)
    return f"""【Investment OS 每日汇总】

日期：{local_now:%Y-%m-%d}（北京时间）

当日触发过的预警：
{event_lines}

当日涨跌幅最大资产：
{biggest_line}

当日机会榜 Top3：
{_rank_lines(opportunity, "opportunity")}

当日风险榜 Top3：
{_rank_lines(risks, "risk")}

明日重点事件：
{news_lines}
说明：仅列出当前已获取的官方/主流来源信息；未确认日程不作推测。

今日是否需要调整定投节奏：
{adjust}

预算纪律：每日约 10 USDT、每月约 300 USDT；只做现货，不使用杠杆。
风险提示：本系统只做辅助分析，不构成收益保证。"""


def _rank_lines(items: list[tuple[str, Scores]], field: str) -> str:
    if not items:
        return "- 数据暂不可用"
    return "\n".join(
        f"{index}. {asset}：{getattr(score, field)}/100"
        for index, (asset, score) in enumerate(items, 1)
    )


def _investment_rhythm(scores: dict[str, Scores], events: list[dict]) -> str:
    high_risk = sum(1 for score in scores.values() if score.risk >= 70)
    if high_risk >= 2:
        return "风险信号偏多，建议暂缓新增，等待重新企稳。"
    if any(item.get("type") == "急涨预警" for item in events):
        return "存在急涨资产，维持预算但不追高，等待回踩。"
    return "无需调整，维持原定定投计划；如执行则继续小额分批。"


def _is_today(value: str, target_date: str) -> bool:
    try:
        return datetime.fromisoformat(value).astimezone(BEIJING).date().isoformat() == target_date
    except ValueError:
        return False
