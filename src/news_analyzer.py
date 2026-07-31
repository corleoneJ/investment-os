from __future__ import annotations

from dataclasses import dataclass

from .event_analyzer import EventImpact
from .market_data import MarketSnapshot


@dataclass(frozen=True)
class CauseAnalysis:
    asset: str
    direction: str
    primary_cause: str
    analysis: str
    confidence: int
    evidence: tuple[str, ...]


class NewsAnalyzer:
    def analyze(
        self,
        asset: str,
        snapshot: MarketSnapshot,
        events: list[EventImpact],
        market_context: dict[str, MarketSnapshot],
    ) -> CauseAnalysis:
        change = snapshot.changes.get("24h")
        direction = "上涨" if change is not None and change > 0 else "下跌" if change is not None and change < 0 else "震荡"
        direct = [event for event in events if asset in event.item.assets]
        indirect = [
            event
            for event in events
            if asset in event.industry.beneficiaries or asset in event.industry.victims
        ]
        related = direct or indirect
        if related:
            event = max(related, key=lambda value: value.level)
            is_direct = event in direct
            confidence = min(
                95,
                55
                + event.level * 7
                + (5 if event.item.source == "美国 SEC EDGAR" else 0)
                - (15 if not is_direct else 0),
            )
            relationship = "直接相关事件" if is_direct else "产业链二阶影响线索"
            return CauseAnalysis(
                asset=asset,
                direction=direction,
                primary_cause=f"{event.item.title}（{relationship}）",
                analysis=(
                    f"事实层面有{event.item.source}事件，属于{relationship}；价格当前{direction}。"
                    f"事件方向判定为“{event.direction}”，但标题不能替代公告正文。"
                ),
                confidence=confidence,
                evidence=(event.fact, event.inference),
            )
        technical = self._technical_cause(snapshot)
        cross_market = self._cross_market(asset, snapshot, market_context)
        return CauseAnalysis(
            asset=asset,
            direction=direction,
            primary_cause=technical,
            analysis=(
                f"暂未发现可确认的直接消息驱动；当前更可能是{technical}。"
                f"{cross_market} 因缺少直接事件证据，不能把相关性当作因果。"
            ),
            confidence=45 if snapshot.fresh else 25,
        evidence=("行情与技术指标", "暂未发现24小时内可确认的重大直接新闻"),
        )

    @staticmethod
    def _technical_cause(snapshot: MarketSnapshot) -> str:
        if snapshot.breakout and snapshot.volume_state == "放量":
            return "放量技术突破与趋势资金推动"
        if snapshot.breakdown and snapshot.volume_state == "放量":
            return "放量跌破与风险资金撤离"
        if snapshot.pullback:
            return "上升趋势中的技术回踩"
        if snapshot.volume_state == "缩量":
            return "缩量交易与观望资金主导"
        return "技术面和市场风险偏好共同作用"

    @staticmethod
    def _cross_market(
        asset: str,
        snapshot: MarketSnapshot,
        market_context: dict[str, MarketSnapshot],
    ) -> str:
        qqq = market_context.get("QQQ")
        dxy = market_context.get("DX-Y.NYB")
        if asset == "BTC":
            qqq_change = qqq.changes.get("1h") if qqq and not qqq.error else None
            dxy_change = dxy.changes.get("1h") if dxy and not dxy.error else None
            return (
                f"跨市场参考：QQQ 1小时{_pct(qqq_change)}，美元指数代理1小时{_pct(dxy_change)}。"
                "24小时内未匹配到BTC ETF事件时，ETF原因视为未确认；"
                "当前未接入可靠的免费链上资金流，链上因素不作为已证实因果。"
            )
        qqq_change = qqq.changes.get("1h") if qqq and not qqq.error else None
        own_change = snapshot.changes.get("1h")
        if qqq_change is None or own_change is None:
            return "市场风险偏好数据暂不可用。"
        relation = "同向" if qqq_change * own_change >= 0 else "背离"
        return f"该资产与 QQQ 近1小时走势{relation}。"


def _pct(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:+.2f}%"
