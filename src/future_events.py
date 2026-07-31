from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .market_data import build_session

LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
MONTHS = {
    name: index
    for index, name in enumerate(
        ("January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"),
        1,
    )
}


@dataclass(frozen=True)
class FutureEvent:
    name: str
    event_time: datetime
    source: str
    assets: tuple[str, ...]
    expected_impact: str
    url: str


class FutureEventScanner:
    def __init__(self, timeout: float = 4.0, days: int = 7) -> None:
        self.timeout = timeout
        self.days = days
        self.session = build_session(retries=1)

    def scan(self, assets: list[dict[str, Any]], now: datetime | None = None) -> list[FutureEvent]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        symbols = tuple(asset["symbol"] for asset in assets)
        jobs = {
            "BLS未来事件": lambda: self._fetch_bls(current, symbols),
            "FOMC未来事件": lambda: self._fetch_fomc(current, symbols),
            "未来财报": lambda: self._fetch_earnings(current, symbols),
        }
        result: list[FutureEvent] = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(job): name for name, job in jobs.items()}
            for future in as_completed(futures):
                try:
                    result.extend(future.result())
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("未来事件源失败：%s（%s）", futures[future], type(exc).__name__)
        unique = {(event.name, event.event_time.isoformat()): event for event in result}
        return sorted(unique.values(), key=lambda event: event.event_time)

    def _fetch_bls(self, now: datetime, symbols: tuple[str, ...]) -> list[FutureEvent]:
        url = "https://www.bls.gov/schedule/news_release/bls.ics"
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        text = re.sub(r"\r?\n[ \t]", "", response.text)
        events: list[FutureEvent] = []
        for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.DOTALL):
            summary = _ical_value(block, "SUMMARY")
            raw_time = _ical_value(block, "DTSTART")
            event_time = _parse_ical_time(raw_time)
            if not event_time or not _within(event_time, now, self.days):
                continue
            lowered = summary.lower()
            if not any(term in lowered for term in ("consumer price", "employment situation", "payroll")):
                continue
            events.append(
                FutureEvent(
                    name=summary,
                    event_time=event_time,
                    source="美国劳工统计局日历",
                    assets=symbols,
                    expected_impact="宏观数据可能影响利率、美元、QQQ与BTC波动。",
                    url=url,
                )
            )
        return events

    def _fetch_fomc(self, now: datetime, symbols: tuple[str, ...]) -> list[FutureEvent]:
        url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        year = now.astimezone(NEW_YORK).year
        match = re.search(
            rf">{year} FOMC Meetings<.*?(?=<div class=\"panel panel-default\">|\Z)",
            response.text,
            re.DOTALL,
        )
        if not match:
            return []
        events: list[FutureEvent] = []
        pattern = re.compile(
            r"fomc-meeting__month[^>]*><strong>([A-Za-z]+)</strong>.*?"
            r"fomc-meeting__date[^>]*>([^<]+)</div>",
            re.DOTALL,
        )
        for month_name, date_range in pattern.findall(match.group(0)):
            end_day = int(re.sub(r"\D", "", date_range.split("-")[-1]))
            event_time = datetime(
                year, MONTHS[month_name], end_day, 14, 0, tzinfo=NEW_YORK
            ).astimezone(UTC)
            if _within(event_time, now, self.days):
                events.append(
                    FutureEvent(
                        name="FOMC利率决议与声明",
                        event_time=event_time,
                        source="美联储FOMC日历",
                        assets=symbols,
                        expected_impact="利率路径和流动性预期可能影响所有监控资产。",
                        url=url,
                    )
                )
        return events

    def _fetch_earnings(self, now: datetime, symbols: tuple[str, ...]) -> list[FutureEvent]:
        wanted = set(symbols)
        start = now.astimezone(NEW_YORK).date()
        events: list[FutureEvent] = []
        with ThreadPoolExecutor(max_workers=7) as executor:
            futures = [
                executor.submit(self._fetch_earnings_day, start + timedelta(days=offset), wanted)
                for offset in range(self.days + 1)
                if (start + timedelta(days=offset)).weekday() < 5
            ]
            for future in as_completed(futures):
                try:
                    events.extend(future.result())
                except Exception as exc:  # noqa: BLE001
                    LOGGER.info("单日财报日历暂不可用（%s），继续保留其他日期。", type(exc).__name__)
        return events

    def _fetch_earnings_day(self, day: date, wanted: set[str]) -> list[FutureEvent]:
        url = "https://api.nasdaq.com/api/calendar/earnings"
        response = self.session.get(
            url,
            params={"date": day.isoformat()},
            headers={
                "User-Agent": "Mozilla/5.0 InvestmentOS/3.0",
                "Accept": "application/json, text/plain, */*",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        rows = (((response.json().get("data") or {}).get("rows")) or [])
        result: list[FutureEvent] = []
        for row in rows:
            symbol = row.get("symbol", "")
            if symbol not in wanted:
                continue
            raw_session = row.get("time", "")
            hour = 16 if "after" in raw_session else 8 if "before" in raw_session else 12
            event_time = datetime.combine(day, time(hour=hour), NEW_YORK).astimezone(UTC)
            result.append(
                FutureEvent(
                    name=f"{symbol} 财报",
                    event_time=event_time,
                    source="Nasdaq财报日历",
                    assets=(symbol,),
                    expected_impact="财报、业绩指引与AI资本开支可能引发盘前盘后波动。",
                    url=f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}/earnings",
                )
            )
        return result


def _ical_value(block: str, key: str) -> str:
    match = re.search(rf"^{key}(?:;[^:]*)?:(.+)$", block, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _parse_ical_time(value: str) -> datetime | None:
    cleaned = value.rstrip("Z")
    for pattern in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            zone = UTC if value.endswith("Z") else NEW_YORK
            parsed = datetime.strptime(cleaned, pattern).replace(tzinfo=zone)
            if pattern == "%Y%m%d":
                parsed = datetime.combine(parsed.date(), time(8, 30), zone)
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    return None


def _within(event_time: datetime, now: datetime, days: int) -> bool:
    return now <= event_time <= now + timedelta(days=days)
