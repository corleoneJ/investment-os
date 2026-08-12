from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Iterable

from .feishu import FeishuClient
from .flow_analyzer import FlowResult
from .market_data import MarketSnapshot
from .models import Event, FlowData, MarketData, TradeContext, ValuationData
from .news import NewsItem
from .state import StateStore
from .trade_filter_layer import TradeFilterLayer, TradeFilterResult
from .v4_engine import V4AssetDecision, V4Report
from .valuation_engine import ValuationResult

LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


class V5ProductionBridge:
    """Connect existing V4 providers/scanners to the V5 trade filter layer.

    V4 remains responsible for data collection and base analysis. This bridge is
    the only production path that may produce realtime Feishu trade messages.
    """

    def __init__(
        self,
        state: StateStore,
        feishu: FeishuClient,
        layer: TradeFilterLayer | None = None,
    ) -> None:
        self.state = state
        self.feishu = feishu
        self.layer = layer or TradeFilterLayer()

    def evaluate_decision(
        self, decision: V4AssetDecision, now: datetime | None = None
    ) -> TradeFilterResult:
        return self.layer.evaluate(_context_from_v4_decision(decision), now)

    def deliver_report(self, report: V4Report, dry_run: bool = False) -> tuple[int, int]:
        """Deliver V5-filtered realtime signals from a V4 report."""
        unique = {decision.symbol: decision for decision in report.decisions}
        if not dry_run and not self.feishu.configured:
            LOGGER.warning("未配置 FEISHU_WEBHOOK：V5分析已完成，全部消息跳过发送。")
            return 0, len(unique)
        sent = 0
        failed = 0
        now = datetime.now(UTC)
        for decision in unique.values():
            result = self.evaluate_decision(decision, now)
            pushed = self._deliver_result(result, now, dry_run)
            sent += 1 if pushed else 0
            failed += 1 if result.should_send_feishu and not dry_run and not pushed else 0
            LOGGER.info(
                "V5实时过滤：%s｜grade=%s｜entry_model=%s｜FINAL_ACTION=%s｜send=%s",
                decision.symbol,
                result.grade.grade,
                result.entry.entry_model,
                result.final_action.final_action,
                result.should_send_feishu,
            )
        self.state.save()
        return sent, failed

    def deliver_news_items(
        self,
        workflow: str,
        news: Iterable[NewsItem],
        snapshots: dict[str, MarketSnapshot],
        dry_run: bool = False,
    ) -> tuple[int, int, int]:
        """Run news/earnings/macro events through V5 before any realtime push."""
        if not dry_run and not self.feishu.configured:
            LOGGER.warning("未配置 FEISHU_WEBHOOK：%s V5过滤已完成，消息跳过发送。", workflow)
        sent = 0
        failed = 0
        skipped = 0
        now = datetime.now(UTC)
        for item in news:
            contexts = [
                _context_from_news_item(item, snapshot)
                for symbol in item.assets
                if (snapshot := snapshots.get(symbol)) is not None
            ]
            if not contexts:
                skipped += 1
                continue
            for context in contexts:
                result = self.layer.evaluate(context, now)
                if not result.should_send_feishu:
                    skipped += 1
                    LOGGER.info(
                        "%s V5过滤：%s｜grade=%s｜entry_model=%s｜FINAL_ACTION=%s｜不发送",
                        workflow,
                        context.event.symbol,
                        result.grade.grade,
                        result.entry.entry_model,
                        result.final_action.final_action,
                    )
                    continue
                pushed = self._deliver_result(result, now, dry_run)
                sent += 1 if pushed else 0
                failed += 1 if not dry_run and not pushed else 0
        self.state.save()
        return sent, failed, skipped

    def _deliver_result(
        self, result: TradeFilterResult, now: datetime, dry_run: bool
    ) -> bool:
        record = result.signal_record
        fingerprint = _signal_fingerprint(result)
        if not result.should_send_feishu:
            return False
        if self.state.decision_is_duplicate(record.symbol, fingerprint):
            LOGGER.info("V5智能去重：%s 同一FINAL_ACTION与入场条件不重复发送。", record.symbol)
            return False
        if dry_run:
            LOGGER.info(
                "演练模式生成V5消息：%s｜grade=%s｜entry_model=%s｜FINAL_ACTION=%s",
                record.symbol,
                record.grade,
                record.buy_zone,
                record.decision,
            )
            return True
        if not self.feishu.configured:
            return False
        if not self.feishu.send(result.feishu_message):
            return False
        self.state.record_decision_fingerprint(record.symbol, fingerprint, now)
        self.state.record_v4_decision(
            asset=record.symbol,
            now=now,
            price=record.price,
            investment_score=result.scoring.total,
            opportunity_score=record.opportunity_score,
            risk_score=record.risk_score,
            data_quality_score=80 if result.grade.grade in {"S", "A"} else 50,
            action=record.decision,
            summary=result.entry.core_conclusion,
        )
        return True


def _context_from_v4_decision(decision: V4AssetDecision) -> TradeContext:
    event = _event_from_v4(decision)
    market = _market_from_snapshot(decision.snapshot)
    flow = _flow_from_v4(decision.flow)
    valuation = _valuation_from_v4(decision.valuation, decision.score.risk_score)
    previous = None
    return TradeContext(
        event=event,
        market=market,
        flow=flow,
        valuation=valuation,
        data_quality="LOW" if decision.snapshot.error else "HIGH",
        previous_decision=previous,
        previous_grade=None,
    )


def _context_from_news_item(item: NewsItem, snapshot: MarketSnapshot) -> TradeContext:
    event = _event_from_news(item, snapshot.asset)
    market = _market_from_snapshot(snapshot)
    flow = _flow_from_snapshot(snapshot)
    risk = 70 if item.is_negative else 45
    opportunity = 72 if item.is_major else 35
    valuation = ValuationData(
        opportunity_score=opportunity,
        risk_score=risk,
        valuation_support=item.is_major and not item.is_negative,
        target_upside_pct=18 if item.is_major and not item.is_negative else 5,
        downside_pct=8,
    )
    return TradeContext(event=event, market=market, flow=flow, valuation=valuation)


def _event_from_v4(decision: V4AssetDecision) -> Event:
    catalyst = decision.catalyst
    title = catalyst.title if catalyst else decision.confirmed_fact
    source = catalyst.source if catalyst else "Investment OS V4"
    category = catalyst.category if catalyst else "V4综合分析"
    published_at = catalyst.published_at if catalyst else decision.snapshot.data_time
    direction = -1 if catalyst and catalyst.is_negative else 1
    event_score = max(0, min(100, decision.score.opportunity_score))
    industry = round((decision.graph_impact.weight * 100) if decision.graph_impact else 30)
    return Event(
        event_id=catalyst.fingerprint if catalyst else _stable_id(decision.symbol, title),
        symbol=decision.symbol,
        title=title or "V4综合分析",
        source=source,
        published_at=published_at,
        category=category,
        summary=decision.summary,
        tags=(category,),
        revenue_impact=round(event_score * 0.30) * direction,
        profit_impact=round(event_score * 0.25) * direction,
        guidance_impact=round(event_score * 0.20) * direction,
        supply_demand_impact=round(event_score * 0.15) * direction,
        valuation_impact=round(decision.valuation.valuation_score * 0.20) * direction,
        competition_impact=round(industry * 0.10) * direction,
        industry_impact=round(industry * 0.20) * direction,
        capital_flow_impact=round(decision.flow.flow_score * 0.20) * direction,
        surprise_level=20 if catalyst and catalyst.is_major else 5,
        confirmed=bool(catalyst and catalyst.is_major),
        previously_priced=decision.snapshot.rsi is not None and decision.snapshot.rsi >= 75,
    )


def _event_from_news(item: NewsItem, symbol: str) -> Event:
    direction = -1 if item.is_negative else 1
    base = 75 if item.is_major else 25
    official = item.source in {"美国 SEC EDGAR", "美联储", "美国劳工统计局"}
    return Event(
        event_id=item.fingerprint,
        symbol=symbol,
        title=item.title,
        source=item.source,
        published_at=item.published_at,
        category=item.category,
        summary=item.title,
        tags=(item.category,),
        revenue_impact=round(base * 0.30) * direction,
        profit_impact=round(base * 0.25) * direction,
        guidance_impact=round(base * 0.20) * direction,
        supply_demand_impact=round(base * 0.15) * direction,
        valuation_impact=round(base * 0.15) * direction,
        competition_impact=round(base * 0.10) * direction,
        industry_impact=round(base * 0.25) * direction,
        policy_impact=round(base * 0.20) * direction if "宏观" in item.category else 0,
        capital_flow_impact=round(base * 0.15) * direction,
        surprise_level=20 if item.is_major else 0,
        confirmed=official or item.is_major,
        source_quality_hint="normal" if official else "fallback",
    )


def _market_from_snapshot(snapshot: MarketSnapshot) -> MarketData:
    price = max(0.01, snapshot.price or 0.01)
    ema20 = snapshot.ema20
    ema50 = snapshot.ema60
    trend = (
        "UP"
        if ema20 and ema50 and price > ema20 > ema50
        else "DOWN"
        if ema20 and ema50 and price < ema20 < ema50
        else "SIDEWAYS"
    )
    support = snapshot.recent_low or (ema20 * 0.98 if ema20 else price * 0.94)
    resistance = snapshot.recent_high or (ema20 * 1.04 if ema20 else price * 1.12)
    previous_close = price / (1 + ((snapshot.changes.get("1d") or 0) / 100))
    vwap_deviation = (
        (price / snapshot.vwap - 1) * 100
        if snapshot.vwap
        else 0.0
    )
    return MarketData(
        price=price,
        previous_close=previous_close,
        pre_event_change_pct=snapshot.changes.get("1d") or 0.0,
        post_1h_change_pct=snapshot.changes.get("1h") or 0.0,
        post_4h_change_pct=snapshot.changes.get("4h") or 0.0,
        post_1d_change_pct=snapshot.changes.get("1d") or 0.0,
        post_5d_change_pct=snapshot.changes.get("5d") or 0.0,
        volume_ratio=snapshot.volume_ratio or 1.0,
        gap_pct=snapshot.changes.get("1d") or 0.0,
        vwap_deviation_pct=vwap_deviation,
        atr_deviation=abs((snapshot.atr_pct or 0.0) / 2.0),
        rsi=snapshot.rsi or 50.0,
        ema20=ema20,
        ema50=ema50,
        atr=snapshot.atr,
        support=support,
        resistance=resistance,
        recent_high=snapshot.recent_high,
        recent_low=snapshot.recent_low,
        broke_resistance=bool(snapshot.breakout),
        pullback_confirmed=bool(snapshot.pullback),
        reversal_structure=bool(snapshot.breakout and (snapshot.rsi or 50) < 72),
        trend=trend,
    )


def _flow_from_v4(flow: FlowResult) -> FlowData:
    return FlowData(
        fund_flow_score=flow.flow_score,
        volume_confirmed=flow.volume_confirmation == "放量" or (flow.relative_volume or 0) >= 1.2,
        money_flow_confirmed=flow.flow_direction in {"增量资金确认", "资金流入但持续性待验证"},
        vwap_confirmed=flow.vwap_position == "价格在VWAP上方",
        flow_turning_positive=flow.flow_direction != "资金流出",
    )


def _flow_from_snapshot(snapshot: MarketSnapshot) -> FlowData:
    volume_confirmed = (snapshot.volume_ratio or 0) >= 1.2
    money_flow_confirmed = snapshot.obv_trend == "上升"
    return FlowData(
        fund_flow_score=65 if volume_confirmed and money_flow_confirmed else 45,
        volume_confirmed=volume_confirmed,
        money_flow_confirmed=money_flow_confirmed,
        vwap_confirmed=bool(snapshot.vwap and snapshot.price > snapshot.vwap),
        flow_turning_positive=snapshot.obv_trend != "下降",
    )


def _valuation_from_v4(valuation: ValuationResult, risk_score: int) -> ValuationData:
    support = valuation.valuation_label in {"明显低估", "相对便宜", "合理"}
    target = 18 if support else 8
    if isinstance(valuation.current_metrics.get("target_upside_pct"), (int, float)):
        target = float(valuation.current_metrics["target_upside_pct"])
    return ValuationData(
        opportunity_score=max(0, min(100, valuation.valuation_score + 20 if support else valuation.valuation_score)),
        risk_score=max(0, min(100, risk_score)),
        valuation_support=support,
        target_upside_pct=target,
        downside_pct=max(6, risk_score / 10),
        fundamental_intact=valuation.valuation_label != "数据不足",
    )


def _signal_fingerprint(result: TradeFilterResult) -> str:
    record = result.signal_record
    parts = (
        record.symbol,
        record.grade,
        record.decision,
        record.event_fingerprint,
        record.buy_zone,
        str(round(record.entry, 2)),
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _stable_id(symbol: str, text: str) -> str:
    return hashlib.sha256(f"{symbol}:{text}".encode("utf-8")).hexdigest()
