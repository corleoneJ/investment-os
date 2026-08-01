from __future__ import annotations

from datetime import datetime, timezone

from src.data_quality import DataQualityResult, ProviderState, provider_status
from src.flow_analyzer import FlowResult
from src.market_data import MarketSnapshot
from src.valuation_engine import ValuationResult

UTC = timezone.utc


def snapshot(symbol: str = "NVDA", change: float = 1, volume: float = 1.6, weak: bool = False) -> MarketSnapshot:
    price = 90 if weak else 110
    return MarketSnapshot(
        asset=symbol, asset_type="stock", data_time=datetime.now(UTC), price=price,
        changes={"5m": 0.1, "15m": 0.2, "1h": 0.4, "24h": change}, volume_ratio=volume,
        ema20=100, ema60=95, ema200=80, rsi=55 if not weak else 35, rsi_previous=50,
        macd=2 if not weak else -2, macd_signal=1, macd_histogram=1, atr=2, atr_pct=2,
        volatility=20, breakout=False, breakdown=weak, pullback=False, volume_state="放量",
        recent_high=115, recent_low=90, fresh=True, source="测试行情", error=None,
        obv_trend="上升" if not weak else "下降", vwap=105, dollar_volume_proxy=1_000_000,
        provider=provider_status(status=ProviderState.HEALTHY, source="测试行情", source_url="https://example.test", data_timestamp=datetime.now(UTC), confidence=90),
    )


def flow(symbol: str = "NVDA", score: int = 75, direction: str = "增量资金确认") -> FlowResult:
    return FlowResult(
        symbol=symbol, flow_score=score, flow_direction=direction, volume_confirmation="放量",
        relative_volume=1.6, obv_trend="上升", vwap_position="价格在VWAP上方",
        etf_flow="数据暂不可用", institutional_change="数据暂不可用（13F仅代表上个披露期）",
        insider_activity="数据暂不可用", short_interest="数据暂不可用", options_signal="数据暂不可用",
        likely_driver="代理指标同向", confidence=70, source_times={"行情": datetime.now(UTC).isoformat()},
        warnings=("代理推断",), providers=(),
    )


def valuation(symbol: str = "NVDA", score: int = 60, growth: float = 20, label: str = "合理") -> ValuationResult:
    quality = DataQualityResult(80, 75, (), (), ())
    return ValuationResult(
        symbol=symbol, valuation_type="成长/股票估值",
        current_metrics={"revenue_growth_pct": growth, "gross_margin_pct": 60, "operating_margin_pct": 30, "roe_pct": 35, "fcf_yield_pct": 3, "ps": 10, "pe_ttm": 35, "prior_gross_margin_pct": 50},
        historical_percentiles={"pe": None}, peer_comparison="测试", growth_adjusted_value="测试",
        cycle_adjustment="已多指标调整", valuation_score=score, valuation_label=label,
        confidence=75, data_time=datetime.now(UTC), missing_fields=(), warnings=(), data_quality=quality,
    )
