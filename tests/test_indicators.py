import pytest

from src.indicators import atr, ema, macd, pct_change, realized_volatility, rsi


def test_ema_tracks_constant_series() -> None:
    assert ema([10, 10, 10, 10], 3) == [10, 10, 10, 10]


def test_ema_rejects_invalid_period() -> None:
    with pytest.raises(ValueError):
        ema([1, 2], 0)


def test_rsi_rising_and_flat_series() -> None:
    rising = rsi(range(1, 20), 14)
    flat = rsi([5] * 20, 14)
    assert rising[-1] == 100
    assert flat[-1] == 50


def test_pct_change_and_volatility() -> None:
    assert pct_change(110, 100) == pytest.approx(10)
    assert pct_change(10, None) is None
    assert realized_volatility([100, 101, 99, 102, 101]) is not None


def test_macd_and_atr_are_available_for_long_series() -> None:
    values = list(range(1, 50))
    line, signal, histogram = macd(values)
    atr_values = atr(values, [value - 1 for value in values], values)
    assert len(line) == len(signal) == len(histogram) == len(values)
    assert histogram[-1] == pytest.approx(line[-1] - signal[-1])
    assert atr_values[-1] is not None
