"""Feishu text formatter for V5 trade signals."""

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
    context = signal.context
    market = context.market
    flow = context.flow
    rr = signal.risk_reward
    now = generated_at or datetime.now().astimezone()
    is_buy = signal.final_action.final_action == "BUY"
    title = (
        "【Investment OS V5 买入信号】"
        if is_buy
        else "【Investment OS V5 {}级机会】".format(signal.grade.grade)
    )
    action_label = signal.final_action.action_label
    second_buy = "回踩EMA20/VWAP企稳后加仓" if is_buy else "等待确认"
    first_buy = (
        "建议买入区间：{:.2f}附近".format(rr.entry_price)
        if is_buy
        else "等待回踩到EMA20/VWAP附近并企稳"
    )
    wait_condition = (
        "等待价格回踩到EMA20/VWAP附近，RSI不过热，并出现放量企稳或突破确认。"
        if signal.entry.entry_model == "WAIT_FOR_PULLBACK"
        else "等待最终动作解析器重新确认。"
    )
    return "\n".join(
        [
            title,
            "资产：{}".format(context.event.symbol),
            "时间：{}".format(now.strftime("%Y-%m-%d %H:%M %Z")),
            "",
            "机会等级：{}".format(signal.grade.grade),
            "当前动作：{}".format(signal.final_action.final_action),
            "动作说明：{}".format(action_label),
            *([] if is_buy else ["当前不建议追涨"]),
            "",
            "【核心结论】",
            signal.final_action.reason,
            "",
            "【事件】",
            "事件：{}".format(context.event.title),
            "Impact Score：{}".format(signal.impact.impact_score),
            "是否已定价：{}".format("是" if signal.reaction.priced_in_score >= 70 else "否"),
            "",
            "【资金】",
            "资金状态：{}".format("确认" if flow.confirmed else "未确认"),
            "成交量：{:.1f}x".format(market.volume_ratio),
            "VWAP：偏离{:+.1f}%".format(market.vwap_deviation_pct),
            "资金确认：{}".format("是" if flow.confirmed else "否"),
            "",
            "【技术】",
            "趋势：{}".format(market.trend),
            "RSI：{:.1f}".format(market.rsi),
            "EMA：EMA20 {}".format("{:.2f}".format(market.ema20) if market.ema20 else "N/A"),
            "突破/回踩状态：{}".format(signal.entry.entry_model),
            "",
            "【买入计划】",
            "第一买点：{}".format(first_buy),
            "第二买点：{}".format(second_buy),
            "建议仓位：{}".format("小额首仓" if is_buy else "暂不新增"),
            "止损：{:.2f}（{}，{:+.2f}%）".format(rr.stop_loss, rr.stop_type, rr.stop_percent),
            "目标1：{:.2f}".format(rr.target_1),
            "目标2：{:.2f}".format(rr.target_2),
            "盈亏比：{:.2f}".format(rr.risk_reward_ratio),
            "",
            *([] if is_buy else ["【等待条件】", wait_condition, ""]),
            "【风险】",
            *["{}. {}".format(index, item) for index, item in enumerate(signal.risks, 1)],
            "",
            "【执行建议】",
            signal.final_action.execution_advice,
            "",
            "【失效条件】",
            signal.invalidation,
        ]
    )
