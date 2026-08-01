from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .data_quality import ProviderState, ProviderStatus, provider_status
from .indicators import atr, ema, macd, pct_change, realized_volatility, rsi

LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


@dataclass(frozen=True)
class Candle:
    time: datetime
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MarketSnapshot:
    asset: str
    asset_type: str
    data_time: datetime
    price: float
    changes: dict[str, float | None]
    volume_ratio: float | None
    ema20: float | None
    ema60: float | None
    ema200: float | None
    rsi: float | None
    rsi_previous: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    atr: float | None
    atr_pct: float | None
    volatility: float | None
    breakout: bool
    breakdown: bool
    pullback: bool
    volume_state: str
    recent_high: float | None
    recent_low: float | None
    fresh: bool
    source: str
    error: str | None = None
    obv_trend: str | None = None
    vwap: float | None = None
    dollar_volume_proxy: float | None = None
    provider: ProviderStatus | None = None


def build_session(retries: int = 2) -> requests.Session:
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "InvestmentOS/3.0 (GitHub Actions decision system)"})
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=12, pool_maxsize=12))
    return session


class MarketDataClient:
    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self.session = build_session()

    def fetch_all(self, assets: list[dict[str, Any]]) -> dict[str, MarketSnapshot]:
        results: dict[str, MarketSnapshot] = {}
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(assets)))) as executor:
            futures = {executor.submit(self.fetch, item): item for item in assets}
            for future in as_completed(futures):
                item = futures[future]
                symbol = item["symbol"]
                try:
                    results[symbol] = future.result()
                except Exception as exc:  # noqa: BLE001  # 每个数据源/资产独立降级
                    LOGGER.warning("行情获取失败：%s（%s）", symbol, type(exc).__name__)
                    results[symbol] = unavailable_snapshot(symbol, item.get("type", "stock"), str(exc))
        return results

    def fetch(self, asset: dict[str, Any]) -> MarketSnapshot:
        if asset.get("type") == "crypto":
            candles = self._fetch_binance(asset.get("provider_symbol", "BTCUSDT"))
            source = "Binance 公共现货 API（BTCUSDT 作为 BTC-USD 近似）"
        else:
            candles = self._fetch_yahoo(asset.get("provider_symbol", asset["symbol"]))
            source = "Yahoo Finance 公共图表接口"
        return make_snapshot(asset["symbol"], asset.get("type", "stock"), candles, source)

    def _fetch_binance(self, symbol: str) -> list[Candle]:
        response = self.session.get(
            "https://data-api.binance.vision/api/v3/klines",
            params={"symbol": symbol, "interval": "5m", "limit": 400},
            timeout=self.timeout,
        )
        response.raise_for_status()
        rows = response.json()
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        candles = [
            Candle(
                time=datetime.fromtimestamp(row[0] / 1000, UTC),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
            if int(row[6]) < now_ms  # 排除尚未收盘的 5 分钟 K 线
        ]
        if len(candles) < 61:
            raise ValueError("BTC K 线数量不足")
        return candles

    def _fetch_yahoo(self, symbol: str) -> list[Candle]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
        response = self.session.get(
            url,
            params={"range": "5d", "interval": "5m", "includePrePost": "true", "events": "div,splits"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        chart = response.json().get("chart", {})
        if chart.get("error"):
            raise ValueError(chart["error"].get("description", "Yahoo 返回错误"))
        result = (chart.get("result") or [None])[0]
        if not result:
            raise ValueError("Yahoo 未返回行情")
        timestamps = result.get("timestamp") or []
        quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        candles: list[Candle] = []
        for index, timestamp in enumerate(timestamps):
            try:
                close = quote_data["close"][index]
                high = quote_data["high"][index]
                low = quote_data["low"][index]
                volume = quote_data["volume"][index]
            except (IndexError, KeyError):
                continue
            if close is None or high is None or low is None:
                continue
            candles.append(
                Candle(
                    time=datetime.fromtimestamp(timestamp, UTC),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=float(volume or 0),
                )
            )
        if len(candles) < 61:
            raise ValueError("美股 K 线数量不足")
        return candles


def make_snapshot(asset: str, asset_type: str, candles: list[Candle], source: str) -> MarketSnapshot:
    closes = [c.close for c in candles]
    ema20_values = ema(closes, 20)
    ema60_values = ema(closes, 60)
    ema200_values = ema(closes, 200)
    rsi_values = rsi(closes, 14)
    macd_values, macd_signal_values, macd_histogram_values = macd(closes)
    atr_values = atr(
        [candle.high for candle in candles],
        [candle.low for candle in candles],
        closes,
    )
    latest = candles[-1]
    prior = candles[-21:-1]
    average_volume = sum(c.volume for c in prior) / len(prior) if prior else 0
    volume_ratio = latest.volume / average_volume if average_volume > 0 else None
    recent_high = max((c.high for c in prior), default=None)
    recent_low = min((c.low for c in prior), default=None)
    latest_atr = next((value for value in reversed(atr_values) if value is not None), None)
    volume_state = (
        "放量"
        if volume_ratio is not None and volume_ratio >= 1.5
        else "缩量"
        if volume_ratio is not None and volume_ratio <= 0.6
        else "正常"
    )
    pullback = bool(
        ema20_values[-1] > ema60_values[-1]
        and abs(latest.close / ema20_values[-1] - 1) <= 0.01
    )
    recent_candles = candles[-20:]
    total_volume = sum(candle.volume for candle in recent_candles)
    vwap_value = (
        sum(
            ((candle.high + candle.low + candle.close) / 3) * candle.volume
            for candle in recent_candles
        ) / total_volume
        if total_volume > 0
        else None
    )
    obv_values = [0.0]
    for previous, current in zip(candles[-21:-1], candles[-20:]):
        direction = 1 if current.close > previous.close else -1 if current.close < previous.close else 0
        obv_values.append(obv_values[-1] + direction * current.volume)
    obv_change = obv_values[-1] - obv_values[max(0, len(obv_values) - 6)]
    obv_trend = "上升" if obv_change > 0 else "下降" if obv_change < 0 else "横盘"
    now = datetime.now(UTC)
    freshness_limit = timedelta(minutes=15 if asset_type == "crypto" else 45)
    return MarketSnapshot(
        asset=asset,
        asset_type=asset_type,
        data_time=latest.time,
        price=latest.close,
        changes={
            "5m": change_at(candles, timedelta(minutes=5)),
            "15m": change_at(candles, timedelta(minutes=15)),
            "1h": change_at(candles, timedelta(hours=1)),
            "24h": change_at(candles, timedelta(hours=24)),
        },
        volume_ratio=volume_ratio,
        ema20=ema20_values[-1],
        ema60=ema60_values[-1],
        ema200=ema200_values[-1],
        rsi=next((value for value in reversed(rsi_values) if value is not None), None),
        rsi_previous=next((value for value in reversed(rsi_values[:-1]) if value is not None), None),
        macd=macd_values[-1],
        macd_signal=macd_signal_values[-1],
        macd_histogram=macd_histogram_values[-1],
        atr=latest_atr,
        atr_pct=latest_atr / latest.close * 100 if latest_atr and latest.close else None,
        volatility=realized_volatility(closes),
        breakout=recent_high is not None and latest.close > recent_high,
        breakdown=recent_low is not None and latest.close < recent_low,
        pullback=pullback,
        volume_state=volume_state,
        recent_high=recent_high,
        recent_low=recent_low,
        fresh=now - latest.time <= freshness_limit,
        source=source,
        obv_trend=obv_trend,
        vwap=vwap_value,
        dollar_volume_proxy=latest.close * latest.volume,
        provider=provider_status(
            status=ProviderState.HEALTHY if now - latest.time <= freshness_limit else ProviderState.STALE,
            source=source,
            source_url=(
                "https://data-api.binance.vision/api/v3/klines"
                if asset_type == "crypto"
                else "https://query1.finance.yahoo.com/v8/finance/chart/"
            ),
            data_timestamp=latest.time,
            confidence=(90 if asset_type == "crypto" else 70)
            if now - latest.time <= freshness_limit
            else 35,
            is_fallback=asset_type != "crypto",
        ),
    )


def change_at(candles: list[Candle], delta: timedelta) -> float | None:
    latest = candles[-1]
    target = latest.time - delta
    previous = next((c for c in reversed(candles[:-1]) if c.time <= target), None)
    return pct_change(latest.close, previous.close if previous else None)


def unavailable_snapshot(asset: str, asset_type: str, error: str) -> MarketSnapshot:
    return MarketSnapshot(
        asset=asset,
        asset_type=asset_type,
        data_time=datetime.now(UTC),
        price=0,
        changes={"5m": None, "15m": None, "1h": None, "24h": None},
        volume_ratio=None,
        ema20=None,
        ema60=None,
        ema200=None,
        rsi=None,
        rsi_previous=None,
        macd=None,
        macd_signal=None,
        macd_histogram=None,
        atr=None,
        atr_pct=None,
        volatility=None,
        breakout=False,
        breakdown=False,
        pullback=False,
        volume_state="数据暂不可用",
        recent_high=None,
        recent_low=None,
        fresh=False,
        source="数据暂不可用",
        error=error,
        provider=provider_status(
            status=ProviderState.UNAVAILABLE,
            source="行情源",
            source_url="",
            data_timestamp=None,
            confidence=0,
            error=type(error).__name__ if not isinstance(error, str) else "行情获取失败",
        ),
    )
