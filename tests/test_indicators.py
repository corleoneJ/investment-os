import pytest

from src.indicators import ema, pct_change, realized_volatility, rsi


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
