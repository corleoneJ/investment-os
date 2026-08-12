"""Price Reaction Analyzer: decide whether the market already reacted."""

from dataclasses import dataclass

from src.models import MarketData


@dataclass(frozen=True)
class PriceReactionResult:
    priced_in_score: int
    is_overheated: bool
    reaction_summary: str
    do_not_chase: bool


class PriceReactionAnalyzer:
    def evaluate(self, market: MarketData) -> PriceReactionResult:
        score = 0
        if market.pre_event_change_pct >= 8:
            score += 25
        if market.post_1d_change_pct >= 10:
            score += 25
        if market.post_5d_change_pct >= 20:
            score += 25
        if market.gap_pct >= 6:
            score += 15
        if market.vwap_deviation_pct >= 5:
            score += 15
        if market.atr_deviation >= 2.5:
            score += 15
        if market.rsi >= 75:
            score += 20
        if market.broke_resistance and market.volume_ratio >= 1.8:
            score = max(0, score - 10)
        score = max(0, min(100, score))
        overheated = (
            score >= 70
            or market.rsi >= 78
            or market.vwap_deviation_pct >= 8
            or market.atr_deviation >= 3
        )
        summary = (
            "价格已经明显反应，禁止追高"
            if overheated
            else "价格反应仍可继续评估"
        )
        return PriceReactionResult(score, overheated, summary, overheated)

