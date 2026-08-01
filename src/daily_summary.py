from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .decision_engine import DecisionReport
from .market_data import MarketSnapshot
from .v4_engine import V4Report

BEIJING = ZoneInfo("Asia/Shanghai")


def build_daily_summary(
    report: DecisionReport,
    snapshots: dict[str, MarketSnapshot],
    history: list[dict],
    now: datetime,
) -> str:
    local_now = now.astimezone(BEIJING)
    today_events = [
        item
        for item in history
        if _is_today(item.get("time", ""), local_now.date().isoformat())
    ]
    best = report.opportunities[0] if report.opportunities else None
    highest_risk = report.risks[0] if report.risks else None
    industry_changes = _industry_changes(report)
    tomorrow = _tomorrow_events(report, local_now)
    top_opportunities = "\n".join(
        f"{index}. {item.asset}：{item.score}/100｜{item.reasons[0]}"
        for index, item in enumerate(report.opportunities[:5], 1)
    ) or "数据暂不可用"
    top_risks = "\n".join(
        f"{index}. {item.asset}：{item.score}/100｜{item.reasons[0]}"
        for index, item in enumerate(report.risks[:5], 1)
    ) or "数据暂不可用"
    summary = _one_line_summary(best, highest_risk)
    action = _daily_action(report)
    return f"""【Investment OS V3 每日决策】

日期：{local_now:%Y-%m-%d}（北京时间）

今天发生了什么：
共生成 {len(today_events)} 条已发送AI决策；扫描 {len(report.decisions)} 个资产。

最大的机会：
{best.asset if best else "数据暂不可用"}｜{best.score if best else 0}/100
{best.reasons[0] if best else "数据暂不可用"}

最大的风险：
{highest_risk.asset if highest_risk else "数据暂不可用"}｜{highest_risk.score if highest_risk else 0}/100
{highest_risk.reasons[0] if highest_risk else "数据暂不可用"}

机会 TOP5：
{top_opportunities}

风险 TOP5：
{top_risks}

产业链变化：
{industry_changes}

明天重点关注：
{tomorrow}

执行建议：
{action}

AI一句总结：
{summary}

风险提示：本系统只做辅助分析，不构成收益保证。"""


def build_v4_daily_summary(
    report: V4Report,
    snapshots: dict[str, MarketSnapshot],
    history: list[dict],
    now: datetime,
) -> str:
    local_now = now.astimezone(BEIJING)
    today = [item for item in history if _is_today(item.get("time", ""), local_now.date().isoformat())]
    early_by_asset: dict[str, dict] = {}
    for item in today:
        early_by_asset.setdefault(item.get("asset", ""), item)
    comparisons: list[str] = []
    errors: list[str] = []
    for symbol, early in sorted(early_by_asset.items()):
        snapshot = snapshots.get(symbol)
        early_price = early.get("price")
        if snapshot and not snapshot.error and isinstance(early_price, (int, float)) and early_price:
            actual = (snapshot.price / early_price - 1) * 100
            comparisons.append(
                f"- {symbol}：早期机会{early.get('opportunity_score', '不可用')}、"
                f"风险{early.get('risk_score', '不可用')}；此后至当前 {actual:+.2f}%"
            )
            if early.get("opportunity_score", 0) >= 70 and actual < -2:
                errors.append(f"- {symbol}：高机会判断后下跌 {actual:.2f}%，需要继续验证或修正规则。")
    tomorrow = _v4_tomorrow(report, local_now)
    focus = "、".join(item.symbol for item in report.rankings.comprehensive[:5]) or "数据暂不可用"
    pace = _v4_daily_action(report)
    alpha = _ranking_lines(report.rankings.alpha)
    return f"""【Investment OS V4 每日决策】

日期：{local_now:%Y-%m-%d}（北京时间）

1. 今日综合机会榜
{_ranking_lines(report.rankings.comprehensive)}

2. 今日Alpha补涨榜
{alpha}

3. 今日资金确认榜
{_ranking_lines(report.rankings.flow)}

4. 今日估值吸引力榜
{_ranking_lines(report.rankings.valuation)}

5. 今日风险榜
{_ranking_lines(report.rankings.risk)}

6. 今日实际涨幅与早期判断对照
{chr(10).join(comparisons[:10]) or '今日状态中暂无可比较的早期价格；不伪造复盘结果。'}

7. 今日错误或未确认判断
{chr(10).join(errors[:5]) or '暂未识别出可量化错误；未确认的产业链推断仍需等待官方数据验证。'}

8. 明日事件日历
{tomorrow}

9. 明日重点观察资产
{focus}

10. 是否调整每日定投节奏
{pace}。不因榜单日内变化频繁交易，继续遵守每日约10 USDT、每月约300 USDT预算。

AI一句总结：{_v4_one_line(report)}

风险提示：仅供辅助分析，不构成收益保证。"""


def _ranking_lines(items) -> str:
    return "\n".join(
        f"{index}. {item.symbol}：{item.score}/100｜{item.explanation}"
        for index, item in enumerate(items, 1)
    ) or "数据暂不可用"


def _v4_tomorrow(report: V4Report, local_now: datetime) -> str:
    tomorrow = local_now.date().fromordinal(local_now.date().toordinal() + 1)
    events = [event for event in report.future_events if event.event_time.astimezone(BEIJING).date() == tomorrow]
    return "\n".join(
        f"- {event.event_time.astimezone(BEIJING):%H:%M}｜{event.name}｜{'、'.join(event.assets)}"
        for event in events
    ) or "官方事件源暂未发现可确认的明日事件。"


def _v4_daily_action(report: V4Report) -> str:
    if not report.scores:
        return "暂缓新增"
    high_risk = sum(score.risk_score >= 70 for score in report.scores.values())
    if high_risk >= 3:
        return "暂停新增"
    top = report.rankings.comprehensive[0] if report.rankings.comprehensive else None
    return report.scores[top.symbol].action if top else "继续定投"


def _v4_one_line(report: V4Report) -> str:
    opportunity = report.rankings.comprehensive[0].symbol if report.rankings.comprehensive else "数据不足"
    risk = report.rankings.risk[0].symbol if report.rankings.risk else "数据不足"
    return f"今日优先验证 {opportunity} 的机会线索，同时防范 {risk} 风险；不把概率判断包装成确定性机会。"


def _industry_changes(report: DecisionReport) -> str:
    if not report.events:
        return "暂未发现可确认的重大产业链事件。"
    lines: list[str] = []
    seen: set[str] = set()
    for event in sorted(report.events, key=lambda item: item.level, reverse=True):
        if event.industry.theme in seen:
            continue
        seen.add(event.industry.theme)
        beneficiaries = "、".join(event.industry.beneficiaries) or "待确认"
        victims = "、".join(event.industry.victims) or "待确认"
        lines.append(
            f"- {event.industry.theme}：{' → '.join(event.industry.chain)}；"
            f"受益 {beneficiaries}；受损 {victims}"
        )
    return "\n".join(lines[:5])


def _tomorrow_events(report: DecisionReport, local_now: datetime) -> str:
    tomorrow = local_now.date().fromordinal(local_now.date().toordinal() + 1)
    matched = [
        event
        for event in report.future_events
        if event.event_time.astimezone(BEIJING).date() == tomorrow
    ]
    if not matched:
        return "未来事件源暂未发现可确认的明日事件；继续关注官方日历。"
    return "\n".join(
        f"- {event.event_time.astimezone(BEIJING):%H:%M}｜{event.name}｜"
        f"可能波动资产：{'、'.join(event.assets)}"
        for event in matched
    )


def _one_line_summary(best, highest_risk) -> str:
    if not best or not highest_risk:
        return "数据不足，当前最重要的是等待可靠信息，不做确定性判断。"
    if highest_risk.score > best.score:
        return (
            f"今天风险端以 {highest_risk.asset} 最突出，"
            f"机会端关注 {best.asset}，执行上先控制新增仓位。"
        )
    return (
        f"今天真正值得关注的是 {best.asset} 的机会线索，"
        f"同时防范 {highest_risk.asset} 的风险。"
    )


def _daily_action(report: DecisionReport) -> str:
    if not report.decisions:
        return "暂停新增"
    risk_count = sum(1 for decision in report.decisions if decision.risk.score >= 70)
    if risk_count >= 3:
        return "暂停新增"
    top = report.opportunities[0] if report.opportunities else None
    if top and top.score >= 75:
        decision = next(item for item in report.decisions if item.asset == top.asset)
        return decision.action
    return "继续定投"


def _is_today(value: str, target_date: str) -> bool:
    try:
        return datetime.fromisoformat(value).astimezone(BEIJING).date().isoformat() == target_date
    except ValueError:
        return False
