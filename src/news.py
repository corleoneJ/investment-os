from __future__ import annotations

import hashlib
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

from .data_quality import ProviderState, ProviderStatus, provider_status
from .market_data import build_session

LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
NEWS_LOOKBACK = timedelta(hours=24)
MAJOR_FORMS = {"8-K", "10-Q", "10-K", "6-K", "20-F"}
MAJOR_TERMS = (
    "earnings", "revenue", "guidance", "outlook", "capital expenditure", "capex",
    "acquisition", "merger", "ceo", "chief executive", "investigation", "lawsuit",
    "accounting", "recall", "outage", "accident", "cpi", "nonfarm", "fomc",
    "powell", "rate decision", "monetary policy", "regulation", "bitcoin etf", "btc etf",
    "inflow", "outflow", "财报", "指引", "资本开支", "并购", "调查", "诉讼",
    "ppi", "producer price", "unemployment rate", "jobless", "fed speech",
)
MAINSTREAM_SOURCES = (
    "reuters", "associated press", "ap news", "bloomberg", "cnbc", "financial times",
    "wall street journal", "the wall street journal", "marketwatch", "barron's",
    "yahoo finance", "fortune", "forbes", "the new york times", "washington post",
)
NEGATIVE_TERMS = (
    "miss", "cuts guidance", "lower guidance", "downgrade", "investigation", "lawsuit",
    "recall", "outage", "accident", "fraud", "accounting issue", "outflow", "ban",
    "低于预期", "下调", "调查", "诉讼", "事故", "流出", "禁令",
)


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    published_at: datetime
    url: str
    assets: tuple[str, ...]
    category: str
    is_major: bool
    is_negative: bool
    provider: ProviderStatus | None = None

    def __post_init__(self) -> None:
        if self.provider is None:
            object.__setattr__(
                self,
                "provider",
                provider_status(
                    status=ProviderState.HEALTHY,
                    source=self.source,
                    source_url=self.url,
                    data_timestamp=self.published_at,
                    confidence=90 if self.source in {"美国 SEC EDGAR", "美联储", "美国劳工统计局"} else 60,
                    is_fallback=self.source not in {"美国 SEC EDGAR", "美联储", "美国劳工统计局"},
                ),
            )

    @property
    def fingerprint(self) -> str:
        normalized = re.sub(r"\s+", " ", self.url.strip() or self.title.strip()).lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class NewsClient:
    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self.session = build_session()
        self.sec_user_agent = (
            os.getenv("SEC_USER_AGENT") or "InvestmentOS/3.0 admin@example.invalid"
        )

    def fetch(self, assets: list[dict[str, Any]]) -> list[NewsItem]:
        symbols = tuple(asset["symbol"] for asset in assets)
        jobs: list[tuple[str, Any]] = [
            ("美联储", lambda: self._fetch_fed(symbols)),
            ("美国劳工统计局", lambda: self._fetch_bls(symbols)),
            ("主流媒体聚合", lambda: self._fetch_google_news([a["symbol"] for a in assets])),
        ]
        jobs.extend(
            (f"SEC {asset['symbol']}", lambda item=asset: self._fetch_sec(item))
            for asset in assets
            if asset.get("cik")
        )
        return self._run_jobs(jobs)

    def fetch_company_news(self, assets: list[dict[str, Any]]) -> list[NewsItem]:
        """10分钟新闻任务：公司、BTC ETF、监管与产业链新闻，不重复抓SEC。"""
        return self._run_jobs([
            ("公司与市场重大新闻", lambda: self._fetch_google_news([a["symbol"] for a in assets]))
        ])

    def fetch_earnings_sec(self, assets: list[dict[str, Any]]) -> list[NewsItem]:
        """30分钟任务：只抓有CIK的公司SEC重大文件。"""
        jobs = [
            (f"SEC {asset['symbol']}", lambda item=asset: self._fetch_sec(item))
            for asset in assets
            if asset.get("cik")
        ]
        return self._run_jobs(jobs)

    def fetch_macro(self, assets: list[dict[str, Any]]) -> list[NewsItem]:
        """每小时任务：只抓美联储和BLS官方宏观发布。"""
        symbols = tuple(asset["symbol"] for asset in assets)
        return self._run_jobs([
            ("美联储", lambda: self._fetch_fed(symbols)),
            ("美联储讲话", lambda: self._fetch_fed_speeches(symbols)),
            ("美国劳工统计局", lambda: self._fetch_bls(symbols)),
        ])

    def _run_jobs(self, jobs: list[tuple[str, Any]]) -> list[NewsItem]:
        items: list[NewsItem] = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(job): name for name, job in jobs}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    items.extend(future.result())
                except Exception as exc:  # noqa: BLE001  # 每个新闻源独立降级
                    LOGGER.warning("新闻源失败：%s（%s）", name, type(exc).__name__)
        unique = {item.fingerprint: item for item in items}
        return sorted(unique.values(), key=lambda item: item.published_at, reverse=True)

    def _fetch_sec(self, asset: dict[str, Any]) -> list[NewsItem]:
        cik = str(asset["cik"]).zfill(10)
        response = self.session.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers={"User-Agent": self.sec_user_agent},
            timeout=self.timeout,
        )
        response.raise_for_status()
        recent = response.json().get("filings", {}).get("recent", {})
        fields = ("accessionNumber", "filingDate", "acceptanceDateTime", "form", "primaryDocument")
        rows = zip(*(recent.get(field, []) for field in fields))
        cutoff = datetime.now(UTC) - NEWS_LOOKBACK
        result: list[NewsItem] = []
        for accession, filing_date, accepted, form, document in rows:
            if form not in MAJOR_FORMS:
                continue
            published = parse_time(accepted or filing_date)
            if published < cutoff:
                continue
            accession_plain = accession.replace("-", "")
            cik_plain = str(int(cik))
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/{accession_plain}/{document}"
            result.append(
                NewsItem(
                    title=f"{asset['symbol']} 提交 {form} 文件",
                    source="美国 SEC EDGAR",
                    published_at=published,
                    url=url,
                    assets=(asset["symbol"],),
                    category="公司公告/财报",
                    is_major=True,
                    is_negative=False,
                )
            )
        return result

    def _fetch_fed(self, symbols: tuple[str, ...]) -> list[NewsItem]:
        return self._fetch_rss(
            "https://www.federalreserve.gov/feeds/press_all.xml",
            source_default="美联储",
            assets=symbols,
            category="宏观/美联储",
        )

    def _fetch_fed_speeches(self, symbols: tuple[str, ...]) -> list[NewsItem]:
        return self._fetch_rss(
            "https://www.federalreserve.gov/feeds/speeches.xml",
            source_default="美联储讲话",
            assets=symbols,
            category="宏观/美联储讲话",
        )

    def _fetch_bls(self, symbols: tuple[str, ...]) -> list[NewsItem]:
        return self._fetch_rss(
            "https://www.bls.gov/feed/bls_latest.rss",
            source_default="美国劳工统计局",
            assets=symbols,
            category="宏观数据",
        )

    def _fetch_google_news(self, symbols: list[str]) -> list[NewsItem]:
        company_query = " OR ".join(symbols)
        event_query = (
            '"earnings" OR "guidance" OR "AI capex" OR "FOMC" OR "CPI" OR '
            '"nonfarm payrolls" OR "Bitcoin ETF" OR "acquisition" OR "CEO"'
        )
        url = (
            "https://news.google.com/rss/search?q="
            + quote_plus(f"({company_query}) ({event_query}) when:1d")
            + "&hl=en-US&gl=US&ceid=US:en"
        )
        items = self._fetch_rss(url, "Google News", tuple(symbols), "财经媒体")
        matched: list[NewsItem] = []
        for item in items:
            if not any(name in item.source.lower() for name in MAINSTREAM_SOURCES):
                continue
            title_upper = item.title.upper()
            assets = tuple(symbol for symbol in symbols if symbol.replace("-USD", "") in title_upper)
            if not assets and any(term in item.title.lower() for term in ("fomc", "cpi", "federal reserve", "nonfarm")):
                assets = tuple(symbols)
            if assets:
                matched.append(
                    NewsItem(
                        title=item.title,
                        source=item.source,
                        published_at=item.published_at,
                        url=item.url,
                        assets=assets,
                        category=item.category,
                        is_major=item.is_major,
                        is_negative=item.is_negative,
                    )
                )
        return matched

    def _fetch_rss(
        self, url: str, source_default: str, assets: tuple[str, ...], category: str
    ) -> list[NewsItem]:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        cutoff = datetime.now(UTC) - NEWS_LOOKBACK
        result: list[NewsItem] = []
        for node in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = child_text(node, "title")
            link = child_text(node, "link")
            if not link:
                link_node = node.find("{http://www.w3.org/2005/Atom}link")
                link = link_node.attrib.get("href", "") if link_node is not None else ""
            published_raw = child_text(node, "pubDate") or child_text(node, "published") or child_text(node, "updated")
            published = parse_time(published_raw)
            if not title or published < cutoff:
                continue
            source = child_text(node, "source") or source_default
            lowered = title.lower()
            is_major = any(term in lowered for term in MAJOR_TERMS)
            result.append(
                NewsItem(
                    title=title.strip(),
                    source=source.strip(),
                    published_at=published,
                    url=link.strip(),
                    assets=assets,
                    category=category,
                    is_major=is_major,
                    is_negative=any(term in lowered for term in NEGATIVE_TERMS),
                )
            )
        return result


def child_text(node: ElementTree.Element, name: str) -> str:
    element = node.find(name)
    if element is None:
        element = node.find(f"{{http://www.w3.org/2005/Atom}}{name}")
    return (element.text or "") if element is not None else ""


def parse_time(value: str) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
