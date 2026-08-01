from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .alpha_finder import AlphaFinder
from .data_quality import DataQualityResult
from .flow_analyzer import FlowAnalyzer
from .industry_graph import IndustryGraph
from .investment_score import InvestmentScoreCalculator
from .market_data import Candle, make_snapshot
from .news import NewsItem
from .valuation_engine import ValuationResult

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def _valuation(symbol: str) -> ValuationResult:
    quality = DataQualityResult(80, 75, (), (), ())
    return ValuationResult(
        symbol=symbol, valuation_type="模拟多指标估值",
        current_metrics={"revenue_growth_pct": 18, "gross_margin_pct": 45, "operating_margin_pct": 22, "roe_pct": 25, "fcf_yield_pct": 3},
        historical_percentiles={"pe": None}, peer_comparison="模拟同行：合理",
        growth_adjusted_value="增长与估值大致匹配", cycle_adjustment="已考虑周期风险",
        valuation_score=60, valuation_label="合理", confidence=75,
        data_time=datetime.now(UTC), missing_fields=(), warnings=("这是测试模拟数据，不是市场事实。",),
        data_quality=quality,
    )


def main() -> int:
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    candles = [
        Candle(end - timedelta(minutes=5 * (219 - index)), 100 + index * 0.06 + 0.5, 100 + index * 0.06 - 0.5, 100 + index * 0.06, 1000 + index * 8)
        for index in range(220)
    ]
    symbols = ["NVDA", "AVGO", "TSM", "MU", "SNDK"]
    snapshots = {symbol: make_snapshot(symbol, "stock", candles, "本地模拟信号") for symbol in symbols}
    flows = {symbol: FlowAnalyzer().analyze(snapshot) for symbol, snapshot in snapshots.items()}
    valuations = {symbol: _valuation(symbol) for symbol in symbols}
    event = NewsItem(
        title="模拟：大型云厂商上调 AI capital expenditure capex",
        source="本地模拟器", published_at=end, url="simulation://ai-capex",
        assets=("MSFT",), category="AI资本开支", is_major=True, is_negative=False,
    )
    candidates = AlphaFinder(IndustryGraph.from_yaml(ROOT / "config" / "industry_graph.yaml")).find(
        [event], snapshots, flows, valuations, []
    )
    if not candidates:
        print("模拟失败：没有生成Alpha候选。")
        return 1
    top = candidates[0]
    calculator = InvestmentScoreCalculator.from_yaml(ROOT / "config" / "scoring_weights.yaml")
    score = calculator.calculate(
        top.symbol,
        {"event_catalyst": 90, "industry_benefit": top.benefit_level, "fundamental_quality": 70,
         "earnings_momentum": 65, "capital_flow": flows[top.symbol].flow_score, "valuation": 60,
         "technical_setup": 75, "macro_environment": 55},
        top.alpha_score, 35, top.confidence, top.data_quality, flows[top.symbol].flow_score,
    )
    print(
        f"模拟信号通过：{top.symbol}｜Alpha {top.alpha_score}｜综合 {score.investment_score}｜"
        f"机会 {score.opportunity_score}｜风险 {score.risk_score}｜建议 {score.action}。"
    )
    print("说明：全部输入均为本地模拟，仅验证规则链，不代表真实投资机会。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
