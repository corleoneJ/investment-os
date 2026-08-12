"""Market Impact Engine for judging whether an event can move price."""

from dataclasses import dataclass

from src.models import Event


@dataclass(frozen=True)
class MarketImpactResult:
    impact_score: int
    impact_direction: str
    impact_duration: str
    market_priced_in: bool
    confidence: int
    reasoning: str


class MarketImpactEngine:
    def evaluate(self, event: Event) -> MarketImpactResult:
        components = {
            "收入影响": event.revenue_impact,
            "利润影响": event.profit_impact,
            "指引影响": event.guidance_impact,
            "供需影响": event.supply_demand_impact,
            "估值影响": event.valuation_impact,
            "竞争格局": event.competition_impact,
            "行业传导": event.industry_impact,
            "政策影响": event.policy_impact,
            "资金影响": event.capital_flow_impact,
            "超预期": event.surprise_level,
        }
        score = max(0, min(100, int(round(sum(components.values()) / 1.8))))
        if event.previously_priced:
            score = max(0, score - 15)
        if not event.confirmed:
            score = max(0, score - 20)

        positives = sum(value for value in components.values() if value > 0)
        negatives = abs(sum(value for value in components.values() if value < 0))
        if positives > negatives * 1.3:
            direction = "POSITIVE"
        elif negatives > positives * 1.3:
            direction = "NEGATIVE"
        elif positives or negatives:
            direction = "MIXED"
        else:
            direction = "UNCLEAR"

        if score >= 80:
            duration = "multi_day"
        elif score >= 60:
            duration = "1_to_5_days"
        elif score >= 30:
            duration = "intraday_to_1_day"
        else:
            duration = "none"

        confidence = 80
        if not event.confirmed:
            confidence -= 30
        if event.published_at is None:
            confidence -= 20
        if event.source_quality_hint == "low":
            confidence -= 20
        confidence = max(0, min(100, confidence))

        top = sorted(components.items(), key=lambda item: abs(item[1]), reverse=True)[:3]
        reasoning = "主要影响：{}".format(
            "，".join("{}{:+d}".format(name, value) for name, value in top)
        )
        return MarketImpactResult(
            score,
            direction,
            duration,
            event.previously_priced,
            confidence,
            reasoning,
        )

