from datetime import datetime, timezone

from src.market_data import MarketSnapshot
from src.scoring import calculate_scores


def snapshot(**overrides) -> MarketSnapshot:
    values = {
        "asset": "NVDA",
        "asset_type": "stock",
        "data_time": datetime.now(timezone.utc),
        "price": 105,
        "changes": {"5m": 0.5, "15m": 1.0, "1h": 2.0, "24h": 4.0},
        "volume_ratio": 1.8,
        "ema20": 100,
        "ema60": 95,
        "rsi": 60,
        "rsi_previous": 58,
        "volatility": 2,
        "breakout": True,
        "breakdown": False,
        "recent_high": 104,
        "recent_low": 90,
        "fresh": True,
        "source": "测试",
        "error": None,
    }
    values.update(overrides)
    return MarketSnapshot(**values)


def test_strong_trend_scores_at_least_70() -> None:
    scores = calculate_scores(snapshot(), [])
    assert scores.trend >= 70
    assert scores.risk == 0


def test_pullback_opportunity_requires_rsi_recovery() -> None:
    item = snapshot(price=100.5, rsi=45, rsi_previous=40, breakout=False, volume_ratio=1)
    scores = calculate_scores(item, [])
    assert scores.opportunity >= 70


def test_missing_data_is_maximum_risk() -> None:
    scores = calculate_scores(snapshot(price=0, error="不可用"), [])
    assert scores.risk == 100
