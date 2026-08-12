"""Factories for V5 tests."""

from datetime import datetime, timedelta, timezone

from src.models import (
    Event,
    FlowData,
    MarketData,
    PeerReaction,
    TradeContext,
    ValuationData,
)

NOW = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)


def strong_event(symbol="SNDK"):
    return Event(
        event_id="evt-strong-{}".format(symbol),
        symbol=symbol,
        title="Earnings beat and AI storage demand catalyst lifts guidance",
        source="Company PR",
        published_at=NOW - timedelta(hours=2),
        category="earnings",
        revenue_impact=20,
        profit_impact=20,
        guidance_impact=25,
        supply_demand_impact=20,
        valuation_impact=10,
        competition_impact=10,
        industry_impact=25,
        capital_flow_impact=15,
        surprise_level=25,
        source_quality_hint="high",
    )


def weak_event():
    return Event(
        event_id="evt-noise",
        symbol="ABC",
        title="Company announces ordinary collaboration and product update",
        source="Unknown Blog",
        published_at=NOW - timedelta(days=5),
        category="partnership",
        source_quality_hint="low",
        revenue_impact=2,
        profit_impact=0,
        confirmed=False,
    )


def market(**kwargs):
    values = {
        "price": 100.0,
        "previous_close": 98.0,
        "pre_event_change_pct": 1.0,
        "post_1h_change_pct": 1.5,
        "post_4h_change_pct": 2.0,
        "post_1d_change_pct": 3.0,
        "post_5d_change_pct": 4.0,
        "volume_ratio": 2.2,
        "gap_pct": 1.0,
        "vwap_deviation_pct": 1.2,
        "atr_deviation": 0.8,
        "rsi": 58.0,
        "ema20": 98.0,
        "ema50": 94.0,
        "atr": 3.0,
        "support": 96.0,
        "resistance": 112.0,
        "recent_high": 111.0,
        "recent_low": 95.0,
        "broke_resistance": False,
        "pullback_confirmed": True,
        "reversal_structure": False,
        "trend": "UP",
    }
    values.update(kwargs)
    return MarketData(**values)


def flow(**kwargs):
    values = {
        "fund_flow_score": 75,
        "volume_confirmed": True,
        "money_flow_confirmed": True,
        "vwap_confirmed": True,
        "flow_turning_positive": True,
    }
    values.update(kwargs)
    return FlowData(**values)


def valuation(**kwargs):
    values = {
        "opportunity_score": 82,
        "risk_score": 45,
        "valuation_support": True,
        "target_upside_pct": 25.0,
        "downside_pct": 6.0,
        "fundamental_intact": True,
    }
    values.update(kwargs)
    return ValuationData(**values)


def context(**kwargs):
    values = {
        "event": strong_event(),
        "market": market(),
        "flow": flow(),
        "valuation": valuation(),
        "peer_reactions": (),
        "data_quality": "HIGH",
    }
    values.update(kwargs)
    return TradeContext(**values)


def sndk_early_context():
    return context(
        event=strong_event("SNDK"),
        market=market(post_1d_change_pct=1.0, pullback_confirmed=False, broke_resistance=False),
        flow=flow(volume_confirmed=True, money_flow_confirmed=True, flow_turning_positive=True),
        valuation=valuation(opportunity_score=68, risk_score=48, valuation_support=True),
        peer_reactions=(
            PeerReaction("NVDA", 8.0, 90),
            PeerReaction("MU", 6.0, 95),
        ),
    )

