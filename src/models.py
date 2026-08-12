"""Shared data contracts for Investment OS V5."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence


@dataclass(frozen=True)
class Event:
    event_id: str
    symbol: str
    title: str
    source: str
    published_at: Optional[datetime]
    category: str = "general"
    summary: str = ""
    tags: Sequence[str] = field(default_factory=tuple)
    revenue_impact: int = 0
    profit_impact: int = 0
    guidance_impact: int = 0
    supply_demand_impact: int = 0
    valuation_impact: int = 0
    competition_impact: int = 0
    industry_impact: int = 0
    policy_impact: int = 0
    capital_flow_impact: int = 0
    surprise_level: int = 0
    confirmed: bool = True
    duplicate_of: Optional[str] = None
    previously_priced: bool = False
    source_quality_hint: str = "normal"


@dataclass(frozen=True)
class MarketData:
    price: float
    previous_close: float
    pre_event_change_pct: float = 0.0
    post_1h_change_pct: float = 0.0
    post_4h_change_pct: float = 0.0
    post_1d_change_pct: float = 0.0
    post_5d_change_pct: float = 0.0
    volume_ratio: float = 1.0
    gap_pct: float = 0.0
    vwap_deviation_pct: float = 0.0
    atr_deviation: float = 0.0
    rsi: float = 50.0
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    atr: Optional[float] = None
    support: Optional[float] = None
    resistance: Optional[float] = None
    recent_high: Optional[float] = None
    recent_low: Optional[float] = None
    broke_resistance: bool = False
    pullback_confirmed: bool = False
    reversal_structure: bool = False
    trend: str = "SIDEWAYS"


@dataclass(frozen=True)
class FlowData:
    fund_flow_score: int = 50
    volume_confirmed: bool = False
    money_flow_confirmed: bool = False
    vwap_confirmed: bool = False
    flow_turning_positive: bool = False

    @property
    def confirmed(self) -> bool:
        return (
            self.fund_flow_score >= 60
            and self.volume_confirmed
            and self.money_flow_confirmed
        )


@dataclass(frozen=True)
class ValuationData:
    opportunity_score: int = 50
    risk_score: int = 50
    valuation_support: bool = False
    target_upside_pct: float = 0.0
    downside_pct: float = 0.0
    fundamental_intact: bool = True


@dataclass(frozen=True)
class PeerReaction:
    symbol: str
    reaction_pct: float
    relevance_score: int = 50


@dataclass(frozen=True)
class TradeContext:
    event: Event
    market: MarketData
    flow: FlowData = field(default_factory=FlowData)
    valuation: ValuationData = field(default_factory=ValuationData)
    peer_reactions: Sequence[PeerReaction] = field(default_factory=tuple)
    data_quality: str = "HIGH"
    previous_grade: Optional[str] = None
    previous_decision: Optional[str] = None


@dataclass(frozen=True)
class ScoringBreakdown:
    contributions: Dict[str, int]

    @property
    def total(self) -> int:
        return max(0, min(100, sum(self.contributions.values())))

    def lines(self) -> List[str]:
        return [
            "{} {:+d}".format(name, value)
            for name, value in self.contributions.items()
            if value != 0
        ]

