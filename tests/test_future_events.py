from datetime import date
from unittest.mock import Mock

from src.future_events import FutureEventScanner, _parse_ical_time


def test_parse_ical_time_uses_new_york_timezone() -> None:
    parsed = _parse_ical_time("20260807T083000")
    assert parsed is not None
    assert parsed.isoformat() == "2026-08-07T12:30:00+00:00"


def test_earnings_calendar_only_keeps_watched_assets() -> None:
    scanner = FutureEventScanner()
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": {
            "rows": [
                {"symbol": "SNDK", "time": "time-after-hours"},
                {"symbol": "OTHER", "time": "time-before-market"},
            ]
        }
    }
    scanner.session.get = Mock(return_value=response)
    events = scanner._fetch_earnings_day(date(2026, 8, 5), {"SNDK"})
    assert [event.name for event in events] == ["SNDK 财报"]
    assert events[0].event_time.isoformat() == "2026-08-05T20:00:00+00:00"
