from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import pairwise
from statistics import pstdev


def ema(values: Iterable[float], period: int) -> list[float]:
    data = [float(v) for v in values]
    if not data:
        return []
    if period <= 0:
        raise ValueError("period 必须大于 0")
    alpha = 2 / (period + 1)
    result = [data[0]]
    for value in data[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def rsi(values: Iterable[float], period: int = 14) -> list[float | None]:
    data = [float(v) for v in values]
    if period <= 0:
        raise ValueError("period 必须大于 0")
    result: list[float | None] = [None] * len(data)
    if len(data) <= period:
        return result
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in pairwise(data):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = _rsi_value(avg_gain, avg_loss)
    for index in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        result[index + 1] = _rsi_value(avg_gain, avg_loss)
    return result


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def realized_volatility(values: Iterable[float], periods: int = 20) -> float | None:
    data = [float(v) for v in values if v is not None and v > 0]
    if len(data) < 3:
        return None
    window = data[-(periods + 1) :]
    returns = [math.log(current / previous) for previous, current in pairwise(window)]
    if len(returns) < 2:
        return None
    # 5 分钟收益率折算为 1 小时波动率，仅用于同类信号比较。
    return pstdev(returns) * math.sqrt(12) * 100


def pct_change(current: float, previous: float | None) -> float | None:
    if previous in (None, 0):
        return None
    return (current / previous - 1) * 100
