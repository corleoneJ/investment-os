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

from .indicators import ema, pct_change, realized_volatility, rsi

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
    rsi: float | None
    rsi_previous: float | None
    volatility: float | None
    breakout: bool
    breakdown: bool
    recent_high: float | None
    recent_low: float | None
    fresh: bool
    source: str
    error: str | None = None


def build_session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "InvestmentOS/1.0 (GitHub Actions market monitor)"})
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
    rsi_values = rsi(closes, 14)
    latest = candles[-1]
    prior = candles[-21:-1]
    average_volume = sum(c.volume for c in prior) / len(prior) if prior else 0
    volume_ratio = latest.volume / average_volume if average_volume > 0 else None
    recent_high = max((c.high for c in prior), default=None)
    recent_low = min((c.low for c in prior), default=None)
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
        rsi=next((value for value in reversed(rsi_values) if value is not None), None),
        rsi_previous=next((value for value in reversed(rsi_values[:-1]) if value is not None), None),
        volatility=realized_volatility(closes),
        breakout=recent_high is not None and latest.close > recent_high,
        breakdown=recent_low is not None and latest.close < recent_low,
        recent_high=recent_high,
        recent_low=recent_low,
        fresh=now - latest.time <= freshness_limit,
        source=source,
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
        rsi=None,
        rsi_previous=None,
        volatility=None,
        breakout=False,
        breakdown=False,
        recent_high=None,
        recent_low=None,
        fresh=False,
        source="数据暂不可用",
        error=error,
    )
