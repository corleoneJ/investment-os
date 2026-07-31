from __future__ import annotations

from dataclasses import dataclass

from .event_analyzer import EventImpact
from .future_events import FutureEvent
from .market_data import MarketSnapshot
from .scoring import Scores


@dataclass(frozen=True)
class OpportunityFinding:
    asset: str
    score: int
    reasons: tuple[str, ...]


class OpportunityFinder:
    def find(
        self,
        snapshots: dict[str, MarketSnapshot],
        base_scores: dict[str, Scores],
        events: list[EventImpact],
        future_events: list[FutureEvent],
    ) -> list[OpportunityFinding]:
        findings = [
            self._score(asset, snapshot, base_scores[asset], events, future_events)
            for asset, snapshot in snapshots.items()
            if asset in base_scores
        ]
        return sorted(findings, key=lambda finding: finding.score, reverse=True)

    def _score(
        self,
        asset: str,
        snapshot: MarketSnapshot,
        base: Scores,
        events: list[EventImpact],
        future_events: list[FutureEvent],
    ) -> OpportunityFinding:
        if snapshot.error:
            return OpportunityFinding(asset, 0, ("行情数据暂不可用，无法确认机会。",))
        score = round(base.opportunity * 0.45)
        reasons: list[str] = []
        if (
            snapshot.ema20
            and snapshot.ema60
            and snapshot.ema200
            and snapshot.price > snapshot.ema20 > snapshot.ema60 > snapshot.ema200
        ):
            score += 20
            reasons.append("价格与 EMA20/60/200 呈多头排列。")
        if snapshot.macd is not None and snapshot.macd_signal is not None and snapshot.macd > snapshot.macd_signal:
            score += 10
            reasons.append("MACD 位于信号线上方。")
        if snapshot.pullback:
            score += 15
            reasons.append("中期趋势向上且价格正在回踩 EMA20。")
        if snapshot.rsi is not None and 40 <= snapshot.rsi <= 65:
            score += 10
            reasons.append("RSI 处于不过热的可观察区间。")
        beneficiary_events = [event for event in events if asset in event.industry.beneficiaries]
        if beneficiary_events:
            strongest = max(beneficiary_events, key=lambda event: event.level)
            score += strongest.level * 4
            reasons.append(f"产业链事件可能受益：{strongest.industry.theme}。")
        upcoming = [event for event in future_events if asset in event.assets]
        if upcoming:
            score += 5
            reasons.append(f"未来7天存在事件窗口：{upcoming[0].name}。")
        if (snapshot.rsi or 0) >= 70 or (snapshot.changes.get("24h") or 0) >= 8:
            score -= 20
            reasons.append("短线偏热，机会分已扣除追高风险。")
        if not snapshot.fresh:
            score -= 10
            reasons.append("行情时间较旧，机会分已降低并等待下一交易时段确认。")
        if not reasons:
            reasons.append("暂未发现领先于价格的高质量机会线索。")
        return OpportunityFinding(asset, max(0, min(100, score)), tuple(reasons))
