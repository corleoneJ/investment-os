from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .decision_engine import AssetDecision, DecisionReport
from .feishu import FeishuClient
from .market_data import MarketSnapshot
from .state import StateStore
from .v4_engine import V4AssetDecision, V4Report

LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
BEIJING = ZoneInfo("Asia/Shanghai")


class AlertManager:
    """V3 观察阶段：不做冷却、不做评分门槛，每个资产决策全部发送。"""

    def __init__(self, feishu: FeishuClient, state: StateStore) -> None:
        self.feishu = feishu
        self.state = state

    def deliver(
        self,
        report: DecisionReport,
        snapshots: dict[str, MarketSnapshot],
        dry_run: bool = False,
    ) -> tuple[int, int]:
        if not dry_run and not self.feishu.configured:
            LOGGER.warning("未配置 FEISHU_WEBHOOK：V3分析已完成，全部消息跳过发送。")
            return 0, len(report.decisions)
        sent = 0
        failed = 0
        now = datetime.now(UTC)
        for decision in report.decisions:
            message = format_ai_message(decision, snapshots[decision.asset])
            if dry_run:
                LOGGER.info(
                    "演练模式生成：%s｜机会%d｜风险%d｜%s",
                    decision.asset,
                    decision.opportunity.score,
                    decision.risk.score,
                    decision.action,
                )
                sent += 1
                continue
            if self.feishu.send(message):
                sent += 1
                self.state.record_alert(
                    decision.asset,
                    "AI决策",
                    max(decision.opportunity.score, decision.risk.score),
                    now,
                    decision.summary,
                )
            else:
                failed += 1
        self.state.save()
        return sent, failed

    def deliver_v4(self, report: V4Report, dry_run: bool = False) -> tuple[int, int]:
        """同一轮对同一资产只发送一条合并决策；V4观察期不做频率过滤。"""
        unique = {decision.symbol: decision for decision in report.decisions}
        if not dry_run and not self.feishu.configured:
            LOGGER.warning("未配置 FEISHU_WEBHOOK：V4分析已完成，全部消息跳过发送。")
            return 0, len(unique)
        sent = 0
        failed = 0
        now = datetime.now(UTC)
        for decision in unique.values():
            message = format_v4_message(decision, report.generated_at)
            if dry_run:
                LOGGER.info(
                    "演练模式生成V4合并消息：%s｜综合%d｜机会%d｜风险%d｜%s",
                    decision.symbol,
                    decision.score.investment_score,
                    decision.score.opportunity_score,
                    decision.score.risk_score,
                    decision.score.action,
                )
                sent += 1
                continue
            if self.feishu.send(message):
                sent += 1
                snapshot = decision.snapshot
                self.state.record_v4_decision(
                    asset=decision.symbol,
                    now=now,
                    price=None if snapshot.error else snapshot.price,
                    investment_score=decision.score.investment_score,
                    opportunity_score=decision.score.opportunity_score,
                    risk_score=decision.score.risk_score,
                    data_quality_score=decision.score.data_quality_score,
                    action=decision.score.action,
                    summary=decision.summary,
                )
            else:
                failed += 1
        self.state.save()
        return sent, failed


def format_v4_message(decision: V4AssetDecision, generated_at: datetime) -> str:
    snapshot = decision.snapshot
    alpha = decision.alpha
    impact = decision.graph_impact
    provider = snapshot.provider
    provider_text = (
        f"{provider.source}｜{provider.status.value}｜抓取{provider.fetched_at.astimezone(BEIJING):%m-%d %H:%M}"
        if provider else "数据暂不可用"
    )
    alpha_logic = "是" if alpha and alpha.alpha_score >= 55 else "尚未确认"
    priced = (
        "可能尚未充分定价" if alpha and alpha.relative_lag is not None and alpha.relative_lag >= 2
        else "已定价程度数据不足或无明显滞后"
    )
    peer_reaction = _pct(alpha.peer_reaction) if alpha else "数据暂不可用"
    own_reaction = _pct(alpha.own_reaction) if alpha else _pct(snapshot.changes.get("24h"))
    history_position = (
        next(iter(decision.valuation.historical_percentiles.values()), "数据暂不可用")
        if decision.valuation.historical_percentiles else "数据暂不可用"
    )
    support = _price(snapshot.ema20 or snapshot.recent_low)
    resistance = _price(snapshot.recent_high)
    trend = (
        "上行" if snapshot.ema20 and snapshot.ema60 and snapshot.price > snapshot.ema20 > snapshot.ema60
        else "转弱" if snapshot.ema20 and snapshot.price < snapshot.ema20
        else "震荡或数据不足"
    )
    graph_path = " → ".join(impact.path) if impact else "暂未匹配到产业链路径"
    institutional = (
        f"ETF：{decision.flow.etf_flow}；机构：{decision.flow.institutional_change}；"
        f"内部人：{decision.flow.insider_activity}"
    )
    valuation_provider = next(
        (
            provider
            for provider in decision.valuation.data_quality.providers
            if provider.status.value != "PLACEHOLDER"
        ),
        None,
    )
    if valuation_provider:
        valuation_period = (
            valuation_provider.data_timestamp.astimezone(BEIJING).strftime("%Y-%m-%d")
            if valuation_provider.data_timestamp
            else "披露期解析暂不可用"
        )
        valuation_source = (
            f"{valuation_provider.source}｜"
            f"抓取{valuation_provider.fetched_at.astimezone(BEIJING):%m-%d %H:%M}｜"
            f"数据期{valuation_period}"
        )
    else:
        valuation_source = "数据暂不可用"
    return f"""【Investment OS V4 实时决策】

资产：{decision.symbol}
时间：{generated_at.astimezone(BEIJING):%Y-%m-%d %H:%M:%S}（北京时间）
数据更新时间：{snapshot.data_time.astimezone(BEIJING):%Y-%m-%d %H:%M:%S}｜{provider_text}

【核心结论】
{decision.score.conclusion}

【评分】
综合评分：{decision.score.investment_score}/100
机会评分：{decision.score.opportunity_score}/100
风险评分：{decision.score.risk_score}/100
置信度：{decision.score.confidence_score}/100
数据质量：{decision.score.data_quality_score}/100

【催化剂】
已确认事实：{decision.confirmed_fact}
系统推断：{decision.system_inference}
暂无法验证：{decision.unverifiable}

【产业链路径】
{graph_path}

【Alpha判断】
是否存在补涨逻辑：{alpha_logic}
市场是否已充分定价：{priced}
同行表现：{peer_reaction}
自身表现：{own_reaction}

【资金】
资金结论：{decision.flow.flow_direction}（量价代理推断）
成交量：{decision.flow.volume_confirmation}｜相对量 {_number(decision.flow.relative_volume)}
ETF/机构/内部人数据：{institutional}
数据时效说明：实时量价代理更新于 {decision.flow.source_times.get('行情', '数据暂不可用')}；13F只能代表上个披露期。

【估值】
估值标签：{decision.valuation.valuation_label}
数据来源与时效：{valuation_source}
历史位置：{history_position}
同行比较：{decision.peer_summary}
周期调整：{decision.valuation.cycle_adjustment}

【技术位置】
趋势：{trend}
支撑：{support}
压力：{resistance}
是否过热：{'是' if (snapshot.rsi or 0) >= 70 else '否或数据不足'}
是否适合追入：{'否' if (snapshot.rsi or 0) >= 70 else '仍需服从资金、估值和风险过滤'}

【风险】
1. {decision.risks[0]}
2. {decision.risks[1]}
3. {decision.risks[2]}

【执行建议】
{decision.score.action}

【失效条件】
{"；".join(decision.invalidation_conditions)}

【AI一句总结】
{decision.summary}

风险提示：仅供辅助分析，不构成收益保证。"""


def format_ai_message(decision: AssetDecision, snapshot: MarketSnapshot) -> str:
    event_text = (
        f"{decision.event.stars}｜{decision.event.fact}\n"
        f"事实/推测：{decision.event.inference}"
        if decision.event
        else "暂未发现可确认的重大事件；当前判断主要来自行情与技术面。"
    )
    beneficiaries = "、".join(decision.industry.beneficiaries) or "暂未确认"
    victims = "、".join(decision.industry.victims) or "暂未确认"
    future = (
        "；".join(
            f"{event.event_time.astimezone(BEIJING):%m-%d %H:%M} {event.name}"
            for event in decision.future_events[:3]
        )
        or "未来7天暂未取得可确认事件"
    )
    technical = (
        f"价格 {_price(None if snapshot.error else snapshot.price)}；"
        f"EMA20/60/200={_price(snapshot.ema20)}/{_price(snapshot.ema60)}/{_price(snapshot.ema200)}；"
        f"RSI={_number(snapshot.rsi)}；MACD柱={_number(snapshot.macd_histogram)}；"
        f"ATR占比={_pct(snapshot.atr_pct)}；成交量={snapshot.volume_state}。"
    )
    return f"""【Investment OS AI】
★★★★★ {decision.dominant_label}

资产：
{decision.asset}

原因：
{decision.cause.primary_cause}
方向：{decision.cause.direction}｜原因可信度：{decision.cause.confidence}/100

AI分析：
{decision.cause.analysis}
技术面：{technical}

产业链：
主题：{decision.industry.theme}
传导：{" → ".join(decision.industry.chain)}
真正可能受益：{beneficiaries}
真正可能受损：{victims}
产业链判断可信度：{decision.industry.confidence}/100

事件：
{event_text}
未来事件：{future}

风险：
{decision.risk.score}/100
{"；".join(decision.risk.reasons)}

机会：
{decision.opportunity.score}/100
{"；".join(decision.opportunity.reasons)}

执行建议：
{decision.action}

AI一句总结：
{decision.summary}

风险提示：本系统只做辅助分析，不构成收益保证。"""


def _price(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:,.2f}"


def _number(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:.2f}"


def _pct(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:.2f}%"
