from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .future_events import FutureEvent, FutureEventScanner
from .market_data import MarketDataClient, MarketSnapshot
from .news import NewsClient, NewsItem


@dataclass(frozen=True)
class ScanResult:
    snapshots: dict[str, MarketSnapshot]
    news: list[NewsItem]
    future_events: list[FutureEvent]


class Scanner:
    def scan(self, assets: list[dict]) -> ScanResult:
        market_assets = assets + [{"symbol": "DX-Y.NYB", "type": "macro"}]
        with ThreadPoolExecutor(max_workers=3) as executor:
            market_future = executor.submit(MarketDataClient().fetch_all, market_assets)
            news_future = executor.submit(NewsClient().fetch, assets)
            events_future = executor.submit(FutureEventScanner().scan, assets)
            return ScanResult(
                snapshots=market_future.result(),
                news=news_future.result(),
                future_events=events_future.result(),
            )
