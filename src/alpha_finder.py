from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .flow_analyzer import FlowResult
from .future_events import FutureEvent
from .industry_graph import GraphImpact, IndustryGraph
from .market_data import MarketSnapshot
from .news import NewsItem
from .valuation_engine import ValuationResult

ALPHA_ACTIONS = {
    "继续观察", "等待资金确认", "等待回踩", "按计划小额分批",
    "暂缓新增", "不追高", "排除候选",
}


@dataclass(frozen=True)
class AlphaCandidate:
    symbol: str
    event_id: str
    event_title: str
    event_time: datetime
    event_source: str
    industry_chain: tuple[str, ...]
    benefit_level: int
    business_relevance: int
    peer_reaction: float | None
    own_reaction: float | None
    relative_lag: float | None
    fundamental_confirmation: str
    flow_confirmation: str
    technical_confirmation: str
    valuation_status: str
    risk_flags: tuple[str, ...]
    data_quality: int
    alpha_score: int
    confidence: int
    reasoning: tuple[str, ...]
    action: str
    invalidation_conditions: tuple[str, ...]


class AlphaFinder:
    def __init__(self, graph: IndustryGraph) -> None:
        self.graph = graph

    def find(
        self,
        news: list[NewsItem],
        snapshots: dict[str, MarketSnapshot],
        flows: dict[str, FlowResult],
        valuations: dict[str, ValuationResult],
        future_events: list[FutureEvent],
    ) -> list[AlphaCandidate]:
        candidates: list[AlphaCandidate] = []
        for item in news:
            impacts = self.graph.match(item)
            for impact in impacts:
                if impact.symbol not in snapshots:
                    continue
                candidates.append(
                    self._evaluate(item, impact, impacts, snapshots, flows, valuations, future_events)
                )
        unique: dict[tuple[str, str], AlphaCandidate] = {}
        for candidate in candidates:
            key = (candidate.symbol, candidate.event_id)
            if key not in unique or candidate.alpha_score > unique[key].alpha_score:
                unique[key] = candidate
        return sorted(unique.values(), key=lambda item: (-item.alpha_score, -item.confidence, item.symbol))

    def _evaluate(
        self,
        item: NewsItem,
        impact: GraphImpact,
        event_impacts: list[GraphImpact],
        snapshots: dict[str, MarketSnapshot],
        flows: dict[str, FlowResult],
        valuations: dict[str, ValuationResult],
        future_events: list[FutureEvent],
    ) -> AlphaCandidate:
        snapshot = snapshots[impact.symbol]
        own = snapshot.changes.get("24h")
        peer_symbols = [entry.symbol for entry in event_impacts if entry.symbol != impact.symbol and entry.symbol in snapshots]
        peer_values = [snapshots[symbol].changes.get("24h") for symbol in peer_symbols]
        available_peers = [float(value) for value in peer_values if value is not None]
        peer = sum(available_peers) / len(available_peers) if available_peers else None
        lag = peer - own if peer is not None and own is not None else None
        flow = flows.get(impact.symbol)
        valuation = valuations.get(impact.symbol)
        trend_confirmed = bool(
            snapshot.ema20 and snapshot.ema60 and snapshot.price >= snapshot.ema20 >= snapshot.ema60
            and snapshot.macd is not None and snapshot.macd_signal is not None and snapshot.macd >= snapshot.macd_signal
        )
        growth = valuation.current_metrics.get("revenue_growth_pct") if valuation else None
        fundamental = (
            "基本面增长为正"
            if isinstance(growth, (int, float)) and growth > 0
            else "基本面存在独立弱项"
            if isinstance(growth, (int, float)) and growth < 0
            else "基本面数据暂不可用"
        )
        flow_text = flow.flow_direction if flow else "数据不足"
        quality_values = [
            snapshot.provider.confidence if snapshot.provider else 0,
            flow.confidence if flow else 0,
            valuation.confidence if valuation else 0,
        ]
        quality = round(sum(quality_values) / len(quality_values))
        upcoming = [event for event in future_events if impact.symbol in event.assets]
        risk_flags: list[str] = []
        if upcoming:
            risk_flags.append(f"临近事件：{upcoming[0].name}")
        if valuation and valuation.valuation_label in {"偏贵", "明显过热", "周期数据失真"}:
            risk_flags.append(f"估值：{valuation.valuation_label}")
        if (snapshot.rsi or 0) >= 70 or (own or 0) >= 8:
            risk_flags.append("短线过热或涨幅已大")
        weak_not_lag = bool(
            own is not None and own < -3
            and (not flow or flow.flow_score < 45)
            and not trend_confirmed
        )
        priced = bool(own is not None and ((peer is not None and own >= peer + 3) or own >= 8))
        score = 0
        contributions: list[str] = []
        event_points = 15 if item.is_major else 8
        score += event_points
        contributions.append(f"事件强度 +{event_points}")
        benefit_points = round(impact.weight * 20)
        score += benefit_points
        contributions.append(f"产业链受益 +{benefit_points}")
        relevance_points = round(impact.weight * 15)
        score += relevance_points
        contributions.append(f"业务相关性 +{relevance_points}")
        if lag is not None and lag >= 2 and not weak_not_lag:
            score += 15
            contributions.append("相对滞涨 +15")
        if flow:
            flow_points = round(flow.flow_score * 0.15)
            score += flow_points
            contributions.append(f"资金确认 +{flow_points}")
        if trend_confirmed:
            score += 10
            contributions.append("技术确认 +10")
        if valuation:
            valuation_points = round(valuation.valuation_score * 0.1)
            score += valuation_points
            contributions.append(f"估值检查 +{valuation_points}")
        if weak_not_lag:
            score = min(score - 25, 35)
            contributions.append("弱势未涨 -25")
        if priced:
            score -= 20
            contributions.append("可能已充分定价 -20")
        if upcoming:
            score -= 8
            contributions.append("临近事件风险 -8")
        if quality < 50:
            score -= 12
            contributions.append("数据质量不足 -12")
        score = max(0, min(100, score))
        confidence = min(90, round(quality * 0.6 + impact.weight * 30))
        if weak_not_lag:
            action = "排除候选"
        elif priced or (snapshot.rsi or 0) >= 70:
            action = "不追高"
        elif score >= 75 and flow and flow.flow_score >= 60 and trend_confirmed:
            action = "按计划小额分批"
        elif score >= 65 and (not flow or flow.flow_score < 60):
            action = "等待资金确认"
        elif score >= 55:
            action = "等待回踩"
        elif risk_flags:
            action = "暂缓新增"
        else:
            action = "继续观察"
        return AlphaCandidate(
            symbol=impact.symbol,
            event_id=f"{impact.event_id}:{item.fingerprint[:12]}",
            event_title=item.title,
            event_time=item.published_at,
            event_source=item.source,
            industry_chain=impact.path,
            benefit_level=round(impact.weight * 100),
            business_relevance=round(impact.weight * 100),
            peer_reaction=peer,
            own_reaction=own,
            relative_lag=lag,
            fundamental_confirmation=fundamental,
            flow_confirmation=flow_text,
            technical_confirmation="趋势已确认" if trend_confirmed else "技术趋势未确认",
            valuation_status=valuation.valuation_label if valuation else "数据不足",
            risk_flags=tuple(risk_flags) or ("暂未发现结构化重大风险",),
            data_quality=quality,
            alpha_score=score,
            confidence=confidence,
            reasoning=tuple(contributions),
            action=action,
            invalidation_conditions=(
                "事件事实被官方公告否定或资本开支方向逆转",
                "资金代理转为流出且价格跌破EMA60",
                "出现公司独立利空或财报显著低于预期",
            ),
        )
