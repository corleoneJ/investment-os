from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .decision_engine import AssetDecision, DecisionReport
from .feishu import FeishuClient
from .market_data import MarketSnapshot
from .state import StateStore

LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
BEIJING = ZoneInfo("Asia/Shanghai")


class AlertManager:
    """V3 观察阶段：不做冷却、不做评分门槛，每个资产决策全部发送。"""

    def __init__(self, feishu: FeishuClient, state: StateStore) -> None:
        self.feishu = feishu
        self.state = state

    def deliver(
        self,
        report: DecisionReport,
        snapshots: dict[str, MarketSnapshot],
        dry_run: bool = False,
    ) -> tuple[int, int]:
        if not dry_run and not self.feishu.configured:
            LOGGER.warning("未配置 FEISHU_WEBHOOK：V3分析已完成，全部消息跳过发送。")
            return 0, len(report.decisions)
        sent = 0
        failed = 0
        now = datetime.now(UTC)
        for decision in report.decisions:
            message = format_ai_message(decision, snapshots[decision.asset])
            if dry_run:
                LOGGER.info(
                    "演练模式生成：%s｜机会%d｜风险%d｜%s",
                    decision.asset,
                    decision.opportunity.score,
                    decision.risk.score,
                    decision.action,
                )
                sent += 1
                continue
            if self.feishu.send(message):
                sent += 1
                self.state.record_alert(
                    decision.asset,
                    "AI决策",
                    max(decision.opportunity.score, decision.risk.score),
                    now,
                    decision.summary,
                )
            else:
                failed += 1
        self.state.save()
        return sent, failed


def format_ai_message(decision: AssetDecision, snapshot: MarketSnapshot) -> str:
    event_text = (
        f"{decision.event.stars}｜{decision.event.fact}\n"
        f"事实/推测：{decision.event.inference}"
        if decision.event
        else "暂未发现可确认的重大事件；当前判断主要来自行情与技术面。"
    )
    beneficiaries = "、".join(decision.industry.beneficiaries) or "暂未确认"
    victims = "、".join(decision.industry.victims) or "暂未确认"
    future = (
        "；".join(
            f"{event.event_time.astimezone(BEIJING):%m-%d %H:%M} {event.name}"
            for event in decision.future_events[:3]
        )
        or "未来7天暂未取得可确认事件"
    )
    technical = (
        f"价格 {_price(None if snapshot.error else snapshot.price)}；"
        f"EMA20/60/200={_price(snapshot.ema20)}/{_price(snapshot.ema60)}/{_price(snapshot.ema200)}；"
        f"RSI={_number(snapshot.rsi)}；MACD柱={_number(snapshot.macd_histogram)}；"
        f"ATR占比={_pct(snapshot.atr_pct)}；成交量={snapshot.volume_state}。"
    )
    return f"""【Investment OS AI】
★★★★★ {decision.dominant_label}

资产：
{decision.asset}

原因：
{decision.cause.primary_cause}
方向：{decision.cause.direction}｜原因可信度：{decision.cause.confidence}/100

AI分析：
{decision.cause.analysis}
技术面：{technical}

产业链：
主题：{decision.industry.theme}
传导：{" → ".join(decision.industry.chain)}
真正可能受益：{beneficiaries}
真正可能受损：{victims}
产业链判断可信度：{decision.industry.confidence}/100

事件：
{event_text}
未来事件：{future}

风险：
{decision.risk.score}/100
{"；".join(decision.risk.reasons)}

机会：
{decision.opportunity.score}/100
{"；".join(decision.opportunity.reasons)}

执行建议：
{decision.action}

AI一句总结：
{decision.summary}

风险提示：本系统只做辅助分析，不构成收益保证。"""


def _price(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:,.2f}"


def _number(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:.2f}"


def _pct(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:.2f}%"
