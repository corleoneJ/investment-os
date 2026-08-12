"""Entry Timing Engine: strict BUY gate for Investment OS V5."""

from dataclasses import dataclass
from typing import List

from src.market_impact_engine import MarketImpactResult
from src.models import FlowData, MarketData, ValuationData
from src.price_reaction import PriceReactionResult
from src.risk_reward import RiskRewardPlan


@dataclass(frozen=True)
class EntryTimingDecision:
    status: str
    entry_model: str
    opportunity_score: int
    risk_score: int
    core_conclusion: str
    execution_advice: str
    reasons: List[str]


class EntryTimingEngine:
    def evaluate(
        self,
        impact: MarketImpactResult,
        reaction: PriceReactionResult,
        market: MarketData,
        flow: FlowData,
        valuation: ValuationData,
        risk_reward: RiskRewardPlan,
    ) -> EntryTimingDecision:
        reasons = []
        opportunity = valuation.opportunity_score
        risk = valuation.risk_score

        if impact.impact_score < 30:
            return self._decision(
                "AVOID",
                "NO_TRADE_VALUE",
                opportunity,
                max(risk, 65),
                "事件影响不足，没有交易价值。",
                "继续观察",
                ["Impact Score < 30"],
            )

        if reaction.do_not_chase:
            return self._decision(
                "WAIT",
                "DO_NOT_CHASE",
                opportunity,
                risk,
                "事件可能重要，但价格已经过热，现在不追高。",
                "不要追高",
                ["priced_in_score过高", "RSI/VWAP/ATR偏离过热"],
            )

        if risk_reward.risk_reward_ratio < 1.5:
            return self._decision(
                "AVOID",
                "BAD_RISK_REWARD",
                opportunity,
                max(risk, 70),
                "收益空间不足，风险收益不合格。",
                "继续观察",
                ["R/R < 1.5"],
            )
        if risk_reward.risk_reward_ratio < 2.0:
            return self._decision(
                "WAIT",
                "INSUFFICIENT_RISK_REWARD",
                opportunity,
                max(risk, 60),
                "盈亏比尚未达到BUY门槛。",
                "等待回踩",
                ["R/R < 2.0"],
            )

        technical_confirmed = (
            market.pullback_confirmed
            or (market.broke_resistance and market.volume_ratio >= 1.8)
            or market.reversal_structure
        )
        if not flow.confirmed:
            reasons.append("资金未确认")
        if not technical_confirmed:
            reasons.append("技术位置未确认")

        entry_confirmed = (
            impact.impact_score >= 65
            and opportunity >= 70
            and risk <= 60
            and flow.confirmed
            and technical_confirmed
            and not reaction.is_overheated
            and risk_reward.risk_reward_ratio >= 2.0
        )
        if entry_confirmed:
            return self._decision(
                "READY",
                "ENTRY_CONFIRMED",
                opportunity,
                risk,
                "入场结构已经确认，等待最终动作解析器做BUY Gate校验。",
                "允许小额首仓",
                reasons or ["入场确认"],
            )

        if impact.impact_score >= 60 and opportunity >= 60:
            return self._decision(
                "WATCH",
                "WAIT_FOR_PULLBACK" if not technical_confirmed else "WATCHLIST",
                opportunity,
                risk,
                "事件有交易价值，但还缺少买入确认。",
                "等待回踩" if not technical_confirmed else "继续观察",
                reasons or ["BUY条件未全部满足"],
            )
        return self._decision(
            "WAIT",
            "DEFAULT_WAIT",
            opportunity,
            risk,
            "无法确认买入价值，默认WAIT。",
            "继续观察",
            reasons or ["信息不足"],
        )

    @staticmethod
    def _decision(status, model, opportunity, risk, conclusion, advice, reasons):
        return EntryTimingDecision(
            status,
            model,
            max(0, min(100, int(opportunity))),
            max(0, min(100, int(risk))),
            conclusion,
            advice,
            list(reasons),
        )
