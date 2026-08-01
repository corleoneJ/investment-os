from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .flow_analyzer import FlowResult
from .market_data import MarketSnapshot
from .valuation_engine import ValuationResult


@dataclass(frozen=True)
class PeerGroupResult:
    group: str
    symbols: tuple[str, ...]
    fastest_growth: str
    lowest_valuation: str
    highest_quality: str
    highest_risk: str
    likely_laggard: str
    possible_value_trap: str
    explanations: tuple[str, ...]


class PeerComparison:
    def __init__(self, groups: dict[str, list[str]]) -> None:
        self.groups = groups

    @classmethod
    def from_yaml(cls, path: str | Path) -> PeerComparison:
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    def compare(
        self,
        snapshots: dict[str, MarketSnapshot],
        valuations: dict[str, ValuationResult],
        flows: dict[str, FlowResult],
    ) -> dict[str, PeerGroupResult]:
        results: dict[str, PeerGroupResult] = {}
        for group, configured in self.groups.items():
            symbols = [symbol for symbol in configured if symbol in snapshots]
            if not symbols:
                continue
            growth = _best(symbols, lambda symbol: _metric(valuations, symbol, "revenue_growth_pct"))
            cheap = _best(symbols, lambda symbol: valuations.get(symbol).valuation_score if symbol in valuations else None)
            quality = _best(symbols, lambda symbol: _quality_score(valuations.get(symbol)))
            risk = _best(symbols, lambda symbol: _risk_proxy(snapshots[symbol]))
            laggard = _best(symbols, lambda symbol: _lag_score(symbol, snapshots, flows))
            trap = _best(symbols, lambda symbol: _trap_score(symbol, valuations, snapshots, flows))
            explanations = (
                f"增长最快：{growth}（基于可得营收增速）",
                f"估值吸引力最高：{cheap}（多指标估值分，不等于绝对低估）",
                f"质量最高：{quality}（利润率、ROE与现金流代理）",
                f"风险最高：{risk}（趋势、波动与量价代理）",
                f"最可能补涨：{laggard}（相对落后且资金/趋势未明显恶化）",
                f"价值陷阱风险：{trap}（便宜但增长、趋势或资金较弱）",
            )
            results[group] = PeerGroupResult(
                group=group, symbols=tuple(symbols), fastest_growth=growth,
                lowest_valuation=cheap, highest_quality=quality, highest_risk=risk,
                likely_laggard=laggard, possible_value_trap=trap, explanations=explanations,
            )
        return results

    def summary_for(self, symbol: str, results: dict[str, PeerGroupResult]) -> str:
        related = [result for result in results.values() if symbol in result.symbols]
        if not related:
            return "未配置同行组"
        return "；".join(result.explanations[0] + "，" + result.explanations[1] for result in related)


def _metric(valuations: dict[str, ValuationResult], symbol: str, key: str) -> float | None:
    return valuations[symbol].current_metrics.get(key) if symbol in valuations else None


def _quality_score(valuation: ValuationResult | None) -> float | None:
    if not valuation:
        return None
    metrics = valuation.current_metrics
    values = [metrics.get("gross_margin_pct"), metrics.get("operating_margin_pct"), metrics.get("roe_pct")]
    available = [float(value) for value in values if isinstance(value, (int, float))]
    fcf = metrics.get("fcf_yield_pct")
    return (sum(available) / len(available) if available else 0) + (float(fcf) if isinstance(fcf, (int, float)) else 0)


def _risk_proxy(snapshot: MarketSnapshot) -> float:
    score = snapshot.atr_pct or 0
    score += 20 if snapshot.breakdown else 0
    score += 10 if snapshot.ema20 and snapshot.price < snapshot.ema20 else 0
    score += 10 if (snapshot.changes.get("24h") or 0) < -5 else 0
    return score


def _lag_score(symbol: str, snapshots: dict[str, MarketSnapshot], flows: dict[str, FlowResult]) -> float:
    snapshot = snapshots[symbol]
    reaction = snapshot.changes.get("24h") or 0
    flow = flows.get(symbol)
    if reaction < -5 or (flow and flow.flow_direction == "资金流出"):
        return -100
    return -reaction + ((flow.flow_score if flow else 0) / 20)


def _trap_score(
    symbol: str,
    valuations: dict[str, ValuationResult],
    snapshots: dict[str, MarketSnapshot],
    flows: dict[str, FlowResult],
) -> float | None:
    valuation = valuations.get(symbol)
    if not valuation:
        return None
    growth = valuation.current_metrics.get("revenue_growth_pct")
    weak_growth = 20 if isinstance(growth, (int, float)) and growth < 0 else 0
    weak_trend = 15 if snapshots[symbol].ema20 and snapshots[symbol].price < snapshots[symbol].ema20 else 0
    weak_flow = 15 if flows.get(symbol) and flows[symbol].flow_direction == "资金流出" else 0
    cheap = valuation.valuation_score / 5
    return cheap + weak_growth + weak_trend + weak_flow


def _best(symbols: list[str], scorer) -> str:
    scored = [(symbol, scorer(symbol)) for symbol in symbols]
    available = [(symbol, score) for symbol, score in scored if score is not None]
    return max(available, key=lambda item: (item[1], item[0]))[0] if available else "数据暂不可用"
