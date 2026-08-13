"""Single source of truth for Investment OS V5 final actions."""

from dataclasses import dataclass

from src.entry_timing import EntryTimingDecision
from src.market_impact_engine import MarketImpactResult
from src.models import FlowData, MarketData, ValuationData
from src.price_reaction import PriceReactionResult
from src.risk_reward import RiskRewardPlan
from src.trade_grade import TradeGradeResult


@dataclass(frozen=True)
class FinalActionDecision:
    final_action: str
    action_label: str
    execution_advice: str
    reason: str
    can_buy: bool


class FinalActionResolver:
    """Resolve the unique production action after grade and timing are known."""

    def resolve(
        self,
        grade: TradeGradeResult,
        entry: EntryTimingDecision,
        impact: MarketImpactResult,
        reaction: PriceReactionResult,
        risk_reward: RiskRewardPlan,
        flow: FlowData,
        market: MarketData,
        valuation: ValuationData,
        data_quality: str = "HIGH",
    ) -> FinalActionDecision:
        data_quality_pass = data_quality.upper() == "HIGH"
        if entry.entry_model == "NO_TRADE_VALUE":
            return FinalActionDecision(
                "AVOID",
                "回避",
                "继续观察",
                "事件影响不足，没有交易价值。",
                False,
            )
        if entry.entry_model == "WAIT_FOR_PULLBACK":
            return FinalActionDecision(
                "WAIT" if grade.grade == "S" else "WATCH",
                "等待回踩",
                "等待回踩",
                "强事件已确认，但当前入场位置不满足要求。",
                False,
            )
        if entry.entry_model == "DO_NOT_CHASE":
            return FinalActionDecision(
                "WAIT",
                "不要追高",
                "不要追高",
                "价格已经过热，禁止追高买入。",
                False,
            )
        if entry.entry_model in ("BAD_RISK_REWARD", "INSUFFICIENT_RISK_REWARD"):
            action = "AVOID" if risk_reward.risk_reward_ratio < 1.5 else "WAIT"
            return FinalActionDecision(
                action,
                "等待更好盈亏比" if action == "WAIT" else "回避",
                "等待回踩" if action == "WAIT" else "继续观察",
                "风险收益比不满足买入要求。",
                False,
            )
        if entry.entry_model == "ENTRY_CONFIRMED":
            risk_reward_pass = risk_reward.risk_reward_ratio >= 2.0
            risk_pass = entry.risk_score <= 60 and valuation.risk_score <= 60
            technical_data_pass = all(
                value is not None
                for value in (
                    market.price,
                    market.ema20,
                    market.support,
                    market.resistance,
                    market.volume_ratio,
                    market.rsi,
                )
            )
            numeric_data_pass = market.price > 0 and market.volume_ratio > 0 and risk_reward.entry_price > 0
            market_pass = not reaction.is_overheated and market.trend in (
                "UP",
                "REVERSAL",
                "SIDEWAYS",
            )
            impact_pass = impact.impact_score >= 65
            if (
                data_quality_pass
                and technical_data_pass
                and numeric_data_pass
                and flow.confirmed
                and risk_reward_pass
                and risk_pass
                and market_pass
                and impact_pass
            ):
                return FinalActionDecision(
                    "BUY",
                    "BUY",
                    "允许小额首仓",
                    "入场确认、资金确认、风险收益合格。",
                    True,
                )
            return FinalActionDecision(
                "WATCH",
                "继续观察",
                "继续观察",
                "入场结构出现，但数据质量、风险、资金或盈亏比尚未全部通过。",
                False,
            )
        if entry.entry_model == "EARLY_ALPHA":
            return FinalActionDecision(
                "WATCH",
                "潜在补涨观察",
                "继续观察",
                "早期补涨线索成立，但尚未进入买入确认。",
                False,
            )
        return FinalActionDecision(
            "WAIT",
            "继续观察",
            "继续观察",
            "无法确认买入价值，默认WAIT。",
            False,
        )
