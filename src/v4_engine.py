from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .alpha_finder import AlphaCandidate, AlphaFinder
from .flow_analyzer import FlowAnalyzer, FlowResult
from .future_events import FutureEvent
from .industry_graph import GraphImpact, IndustryGraph
from .investment_score import InvestmentScoreCalculator, InvestmentScoreResult
from .llm_adapter import build_llm_adapter
from .market_data import MarketSnapshot
from .news import NewsItem
from .peer_comparison import PeerComparison, PeerGroupResult
from .ranking import RankingEngine, RankingReport
from .risk_finder import RiskFinder
from .scoring import calculate_scores
from .valuation_engine import ValuationEngine, ValuationResult, unavailable_valuation

UTC = timezone.utc


@dataclass(frozen=True)
class V4AssetDecision:
    symbol: str
    snapshot: MarketSnapshot
    score: InvestmentScoreResult
    flow: FlowResult
    valuation: ValuationResult
    alpha: AlphaCandidate | None
    catalyst: NewsItem | None
    graph_impact: GraphImpact | None
    peer_summary: str
    future_events: tuple[FutureEvent, ...]
    confirmed_fact: str
    system_inference: str
    unverifiable: str
    invalidation_conditions: tuple[str, ...]
    risks: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class V4Report:
    decisions: tuple[V4AssetDecision, ...]
    rankings: RankingReport
    scores: dict[str, InvestmentScoreResult]
    alpha_candidates: tuple[AlphaCandidate, ...]
    flows: dict[str, FlowResult]
    valuations: dict[str, ValuationResult]
    peer_results: dict[str, PeerGroupResult]
    future_events: tuple[FutureEvent, ...]
    generated_at: datetime


class V4Engine:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.graph = IndustryGraph.from_yaml(root / "config" / "industry_graph.yaml")
        self.peer_comparison = PeerComparison.from_yaml(root / "config" / "peer_groups.yaml")
        self.score_calculator = InvestmentScoreCalculator.from_yaml(root / "config" / "scoring_weights.yaml")
        valuation_rules = yaml.safe_load((root / "config" / "valuation_rules.yaml").read_text(encoding="utf-8")) or {}
        self.valuation_engine = ValuationEngine(valuation_rules)
        self.llm = build_llm_adapter(root / "config" / "llm_providers.json")

    def build(
        self,
        core_symbols: list[str],
        snapshots: dict[str, MarketSnapshot],
        news: list[NewsItem],
        future_events: list[FutureEvent],
    ) -> V4Report:
        visible = {symbol: snapshot for symbol, snapshot in snapshots.items() if symbol != "DX-Y.NYB"}
        base_scores = {
            symbol: calculate_scores(snapshot, [item for item in news if symbol in item.assets])
            for symbol, snapshot in visible.items()
        }
        flows = {symbol: FlowAnalyzer().analyze(snapshot) for symbol, snapshot in visible.items()}
        impacts_by_news = [(item, impact) for item in news for impact in self.graph.match(item)]
        valuation_symbols = _valuation_selection(core_symbols, impacts_by_news)
        valuations = self.valuation_engine.analyze_many(visible, valuation_symbols)
        for symbol in visible:
            if symbol not in valuations:
                valuations[symbol] = unavailable_valuation(symbol, "本轮未进入基本面精查名单")
        peer_results = self.peer_comparison.compare(visible, valuations, flows)
        alpha_candidates = AlphaFinder(self.graph).find(news, visible, flows, valuations, future_events)
        alpha_map: dict[str, AlphaCandidate] = {}
        for candidate in alpha_candidates:
            if candidate.symbol not in alpha_map:
                alpha_map[candidate.symbol] = candidate
        risk_findings = {
            item.asset: item
            for item in RiskFinder().find(visible, base_scores, [], future_events)
        }
        impact_map: dict[str, tuple[NewsItem, GraphImpact]] = {}
        for item, impact in sorted(impacts_by_news, key=lambda pair: pair[1].weight, reverse=True):
            impact_map.setdefault(impact.symbol, (item, impact))
        catalyst_map: dict[str, tuple[NewsItem, GraphImpact | None]] = {}
        for item in sorted(news, key=lambda entry: (entry.is_major, entry.published_at), reverse=True):
            for symbol in item.assets:
                if symbol in visible:
                    catalyst_map.setdefault(symbol, (item, None))
        catalyst_map.update(impact_map)
        scores: dict[str, InvestmentScoreResult] = {}
        for symbol, snapshot in visible.items():
            valuation = valuations[symbol]
            flow = flows[symbol]
            alpha = alpha_map.get(symbol)
            catalyst, impact = catalyst_map.get(symbol, (None, None))
            event_score = 90 if catalyst and catalyst.source in {"美国 SEC EDGAR", "美联储", "美国劳工统计局"} else 75 if catalyst else 30
            industry_score = round(impact.weight * 100) if impact else 30
            fundamental_quality = _fundamental_quality(valuation)
            earnings_momentum = _earnings_momentum(valuation)
            technical_score = _technical_score(snapshot)
            macro_score = _macro_score(symbol, snapshots)
            risk_score = risk_findings[symbol].score
            opportunity_score = max(
                base_scores[symbol].opportunity,
                alpha.alpha_score if alpha else 0,
                round((event_score + industry_score + flow.flow_score + valuation.valuation_score + technical_score) / 5),
            )
            quality = _combined_quality(snapshot, flow, valuation)
            confidence = round((quality + flow.confidence + valuation.confidence + (alpha.confidence if alpha else 40)) / 4)
            components = {
                "event_catalyst": event_score,
                "industry_benefit": industry_score,
                "fundamental_quality": fundamental_quality,
                "earnings_momentum": earnings_momentum,
                "capital_flow": flow.flow_score,
                "valuation": valuation.valuation_score,
                "technical_setup": technical_score,
                "macro_environment": macro_score,
            }
            scores[symbol] = self.score_calculator.calculate(
                symbol=symbol,
                components=components,
                opportunity_score=opportunity_score,
                risk_score=risk_score,
                confidence_score=confidence,
                data_quality_score=quality,
                flow_score=flow.flow_score,
            )
        rankings = RankingEngine().build(scores, alpha_candidates, flows, valuations)
        decision_symbols = list(core_symbols)
        decision_symbols.extend(
            item.symbol for item in rankings.alpha if item.symbol not in decision_symbols
        )
        decisions = tuple(
            self._decision(
                symbol, visible[symbol], scores[symbol], flows[symbol], valuations[symbol],
                alpha_map.get(symbol), catalyst_map.get(symbol), peer_results, future_events,
            )
            for symbol in decision_symbols
            if symbol in visible
        )
        return V4Report(
            decisions=decisions,
            rankings=rankings,
            scores=scores,
            alpha_candidates=tuple(alpha_candidates),
            flows=flows,
            valuations=valuations,
            peer_results=peer_results,
            future_events=tuple(future_events),
            generated_at=datetime.now(UTC),
        )

    def _decision(
        self,
        symbol: str,
        snapshot: MarketSnapshot,
        score: InvestmentScoreResult,
        flow: FlowResult,
        valuation: ValuationResult,
        alpha: AlphaCandidate | None,
        impact_pair: tuple[NewsItem, GraphImpact | None] | None,
        peer_results: dict[str, PeerGroupResult],
        future_events: list[FutureEvent],
    ) -> V4AssetDecision:
        catalyst, impact = impact_pair if impact_pair else (None, None)
        official = catalyst and catalyst.source in {"美国 SEC EDGAR", "美联储", "美国劳工统计局"}
        confirmed = (
            f"{catalyst.source}于{catalyst.published_at.isoformat()}发布：{catalyst.title}"
            if official else "暂未取得官方来源可直接确认的催化剂。"
        )
        inference = (
            f"系统假设：{' → '.join(impact.path)}；权重{impact.weight:.2f}。{impact.hypothesis}"
            if impact else "系统未匹配到可配置产业链事件，主要依据量价、估值和技术面分析。"
        )
        unverifiable = (
            f"财经来源报道“{catalyst.title}”，尚需核对公司公告原文。"
            if catalyst and not official else
            "ETF/机构实时资金、期权、空头与链上净流数据暂无法验证。"
        )
        future = tuple(event for event in future_events if symbol in event.assets)
        risks = list(valuation.warnings[:1]) + list(flow.warnings[:1])
        if future:
            risks.append(f"未来7天事件：{future[0].name}")
        if snapshot.rsi and snapshot.rsi >= 70:
            risks.append("RSI偏热，追高风险上升。")
        while len(risks) < 3:
            risks.append("公开免费数据可能延迟或缺失。")
        invalidation = alpha.invalidation_conditions if alpha else (
            "价格跌破近20周期低点且资金代理转为流出",
            "催化剂被官方公告否定或产业链假设不再成立",
            "出现独立公司利空或数据质量降至不可用",
        )
        peer_summary = self.peer_comparison.summary_for(symbol, peer_results)
        fallback_summary = f"{symbol}综合{score.investment_score}/100，机会{score.opportunity_score}、风险{score.risk_score}；{score.conclusion}"
        summary = self.llm.summarize(
            symbol,
            f"{confirmed}；资金结论：{flow.flow_direction}；估值：{valuation.valuation_label}；执行建议：{score.action}",
            fallback_summary,
        )
        return V4AssetDecision(
            symbol=symbol, snapshot=snapshot, score=score, flow=flow, valuation=valuation,
            alpha=alpha, catalyst=catalyst, graph_impact=impact, peer_summary=peer_summary,
            future_events=future, confirmed_fact=confirmed, system_inference=inference,
            unverifiable=unverifiable, invalidation_conditions=invalidation,
            risks=tuple(risks[:3]), summary=summary,
        )


def _valuation_selection(
    core_symbols: list[str],
    pairs: list[tuple[NewsItem, GraphImpact]],
) -> list[str]:
    symbols = list(core_symbols)
    for _, impact in sorted(pairs, key=lambda pair: pair[1].weight, reverse=True):
        if impact.symbol not in symbols:
            symbols.append(impact.symbol)
    return symbols


def _fundamental_quality(valuation: ValuationResult) -> int:
    metrics = valuation.current_metrics
    values = [metrics.get("gross_margin_pct"), metrics.get("operating_margin_pct"), metrics.get("roe_pct")]
    available = [float(value) for value in values if isinstance(value, (int, float))]
    if not available:
        return 0
    margin_score = min(100, max(0, sum(available) / len(available)))
    fcf = metrics.get("fcf_yield_pct")
    return round(min(100, margin_score * 0.8 + (min(20, max(0, float(fcf) * 4)) if isinstance(fcf, (int, float)) else 0)))


def _earnings_momentum(valuation: ValuationResult) -> int:
    growth = valuation.current_metrics.get("revenue_growth_pct")
    eps = valuation.current_metrics.get("eps_growth_pct")
    available = [float(value) for value in (growth, eps) if isinstance(value, (int, float))]
    if not available:
        return 0
    return round(max(0, min(100, 50 + sum(available) / len(available))))


def _technical_score(snapshot: MarketSnapshot) -> int:
    if snapshot.error:
        return 0
    score = 40
    score += 20 if snapshot.ema20 and snapshot.ema60 and snapshot.price > snapshot.ema20 > snapshot.ema60 else -15
    score += 15 if snapshot.macd is not None and snapshot.macd_signal is not None and snapshot.macd > snapshot.macd_signal else -5
    score += 15 if snapshot.pullback or snapshot.breakout else 0
    score -= 20 if (snapshot.rsi or 0) >= 70 else 0
    return max(0, min(100, score))


def _macro_score(symbol: str, snapshots: dict[str, MarketSnapshot]) -> int:
    qqq = snapshots.get("QQQ")
    dxy = snapshots.get("DX-Y.NYB")
    score = 50
    if qqq and not qqq.error:
        score += 15 if (qqq.changes.get("1h") or 0) > 0 else -10
    if symbol == "BTC-USD" and dxy and not dxy.error:
        score += 10 if (dxy.changes.get("1h") or 0) < 0 else -10
    return max(0, min(100, score))


def _combined_quality(snapshot: MarketSnapshot, flow: FlowResult, valuation: ValuationResult) -> int:
    market_confidence = snapshot.provider.confidence if snapshot.provider else 0
    return round((market_confidence + flow.confidence + valuation.data_quality.score) / 3)
