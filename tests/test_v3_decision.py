import json
from datetime import datetime, timezone
from pathlib import Path

from src.alert_manager import AlertManager, format_ai_message
from src.decision_engine import DecisionEngine, choose_action
from src.industry_analyzer import IndustryAnalyzer
from src.llm_adapter import DisabledLLMAdapter
from src.market_data import MarketSnapshot
from src.news import NewsItem
from src.scoring import Scores
from src.state import StateStore

ROOT = Path(__file__).resolve().parents[1]


def snapshot(asset: str, **overrides) -> MarketSnapshot:
    values = {
        "asset": asset,
        "asset_type": "stock",
        "data_time": datetime.now(timezone.utc),
        "price": 105,
        "changes": {"5m": 0.2, "15m": 0.5, "1h": 1.0, "24h": 2.0},
        "volume_ratio": 1.2,
        "ema20": 102,
        "ema60": 98,
        "ema200": 90,
        "rsi": 58,
        "rsi_previous": 55,
        "macd": 1.2,
        "macd_signal": 1.0,
        "macd_histogram": 0.2,
        "atr": 2,
        "atr_pct": 1.9,
        "volatility": 1.5,
        "breakout": False,
        "breakdown": False,
        "pullback": False,
        "volume_state": "正常",
        "recent_high": 108,
        "recent_low": 95,
        "fresh": True,
        "source": "测试",
        "error": None,
    }
    values.update(overrides)
    return MarketSnapshot(**values)


def test_industry_chain_finds_second_order_beneficiaries() -> None:
    config = json.loads((ROOT / "config" / "industry_map.json").read_text(encoding="utf-8"))
    analyzer = IndustryAnalyzer(config)
    item = NewsItem(
        title="Microsoft increases AI capex for data center expansion",
        source="Reuters",
        published_at=datetime.now(timezone.utc),
        url="https://example.test/news",
        assets=("MSFT",),
        category="财经媒体",
        is_major=True,
        is_negative=False,
    )
    impact = analyzer.analyze(item)
    assert impact.theme == "AI资本开支"
    assert {"NVDA", "AVGO", "MU", "SNDK"}.issubset(impact.beneficiaries)


def test_decision_engine_outputs_all_assets_and_required_message_sections() -> None:
    config = json.loads((ROOT / "config" / "industry_map.json").read_text(encoding="utf-8"))
    item = NewsItem(
        title="Microsoft increases AI capex for data center expansion",
        source="Reuters",
        published_at=datetime.now(timezone.utc),
        url="https://example.test/news",
        assets=("MSFT",),
        category="财经媒体",
        is_major=True,
        is_negative=False,
    )
    snapshots = {"MSFT": snapshot("MSFT"), "NVDA": snapshot("NVDA")}
    report = DecisionEngine(
        IndustryAnalyzer(config), DisabledLLMAdapter()
    ).decide(
        snapshots,
        [item],
        [],
        {"MSFT": Scores(80, 60, 10), "NVDA": Scores(80, 60, 10)},
    )
    assert len(report.decisions) == 2
    nvda = next(decision for decision in report.decisions if decision.asset == "NVDA")
    assert nvda.industry.theme == "AI资本开支"
    assert "产业链二阶影响线索" in nvda.cause.primary_cause
    message = format_ai_message(nvda, snapshots["NVDA"])
    for section in ("原因：", "AI分析：", "产业链：", "事件：", "风险：", "机会：", "执行建议：", "AI一句总结："):
        assert section in message


def test_v3_alert_manager_has_no_frequency_or_score_gate(tmp_path) -> None:
    config = json.loads((ROOT / "config" / "industry_map.json").read_text(encoding="utf-8"))
    snapshots = {"QQQ": snapshot("QQQ")}
    report = DecisionEngine(
        IndustryAnalyzer(config), DisabledLLMAdapter()
    ).decide(snapshots, [], [], {"QQQ": Scores(20, 10, 5)})

    class FakeFeishu:
        configured = True

        def __init__(self) -> None:
            self.messages = []

        def send(self, text: str) -> bool:
            self.messages.append(text)
            return True

    client = FakeFeishu()
    manager = AlertManager(client, StateStore(tmp_path / "state.json"))
    assert manager.deliver(report, snapshots) == (1, 0)
    assert manager.deliver(report, snapshots) == (1, 0)
    assert len(client.messages) == 2


def test_actions_are_explicit() -> None:
    item = snapshot("BTC", rsi=75)
    assert choose_action("BTC", item, 90, 10) == "不要追高"
    assert choose_action("BTC", snapshot("BTC"), 20, 10) == "继续定投"
    assert choose_action("NVDA", snapshot("NVDA", error="失败"), 90, 10) == "暂停新增"
