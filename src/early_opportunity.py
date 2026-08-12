"""Early Opportunity Detector for event-driven catch-up opportunities."""

from dataclasses import dataclass

from src.models import TradeContext


@dataclass(frozen=True)
class EarlyOpportunityResult:
    early_event_score: int
    signal: str
    reason: str


class EarlyOpportunityDetector:
    def evaluate(self, context: TradeContext) -> EarlyOpportunityResult:
        event_strength = min(35, max(0, context.event.industry_impact // 2))
        peer_reaction = 0
        if context.peer_reactions:
            weighted = [
                peer.reaction_pct * peer.relevance_score / 100.0
                for peer in context.peer_reactions
            ]
            peer_reaction = min(25, int(max(weighted) * 2))
        own_reaction_gap = 0
        own_move = context.market.post_1d_change_pct
        if peer_reaction >= 10 and own_move <= 3:
            own_reaction_gap = 20
        flow_start = 15 if context.flow.flow_turning_positive else 0
        valuation = 10 if context.valuation.valuation_support else 0
        score = max(0, min(100, event_strength + peer_reaction + own_reaction_gap + flow_start + valuation))
        if score >= 70:
            signal = "EARLY_ALPHA"
            reason = "强事件+同行先动+自身涨幅较小+资金刚开始确认，存在潜在补涨。"
        elif score >= 50:
            signal = "EARLY_WATCH"
            reason = "存在早期线索，但确认度不足。"
        else:
            signal = "NONE"
            reason = "早期补涨条件不足。"
        return EarlyOpportunityResult(score, signal, reason)

