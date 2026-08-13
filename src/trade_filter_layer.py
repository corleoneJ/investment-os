"""Investment OS V5 orchestration: noise → impact → timing → alertability."""

from dataclasses import dataclass
from datetime import datetime

from src.alert_filtering import SignalRecord
from src.early_opportunity import EarlyOpportunityDetector, EarlyOpportunityResult
from src.entry_timing import EntryTimingDecision, EntryTimingEngine
from src.feishu_signal_formatter import V5Signal, format_signal
from src.final_action import FinalActionDecision, FinalActionResolver
from src.market_impact_engine import MarketImpactEngine, MarketImpactResult
from src.models import ScoringBreakdown, TradeContext
from src.noise_filter import NoiseFilter, NoiseFilterResult
from src.price_reaction import PriceReactionAnalyzer, PriceReactionResult
from src.risk_reward import RiskRewardEngine, RiskRewardPlan
from src.trade_grade import TradeGradeEngine, TradeGradeResult


@dataclass(frozen=True)
class TradeFilterResult:
    noise: NoiseFilterResult
    impact: MarketImpactResult
    reaction: PriceReactionResult
    risk_reward: RiskRewardPlan
    entry: EntryTimingDecision
    grade: TradeGradeResult
    early: EarlyOpportunityResult
    scoring: ScoringBreakdown
    final_action: FinalActionDecision
    should_send_feishu: bool
    feishu_message: str
    signal_record: SignalRecord


class TradeFilterLayer:
    def __init__(self, noise_filter: NoiseFilter = None):
        self.noise_filter = noise_filter or NoiseFilter()
        self.impact_engine = MarketImpactEngine()
        self.reaction_analyzer = PriceReactionAnalyzer()
        self.rr_engine = RiskRewardEngine()
        self.entry_engine = EntryTimingEngine()
        self.grade_engine = TradeGradeEngine()
        self.early_detector = EarlyOpportunityDetector()
        self.final_action_resolver = FinalActionResolver()

    def evaluate(self, context: TradeContext, now: datetime = None) -> TradeFilterResult:
        noise = self.noise_filter.evaluate(context.event, now)
        impact = self.impact_engine.evaluate(context.event)
        reaction = self.reaction_analyzer.evaluate(context.market)
        rr = self.rr_engine.plan(context.market, context.valuation)
        entry = self.entry_engine.evaluate(
            impact,
            reaction,
            context.market,
            context.flow,
            context.valuation,
            rr,
        )
        early = self.early_detector.evaluate(context)
        grade = self.grade_engine.evaluate(
            impact,
            entry,
            rr,
            context.flow,
            context.data_quality,
        )
        if early.signal == "EARLY_ALPHA" and grade.grade in ("B", "C"):
            grade = TradeGradeResult("A", early.reason, True)
            if entry.status in ("WAIT", "WATCH"):
                entry = EntryTimingDecision(
                    "WATCH",
                    "EARLY_ALPHA",
                    max(entry.opportunity_score, early.early_event_score),
                    entry.risk_score,
                    "潜在补涨机会，先进入A级机会池，等待技术确认。",
                    "继续观察",
                    entry.reasons + [early.reason],
                )

        final_action = self.final_action_resolver.resolve(
            grade,
            entry,
            impact,
            reaction,
            rr,
            context.flow,
            context.market,
            context.valuation,
            context.data_quality,
        )
        scoring = self._scoring(context, impact, reaction, entry, rr)
        signal = V5Signal(
            context,
            grade,
            entry,
            final_action,
            impact,
            reaction,
            rr,
            self._risks(context, reaction, rr),
            rr.invalidation_reason,
        )
        should_send = not noise.is_noise and final_action.final_action == "BUY"
        record = SignalRecord(
            context.event.event_id,
            context.event.symbol,
            (now or datetime.now()).isoformat(),
            context.market.price,
            grade.grade,
            final_action.final_action,
            impact.impact_score,
            entry.opportunity_score,
            entry.risk_score,
            rr.entry_price,
            rr.stop_loss,
            (rr.target_1, rr.target_2),
            entry.core_conclusion,
            context.event.title.lower(),
            entry.entry_model,
        )
        return TradeFilterResult(
            noise,
            impact,
            reaction,
            rr,
            entry,
            grade,
            early,
            scoring,
            final_action,
            should_send,
            format_signal(signal, now) if should_send else "",
            record,
        )

    @staticmethod
    def _risks(context, reaction, rr):
        risks = []
        if reaction.priced_in_score >= 60:
            risks.append("价格已有较强反应，禁止追高。")
        if not context.flow.confirmed:
            risks.append("资金确认不足。")
        if rr.risk_reward_ratio < 2.0:
            risks.append("盈亏比不足。")
        if context.valuation.risk_score > 60:
            risks.append("风险评分偏高。")
        return risks or [
            "若跌破止损结构，事件驱动判断失效。",
            "若成交量和VWAP确认消失，说明资金确认可能失效。",
            "若催化剂被公告或后续数据证伪，需要撤销BUY判断。",
        ]

    @staticmethod
    def _scoring(context, impact, reaction, entry, rr):
        return ScoringBreakdown(
            {
                "事件": int(impact.impact_score * 0.25),
                "产业链": int(context.event.industry_impact * 0.2),
                "资金": 12 if context.flow.confirmed else -8,
                "估值": 8 if context.valuation.valuation_support else 0,
                "技术": 9 if entry.entry_model in ("WAIT_FOR_PULLBACK", "BREAKOUT_BUY") else 0,
                "过热": -7 if reaction.is_overheated else 0,
                "风险收益": 8 if rr.risk_reward_ratio >= 2.0 else -10,
                "财报风险": -5 if context.valuation.risk_score > 60 else 0,
            }
        )
