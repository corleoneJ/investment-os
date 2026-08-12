"""Dry-run scenarios for Investment OS V5.

This module does not send Feishu messages. It only prints the filter outcome
for deterministic simulated cases.
"""

from datetime import datetime, timedelta, timezone

from src.models import (
    Event,
    FlowData,
    MarketData,
    PeerReaction,
    TradeContext,
    ValuationData,
)
from src.trade_filter_layer import TradeFilterLayer

NOW = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)


def _event(event_id, symbol, title, **kwargs):
    values = {
        "event_id": event_id,
        "symbol": symbol,
        "title": title,
        "source": "Company PR",
        "published_at": NOW - timedelta(hours=2),
        "revenue_impact": 20,
        "profit_impact": 20,
        "guidance_impact": 25,
        "supply_demand_impact": 20,
        "valuation_impact": 10,
        "competition_impact": 10,
        "industry_impact": 25,
        "capital_flow_impact": 15,
        "surprise_level": 25,
        "source_quality_hint": "high",
    }
    values.update(kwargs)
    return Event(**values)


def _market(**kwargs):
    values = {
        "price": 100.0,
        "previous_close": 98.0,
        "post_1d_change_pct": 3.0,
        "post_5d_change_pct": 4.0,
        "volume_ratio": 2.2,
        "vwap_deviation_pct": 1.2,
        "atr_deviation": 0.8,
        "rsi": 58.0,
        "ema20": 98.0,
        "ema50": 94.0,
        "atr": 3.0,
        "support": 96.0,
        "resistance": 112.0,
        "recent_low": 95.0,
        "pullback_confirmed": True,
        "trend": "UP",
    }
    values.update(kwargs)
    return MarketData(**values)


def _flow(**kwargs):
    values = {
        "fund_flow_score": 75,
        "volume_confirmed": True,
        "money_flow_confirmed": True,
        "vwap_confirmed": True,
        "flow_turning_positive": True,
    }
    values.update(kwargs)
    return FlowData(**values)


def _valuation(**kwargs):
    values = {
        "opportunity_score": 82,
        "risk_score": 45,
        "valuation_support": True,
        "target_upside_pct": 25.0,
        "fundamental_intact": True,
    }
    values.update(kwargs)
    return ValuationData(**values)


def scenarios():
    return {
        "garbage_news": TradeContext(
            _event(
                "dry-noise",
                "ABC",
                "Ordinary collaboration and product update",
                source="Unknown Blog",
                published_at=NOW - timedelta(days=5),
                revenue_impact=1,
                profit_impact=0,
                guidance_impact=0,
                supply_demand_impact=0,
                industry_impact=0,
                source_quality_hint="low",
                confirmed=False,
            ),
            _market(),
        ),
        "s_wait_pullback": TradeContext(
            _event("dry-s-wait", "SNDK", "AI storage demand catalyst lifts guidance"),
            _market(pullback_confirmed=False, broke_resistance=False),
            _flow(),
            _valuation(opportunity_score=86, risk_score=42, target_upside_pct=30.0),
        ),
        "s_entry_confirmed": TradeContext(
            _event("dry-s-buy", "SNDK", "Earnings beat and AI storage demand lifts guidance"),
            _market(pullback_confirmed=True),
            _flow(),
            _valuation(opportunity_score=86, risk_score=42, target_upside_pct=30.0),
        ),
        "s_do_not_chase": TradeContext(
            _event("dry-hot", "SNDK", "Earnings beat and guidance raise"),
            _market(post_1d_change_pct=18, post_5d_change_pct=28, rsi=82, vwap_deviation_pct=9),
            _flow(),
            _valuation(opportunity_score=86, risk_score=42, target_upside_pct=30.0),
        ),
        "a_wait_pullback": TradeContext(
            _event(
                "dry-a-wait",
                "SNDK",
                "AI storage demand catalyst supports earnings outlook",
                revenue_impact=14,
                profit_impact=14,
                guidance_impact=18,
                supply_demand_impact=16,
                industry_impact=18,
                surprise_level=15,
            ),
            _market(pullback_confirmed=False, broke_resistance=False),
            _flow(),
            _valuation(opportunity_score=68, risk_score=48),
            (PeerReaction("NVDA", 8.0, 90), PeerReaction("MU", 6.0, 95)),
        ),
        "a_entry_confirmed": TradeContext(
            _event(
                "dry-a-buy",
                "SNDK",
                "AI storage demand catalyst supports earnings outlook",
                revenue_impact=14,
                profit_impact=14,
                guidance_impact=18,
                supply_demand_impact=16,
                industry_impact=18,
                surprise_level=15,
            ),
            _market(pullback_confirmed=True),
            _flow(),
            _valuation(opportunity_score=72, risk_score=48, target_upside_pct=24.0),
        ),
    }


def main():
    layer = TradeFilterLayer()
    print("grade | entry_model | final_action | send")
    for context in scenarios().values():
        result = layer.evaluate(context, NOW)
        print(
            "{} | {} | {} | {}".format(
                result.grade.grade,
                result.entry.entry_model,
                result.final_action.final_action,
                result.should_send_feishu,
            )
        )


if __name__ == "__main__":
    main()
