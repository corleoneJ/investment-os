from datetime import datetime, timedelta, timezone

from src.state import StateStore


def test_same_alert_is_suppressed_for_60_minutes(tmp_path) -> None:
    state = StateStore(tmp_path / "alerts.json")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert state.should_send_alert("BTC-USD", "急涨预警", 3.2, now)
    state.record_alert("BTC-USD", "急涨预警", 3.2, now, "测试")
    assert not state.should_send_alert(
        "BTC-USD", "急涨预警", 3.3, now + timedelta(minutes=30)
    )
    assert state.should_send_alert(
        "BTC-USD", "急涨预警", 4.3, now + timedelta(minutes=30)
    )
    assert state.should_send_alert(
        "BTC-USD", "急涨预警", 3.2, now + timedelta(minutes=60)
    )


def test_news_hash_is_persisted_and_deduplicated(tmp_path) -> None:
    path = tmp_path / "alerts.json"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state = StateStore(path)
    state.record_news("abc", now)
    state.save()
    restored = StateStore(path)
    restored.load()
    assert restored.news_seen("abc")
    assert not restored.news_seen("other")
