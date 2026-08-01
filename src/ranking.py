from __future__ import annotations

from dataclasses import dataclass

from .alpha_finder import AlphaCandidate
from .flow_analyzer import FlowResult
from .investment_score import InvestmentScoreResult
from .valuation_engine import ValuationResult


@dataclass(frozen=True)
class RankedItem:
    symbol: str
    score: int
    explanation: str


@dataclass(frozen=True)
class RankingReport:
    comprehensive: tuple[RankedItem, ...]
    alpha: tuple[RankedItem, ...]
    flow: tuple[RankedItem, ...]
    valuation: tuple[RankedItem, ...]
    risk: tuple[RankedItem, ...]
    insufficient_data: tuple[RankedItem, ...]


class RankingEngine:
    def build(
        self,
        scores: dict[str, InvestmentScoreResult],
        alpha_candidates: list[AlphaCandidate],
        flows: dict[str, FlowResult],
        valuations: dict[str, ValuationResult],
    ) -> RankingReport:
        comprehensive = _rank(
            [
                RankedItem(
                    symbol=result.symbol,
                    score=result.investment_score,
                    explanation=(
                        f"机会{result.opportunity_score}/风险{result.risk_score}；"
                        f"{result.conclusion}"
                    ),
                )
                for result in scores.values()
            ],
            10,
        )
        alpha_by_symbol: dict[str, AlphaCandidate] = {}
        for candidate in alpha_candidates:
            if candidate.symbol not in alpha_by_symbol or candidate.alpha_score > alpha_by_symbol[candidate.symbol].alpha_score:
                alpha_by_symbol[candidate.symbol] = candidate
        alpha = _rank(
            [
                RankedItem(
                    candidate.symbol,
                    candidate.alpha_score,
                    f"{candidate.event_title}；{candidate.reasoning[0]}；建议{candidate.action}",
                )
                for candidate in alpha_by_symbol.values()
            ],
            5,
        )
        flow = _rank(
            [RankedItem(symbol, result.flow_score, f"{result.flow_direction}；{result.likely_driver}") for symbol, result in flows.items()],
            5,
        )
        valuation = _rank(
            [RankedItem(symbol, result.valuation_score, f"{result.valuation_label}；{result.growth_adjusted_value}") for symbol, result in valuations.items()],
            5,
        )
        risk = _rank(
            [RankedItem(result.symbol, result.risk_score, result.conclusion) for result in scores.values()],
            5,
        )
        insufficient = _rank(
            [
                RankedItem(result.symbol, 100 - result.data_quality_score, f"数据质量{result.data_quality_score}/100")
                for result in scores.values()
                if result.data_quality_score < 60
            ],
            100,
        )
        return RankingReport(comprehensive, alpha, flow, valuation, risk, insufficient)


def _rank(items: list[RankedItem], limit: int) -> tuple[RankedItem, ...]:
    return tuple(sorted(items, key=lambda item: (-item.score, item.symbol))[:limit])
