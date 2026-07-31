from __future__ import annotations

from dataclasses import dataclass

from .event_analyzer import EventImpact
from .future_events import FutureEvent
from .market_data import MarketSnapshot
from .scoring import Scores


@dataclass(frozen=True)
class RiskFinding:
    asset: str
    score: int
    reasons: tuple[str, ...]


class RiskFinder:
    def find(
        self,
        snapshots: dict[str, MarketSnapshot],
        base_scores: dict[str, Scores],
        events: list[EventImpact],
        future_events: list[FutureEvent],
    ) -> list[RiskFinding]:
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
    ) -> RiskFinding:
        if snapshot.error:
            return RiskFinding(asset, 60, ("行情数据暂不可用，信息风险较高。",))
        score = round(base.risk * 0.55)
        reasons: list[str] = []
        if (
            snapshot.ema20
            and snapshot.ema60
            and snapshot.ema200
            and snapshot.price < snapshot.ema20 < snapshot.ema60 < snapshot.ema200
        ):
            score += 25
            reasons.append("价格与 EMA20/60/200 呈空头排列。")
        if snapshot.macd is not None and snapshot.macd_signal is not None and snapshot.macd < snapshot.macd_signal:
            score += 10
            reasons.append("MACD 位于信号线下方。")
        if snapshot.breakdown:
            score += 15
            reasons.append("价格跌破近20周期低点。")
        if snapshot.volume_state == "放量" and (snapshot.changes.get("5m") or 0) < 0:
            score += 10
            reasons.append("下跌伴随成交量放大。")
        victim_events = [event for event in events if asset in event.industry.victims]
        if victim_events:
            strongest = max(victim_events, key=lambda event: event.level)
            score += strongest.level * 5
            reasons.append(f"产业链负面事件可能受损：{strongest.industry.theme}。")
        upcoming = [event for event in future_events if asset in event.assets]
        if upcoming:
            score += 5
            reasons.append(f"未来7天事件可能放大波动：{upcoming[0].name}。")
        if not snapshot.fresh:
            score += 5
            reasons.append("行情时间较旧，实时风险判断存在数据时效性风险。")
        if not reasons:
            reasons.append("暂未发现结构性高风险，但仍需遵守仓位纪律。")
        return RiskFinding(asset, max(0, min(100, score)), tuple(reasons))
