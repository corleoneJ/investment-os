from datetime import datetime, timezone

from src.alerts import detect_alerts
from src.market_data import MarketSnapshot
from src.news import NewsItem
from src.scoring import Scores


def make_snapshot(**changes) -> MarketSnapshot:
    data = {
        "asset": "BTC-USD",
        "asset_type": "crypto",
        "data_time": datetime.now(timezone.utc),
        "price": 100,
        "changes": {"5m": 0.1, "15m": 0.2, "1h": 0.3, "24h": 0.4},
        "volume_ratio": 1,
        "ema20": 99,
        "ema60": 98,
        "ema200": 90,
        "rsi": 55,
        "rsi_previous": 54,
        "macd": 1,
        "macd_signal": 0.8,
        "macd_histogram": 0.2,
        "atr": 2,
        "atr_pct": 2,
        "volatility": 1,
        "breakout": False,
        "breakdown": False,
        "pullback": False,
        "volume_state": "正常",
        "recent_high": 101,
        "recent_low": 90,
        "fresh": True,
        "source": "测试",
        "error": None,
    }
    data.update(changes)
    return MarketSnapshot(**data)


def thresholds() -> dict:
    return {
        "rapid_rise": {"15m": 3, "1h": 5, "24h": 10},
        "rapid_fall": {"15m": -3, "1h": -5, "24h": -10},
        "breakout": {"volume_ratio": 1.5, "trend_score": 70},
        "pullback": {"ema20_distance_pct": 1, "opportunity_score": 70},
        "weakening": {"rsi_below": 40, "volume_ratio": 1.3},
    }


def test_no_condition_means_no_alert() -> None:
    assert detect_alerts(make_snapshot(), Scores(60, 40, 10), [], thresholds()) == []


def test_rapid_rise_contains_no_chasing_advice() -> None:
    snapshot = make_snapshot(changes={"5m": 1, "15m": 3.2, "1h": 4, "24h": 6})
    alerts = detect_alerts(snapshot, Scores(60, 30, 10), [], thresholds())
    assert alerts[0].alert_type == "急涨预警"
    assert "不建议直接追高" in alerts[0].advice[0]


def test_stale_data_never_triggers() -> None:
    snapshot = make_snapshot(
        fresh=False, changes={"5m": 10, "15m": 10, "1h": 10, "24h": 10}
    )
    assert detect_alerts(snapshot, Scores(100, 100, 0), [], thresholds()) == []


def test_major_news_can_trigger_when_market_is_closed() -> None:
    item = NewsItem(
        title="公司提交重大公告",
        source="美国 SEC EDGAR",
        published_at=datetime.now(timezone.utc),
        url="https://www.sec.gov/example",
        assets=("BTC-USD",),
        category="公司公告",
        is_major=True,
        is_negative=False,
    )
    alerts = detect_alerts(
        make_snapshot(fresh=False), Scores(0, 0, 0), [item], thresholds()
    )
    assert [alert.alert_type for alert in alerts] == ["重大新闻预警"]
