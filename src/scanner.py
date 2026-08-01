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
    def scan(
        self,
        assets: list[dict],
        candidate_assets: list[dict] | None = None,
    ) -> ScanResult:
        """扫描核心资产和产业链候选池；候选池仍由配置文件控制。"""
        combined: dict[str, dict] = {
            item["symbol"]: item for item in [*assets, *(candidate_assets or [])]
        }
        all_assets = list(combined.values())
        market_assets = all_assets + [{"symbol": "DX-Y.NYB", "type": "macro"}]
        with ThreadPoolExecutor(max_workers=3) as executor:
            market_future = executor.submit(MarketDataClient().fetch_all, market_assets)
            news_future = executor.submit(NewsClient().fetch, all_assets)
            events_future = executor.submit(FutureEventScanner().scan, all_assets)
            return ScanResult(
                snapshots=market_future.result(),
                news=news_future.result(),
                future_events=events_future.result(),
            )
