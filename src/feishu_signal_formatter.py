"""Feishu text formatter for V5 trade signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from src.entry_timing import EntryTimingDecision
from src.final_action import FinalActionDecision
from src.market_impact_engine import MarketImpactResult
from src.models import TradeContext
from src.price_reaction import PriceReactionResult
from src.risk_reward import RiskRewardPlan
from src.trade_grade import TradeGradeResult


@dataclass(frozen=True)
class V5Signal:
    context: TradeContext
    grade: TradeGradeResult
    entry: EntryTimingDecision
    final_action: FinalActionDecision
    impact: MarketImpactResult
    reaction: PriceReactionResult
    risk_reward: RiskRewardPlan
    risks: Sequence[str]
    invalidation: str


def format_signal(signal: V5Signal, generated_at: datetime = None) -> str:
    if signal.final_action.final_action != "BUY":
        return ""
    context = signal.context
    market = context.market
    flow = context.flow
    rr = signal.risk_reward
    now = generated_at or datetime.now().astimezone()
    buy_reasons = _buy_reasons(signal)
    if len(buy_reasons) < 3:
        raise ValueError("BUY消息至少需要3条结构化买入理由")
    risks = list(signal.risks[:3])
    while len(risks) < 3:
        risks.append("公开数据可能延迟或缺失，若关键数据失效需要重新评估。")
    return "\n".join(
        [
            "【Investment OS V5 买入信号】",
            "资产：{}".format(context.event.symbol),
            "时间：{}".format(now.strftime("%Y-%m-%d %H:%M %Z")),
            "当前价格：{:.2f}".format(market.price),
            "",
            "【核心结论】",
            "一句话说明：{} 当前满足ENTRY_CONFIRMED、资金确认、技术确认和风险收益比要求，因此只允许小额首仓。".format(
                context.event.symbol
            ),
            "",
            "【买入理由】",
            *["{}. {}".format(index, reason) for index, reason in enumerate(buy_reasons, 1)],
            "",
            "【触发条件】",
            _trigger_text(signal),
            "",
            "【资金确认】",
            "成交量：相对成交量 {:.1f}x，{}".format(market.volume_ratio, "已放大" if flow.volume_confirmed else "未确认"),
            "VWAP：偏离 {:+.1f}%，{}".format(market.vwap_deviation_pct, "已确认" if flow.vwap_confirmed else "未确认"),
            "OBV：{}".format("资金代理确认" if flow.money_flow_confirmed else "资金代理未确认"),
            "其它资金信息：资金分 {}，{}".format(flow.fund_flow_score, "资金重新流入" if flow.flow_turning_positive else "资金未转正"),
            "",
            "【技术位置】",
            "趋势：{}".format(market.trend),
            "EMA：EMA20 {}｜EMA50 {}".format(_price(market.ema20), _price(market.ema50)),
            "RSI：{:.1f}".format(market.rsi),
            "支撑：{}".format(_price(market.support)),
            "压力：{}".format(_price(market.resistance)),
            "是否过热：{}".format("否" if not signal.reaction.is_overheated else "是"),
            "",
            "【基本面 / 催化剂】",
            "事件：{}".format(context.event.title),
            "影响：Impact Score {}｜方向 {}".format(signal.impact.impact_score, signal.impact.impact_direction),
            "产业链：{}，权重代理分 {}".format("系统识别到产业链传导" if context.event.industry_impact else "暂未确认产业链传导", context.event.industry_impact),
            "是否已充分定价：{}".format("否" if not signal.impact.market_priced_in else "是"),
            "",
            "【已确认事实】",
            "{} 于 {} 发布：{}".format(context.event.source, _time(context.event.published_at), context.event.title),
            "",
            "【系统推断】",
            signal.impact.reasoning,
            "",
            "【暂无法验证】",
            "产业链传导、实时机构资金和后续订单兑现仍需后续公开数据验证。",
            "",
            "【买入计划】",
            "建议：允许小额首仓",
            "买入区间：{:.2f}附近".format(rr.entry_price),
            "建议仓位：只允许小额首仓，不得重仓。",
            "止损：{:.2f}（{}，{:+.2f}%）".format(rr.stop_loss, rr.stop_type, rr.stop_percent),
            "目标1：{:.2f}".format(rr.target_1),
            "目标2：{:.2f}".format(rr.target_2),
            "风险收益比：{:.2f}".format(rr.risk_reward_ratio),
            "",
            "【主要风险】",
            *["{}. {}".format(index, item) for index, item in enumerate(risks, 1)],
            "",
            "【失效条件】",
            signal.invalidation,
            "",
            "【一句总结】",
            "{} 不是因为“值得关注”而买，而是因为 BUY 条件已经同时成立。若跌破止损结构，本次BUY逻辑失效。".format(
                context.event.symbol
            ),
        ]
    )


def _buy_reasons(signal: V5Signal) -> list[str]:
    context = signal.context
    market = context.market
    flow = context.flow
    rr = signal.risk_reward
    reasons = [
        "重大催化剂已确认：{}，Impact Score {}，不是普通新闻。".format(
            context.event.title, signal.impact.impact_score
        ),
        "资金确认：相对成交量 {:.1f}x，VWAP偏离 {:+.1f}%，资金分 {}，成交量/资金代理均通过。".format(
            market.volume_ratio, market.vwap_deviation_pct, flow.fund_flow_score
        ),
        "技术确认：入场模型为 {}，价格位于EMA20 {} 上方，RSI {:.1f}，当前未处于明显过热。".format(
            signal.entry.entry_model, _price(market.ema20), market.rsi
        ),
        "风险收益比合格：R/R {:.2f}，止损 {}，目标1 {}，目标2 {}。".format(
            rr.risk_reward_ratio, _price(rr.stop_loss), _price(rr.target_1), _price(rr.target_2)
        ),
    ]
    if context.valuation.valuation_support:
        reasons.append("估值/基本面过滤通过：估值支持为真，基本面趋势未被系统判定恶化。")
    return reasons[:5]


def _trigger_text(signal: V5Signal) -> str:
    market = signal.context.market
    triggers = ["ENTRY_CONFIRMED"]
    if market.pullback_confirmed:
        triggers.append("回踩关键均线/支撑后重新站稳")
    if market.broke_resistance:
        triggers.append("放量突破关键压力")
    if signal.context.flow.vwap_confirmed:
        triggers.append("VWAP收复/站稳")
    if signal.context.flow.flow_turning_positive:
        triggers.append("资金重新流入")
    return "；".join(triggers)


def _price(value: float | None) -> str:
    return "数据暂不可用" if value is None else "{:.2f}".format(value)


def _time(value) -> str:
    return "发布时间暂不可用" if value is None else value.isoformat()
