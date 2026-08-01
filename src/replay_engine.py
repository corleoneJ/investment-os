from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .indicators import ema, rsi


@dataclass(frozen=True)
class HistoricalBar:
    date: date
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class ReplaySignal:
    symbol: str
    signal_date: date
    used_until: date
    score: int
    opportunity_score: int
    risk_score: int
    data_quality: int
    reasons: tuple[str, ...]


class ReplayEngine:
    """只允许使用信号日及以前的数据计算信号，未来窗口仅用于事后评价。"""

    def generate_signal(
        self, symbol: str, bars: list[HistoricalBar], signal_index: int
    ) -> ReplaySignal:
        if signal_index < 60 or signal_index >= len(bars):
            raise ValueError("信号位置必须至少包含60个历史交易日且位于数据范围内")
        history = bars[: signal_index + 1]
        closes = [bar.close for bar in history]
        volumes = [bar.volume for bar in history]
        ema20 = ema(closes, 20)[-1]
        ema60 = ema(closes, 60)[-1]
        rsi_value = next((value for value in reversed(rsi(closes, 14)) if value is not None), 50)
        average_volume = sum(volumes[-21:-1]) / 20 if sum(volumes[-21:-1]) else 0
        relative_volume = volumes[-1] / average_volume if average_volume else 0
        momentum20 = (closes[-1] / closes[-21] - 1) * 100
        opportunity = 40
        reasons: list[str] = []
        if closes[-1] > ema20 > ema60:
            opportunity += 25
            reasons.append("信号日前趋势向上 +25")
        if relative_volume >= 1.5:
            opportunity += 15
            reasons.append("信号日放量 +15")
        if 45 <= rsi_value <= 68:
            opportunity += 10
            reasons.append("RSI位置适中 +10")
        risk = 25
        if rsi_value >= 70:
            risk += 30
            reasons.append("RSI过热，风险 +30")
        if momentum20 >= 20:
            risk += 25
            reasons.append("20日涨幅过大，风险 +25")
        quality = 85
        score = round(opportunity * 0.65 + (100 - risk) * 0.35)
        return ReplaySignal(
            symbol=symbol,
            signal_date=history[-1].date,
            used_until=history[-1].date,
            score=max(0, min(100, score)),
            opportunity_score=max(0, min(100, opportunity)),
            risk_score=max(0, min(100, risk)),
            data_quality=quality,
            reasons=tuple(reasons) or ("历史信号未获得额外加分",),
        )
