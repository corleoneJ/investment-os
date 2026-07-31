from __future__ import annotations

from dataclasses import dataclass

from .market_data import MarketSnapshot
from .news import NewsItem


@dataclass(frozen=True)
class Scores:
    trend: int
    opportunity: int
    risk: int


def calculate_scores(snapshot: MarketSnapshot, news: list[NewsItem]) -> Scores:
    if snapshot.error or not snapshot.price:
        return Scores(0, 0, 100)
    rsi = snapshot.rsi or 50
    change_1h = snapshot.changes.get("1h") or 0
    change_24h = snapshot.changes.get("24h") or 0
    negative_news = any(item.is_major and item.is_negative for item in news)

    trend = 0
    trend += 20 if snapshot.ema20 and snapshot.price > snapshot.ema20 else 0
    trend += 25 if snapshot.ema20 and snapshot.ema60 and snapshot.ema20 > snapshot.ema60 else 0
    trend += 15 if 50 <= rsi <= 70 else (8 if 40 <= rsi < 50 else 0)
    trend += 10 if change_1h > 0 else 0
    trend += 15 if snapshot.volume_ratio and snapshot.volume_ratio >= 1.5 else 0
    trend += 15 if snapshot.breakout else 0

    medium_up = bool(snapshot.ema20 and snapshot.ema60 and snapshot.ema20 > snapshot.ema60)
    ema_distance = abs(snapshot.price / snapshot.ema20 - 1) * 100 if snapshot.ema20 else 999
    rsi_recovering = bool(
        snapshot.rsi is not None
        and snapshot.rsi_previous is not None
        and snapshot.rsi > snapshot.rsi_previous
        and snapshot.rsi <= 50
    )
    opportunity = (
        (30 if medium_up else 0)
        + (25 if ema_distance <= 1 else 0)
        + (25 if rsi_recovering else 0)
        + (20 if not negative_news else 0)
    )

    risk = 0
    risk += 25 if snapshot.ema20 and snapshot.price < snapshot.ema20 else 0
    risk += 25 if snapshot.ema20 and snapshot.ema60 and snapshot.ema20 < snapshot.ema60 else 0
    risk += 20 if rsi < 40 else 0
    risk += 15 if change_1h <= -3 or change_24h <= -7 else 0
    risk += 15 if negative_news else 0
    return Scores(min(trend, 100), min(opportunity, 100), min(risk, 100))
