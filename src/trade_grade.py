"""Trade Grade Engine: S/A/B/C opportunity grading."""

from dataclasses import dataclass

from src.entry_timing import EntryTimingDecision
from src.market_impact_engine import MarketImpactResult
from src.models import FlowData
from src.risk_reward import RiskRewardPlan


@dataclass(frozen=True)
class TradeGradeResult:
    grade: str
    reason: str
    should_enter_alert_pool: bool


class TradeGradeEngine:
    def evaluate(
        self,
        impact: MarketImpactResult,
        entry: EntryTimingDecision,
        risk_reward: RiskRewardPlan,
        flow: FlowData,
        data_quality: str = "HIGH",
    ) -> TradeGradeResult:
        high_quality = data_quality.upper() == "HIGH"
        if (
            impact.impact_score >= 80
            and entry.opportunity_score >= 80
            and entry.risk_score <= 50
            and risk_reward.risk_reward_ratio >= 2.5
            and flow.confirmed
            and high_quality
        ):
            return TradeGradeResult("S", "重大高质量机会，但不等于当前可以买。", True)
        if impact.impact_score >= 65 and entry.opportunity_score >= 65:
            return TradeGradeResult("A", "存在交易机会，但可能需要等待更好位置。", True)
        if impact.impact_score >= 30:
            return TradeGradeResult("B", "普通观察，暂不推送。", False)
        return TradeGradeResult("C", "无交易价值。", False)
