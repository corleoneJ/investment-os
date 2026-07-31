from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .decision_engine import DecisionReport
from .market_data import MarketSnapshot

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
