from __future__ import annotations

from dataclasses import dataclass

from .event_analyzer import EventAnalyzer, EventImpact
from .future_events import FutureEvent
from .industry_analyzer import IndustryAnalyzer, IndustryImpact
from .llm_adapter import LLMAdapter
from .market_data import MarketSnapshot
from .news import NewsItem
from .news_analyzer import CauseAnalysis, NewsAnalyzer
from .opportunity_finder import OpportunityFinder, OpportunityFinding
from .risk_finder import RiskFinder, RiskFinding
from .scoring import Scores

VALID_ACTIONS = {
    "继续定投",
    "等待回踩",
    "小额建仓",
    "继续持有",
    "减仓观察",
    "暂停新增",
    "不要追高",
    "继续观察",
}


@dataclass(frozen=True)
class AssetDecision:
    asset: str
    cause: CauseAnalysis
    industry: IndustryImpact
    event: EventImpact | None
    risk: RiskFinding
    opportunity: OpportunityFinding
    future_events: tuple[FutureEvent, ...]
    action: str
    summary: str

    @property
    def dominant_label(self) -> str:
        return "风险" if self.risk.score > self.opportunity.score else "机会"


@dataclass(frozen=True)
class DecisionReport:
    decisions: tuple[AssetDecision, ...]
    opportunities: tuple[OpportunityFinding, ...]
    risks: tuple[RiskFinding, ...]
    events: tuple[EventImpact, ...]
    future_events: tuple[FutureEvent, ...]


class DecisionEngine:
    def __init__(
        self,
        industry_analyzer: IndustryAnalyzer,
        llm_adapter: LLMAdapter,
    ) -> None:
        self.industry_analyzer = industry_analyzer
        self.event_analyzer = EventAnalyzer(industry_analyzer)
        self.news_analyzer = NewsAnalyzer()
        self.opportunity_finder = OpportunityFinder()
        self.risk_finder = RiskFinder()
        self.llm_adapter = llm_adapter

    def decide(
        self,
        snapshots: dict[str, MarketSnapshot],
        news: list[NewsItem],
        future_events: list[FutureEvent],
        scores: dict[str, Scores],
    ) -> DecisionReport:
        visible = {asset: snapshot for asset, snapshot in snapshots.items() if asset in scores}
        events = self.event_analyzer.analyze_all(news)
        opportunities = self.opportunity_finder.find(visible, scores, events, future_events)
        risks = self.risk_finder.find(visible, scores, events, future_events)
        opportunity_map = {finding.asset: finding for finding in opportunities}
        risk_map = {finding.asset: finding for finding in risks}
        decisions: list[AssetDecision] = []
        for asset, snapshot in visible.items():
            related_events = [
                event
                for event in events
                if asset in event.item.assets
                or asset in event.industry.beneficiaries
                or asset in event.industry.victims
            ]
            primary_event = max(related_events, key=lambda event: event.level, default=None)
            industry = (
                primary_event.industry
                if primary_event
                else IndustryImpact(
                    theme=self.industry_analyzer.role(asset),
                    industries=("资产自身基本面",),
                    chain=("宏观与行业需求", "公司基本面", "估值与资金", "资产价格"),
                    beneficiaries=(),
                    victims=(),
                    confidence=35,
                )
            )
            cause = self.news_analyzer.analyze(asset, snapshot, events, snapshots)
            opportunity = opportunity_map[asset]
            risk = risk_map[asset]
            related_future = tuple(event for event in future_events if asset in event.assets)
            action = choose_action(asset, snapshot, opportunity.score, risk.score)
            fallback = self._summary(asset, cause, opportunity, risk, action, primary_event)
            facts = (
                f"原因={cause.primary_cause}；可信度={cause.confidence}；"
                f"机会={opportunity.score}；风险={risk.score}；建议={action}"
            )
            summary = self.llm_adapter.summarize(asset, facts, fallback)
            decisions.append(
                AssetDecision(
                    asset=asset,
                    cause=cause,
                    industry=industry,
                    event=primary_event,
                    risk=risk,
                    opportunity=opportunity,
                    future_events=related_future,
                    action=action,
                    summary=summary,
                )
            )
        return DecisionReport(
            decisions=tuple(decisions),
            opportunities=tuple(opportunities),
            risks=tuple(risks),
            events=tuple(events),
            future_events=tuple(future_events),
        )

    @staticmethod
    def _summary(
        asset: str,
        cause: CauseAnalysis,
        opportunity: OpportunityFinding,
        risk: RiskFinding,
        action: str,
        event: EventImpact | None,
    ) -> str:
        focus = event.item.title if event else cause.primary_cause
        dominant = "机会" if opportunity.score >= risk.score else "风险"
        return (
            f"{asset} 当前真正值得关注的是“{focus}”，"
            f"{dominant}信号占优，执行上应{action}。"
        )


def choose_action(
    asset: str,
    snapshot: MarketSnapshot,
    opportunity_score: int,
    risk_score: int,
) -> str:
    if snapshot.error or risk_score >= 75:
        return "暂停新增"
    if risk_score >= 60:
        return "减仓观察"
    if not snapshot.fresh:
        return "继续观察"
    if (snapshot.rsi or 0) >= 70 or (snapshot.changes.get("24h") or 0) >= 8:
        return "不要追高"
    if opportunity_score >= 75 and snapshot.pullback:
        return "小额建仓"
    if opportunity_score >= 65:
        return "等待回踩"
    if risk_score >= 40:
        return "继续观察"
    if asset in {"BTC", "QQQ"}:
        return "继续定投"
    if snapshot.ema20 and snapshot.ema60 and snapshot.price > snapshot.ema20 > snapshot.ema60:
        return "继续持有"
    return "继续观察"
