from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

V4_ACTIONS = {
    "继续定投", "继续持有", "等待资金确认", "等待回踩",
    "按计划小额分批", "不追高", "暂缓新增", "排除候选",
}


@dataclass(frozen=True)
class ScoreContribution:
    component: str
    weight: int
    raw_score: int
    weighted_points: float
    explanation: str


@dataclass(frozen=True)
class InvestmentScoreResult:
    symbol: str
    opportunity_score: int
    risk_score: int
    investment_score: int
    confidence_score: int
    data_quality_score: int
    contributions: tuple[ScoreContribution, ...]
    action: str
    conclusion: str


class InvestmentScoreCalculator:
    def __init__(self, weights: dict[str, int]) -> None:
        self.weights = weights
        self.validate_weights(weights)

    @classmethod
    def from_yaml(cls, path: str | Path) -> InvestmentScoreCalculator:
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    @staticmethod
    def validate_weights(weights: dict[str, int]) -> None:
        if sum(weights.values()) != 100:
            raise ValueError(f"评分权重总和必须为100，当前为{sum(weights.values())}")
        if any(not isinstance(value, int) or value < 0 for value in weights.values()):
            raise ValueError("评分权重必须是非负整数")

    def calculate(
        self,
        symbol: str,
        components: dict[str, int | None],
        opportunity_score: int,
        risk_score: int,
        confidence_score: int,
        data_quality_score: int,
        flow_score: int,
    ) -> InvestmentScoreResult:
        values = dict(components)
        values["risk_control"] = 100 - risk_score
        values["data_quality"] = data_quality_score
        contributions: list[ScoreContribution] = []
        total = 0.0
        for component, weight in self.weights.items():
            value = values.get(component)
            raw = max(0, min(100, int(value))) if value is not None else 0
            points = weight * raw / 100
            total += points
            if value is None:
                explanation = f"{_label(component)}数据缺失，损失最多{weight}分"
            elif raw >= 70:
                explanation = f"{_label(component)} +{points:.1f}"
            elif raw < 40:
                lost = weight - points
                explanation = f"{_label(component)}偏弱，未获得{lost:.1f}分"
            else:
                explanation = f"{_label(component)} +{points:.1f}"
            contributions.append(
                ScoreContribution(component, weight, raw, round(points, 2), explanation)
            )
        investment = max(0, min(100, round(total)))
        action, conclusion = decision_matrix(
            symbol, opportunity_score, risk_score, data_quality_score, flow_score
        )
        return InvestmentScoreResult(
            symbol=symbol,
            opportunity_score=max(0, min(100, opportunity_score)),
            risk_score=max(0, min(100, risk_score)),
            investment_score=investment,
            confidence_score=max(0, min(100, confidence_score)),
            data_quality_score=max(0, min(100, data_quality_score)),
            contributions=tuple(contributions),
            action=action,
            conclusion=conclusion,
        )


def decision_matrix(
    symbol: str,
    opportunity: int,
    risk: int,
    data_quality: int,
    flow: int,
) -> tuple[str, str]:
    if data_quality < 40:
        return "暂缓新增", "数据质量不足，不给方向性结论。"
    if opportunity >= 70 and risk < 40:
        return "按计划小额分批", "高机会、低风险，但仍只按每日预算小额分批。"
    if opportunity >= 70 and risk < 70:
        action = "等待资金确认" if flow < 60 else "等待回踩"
        return action, f"高机会、中风险，{action}。"
    if opportunity >= 70 and risk >= 70:
        return "不追高", "高机会、高风险，不宜追高，等待风险释放。"
    if opportunity >= 45 and risk < 40:
        action = "继续定投" if symbol in {"BTC-USD", "QQQ"} else "继续持有"
        return action, "中等机会、低风险，不因榜单变化频繁交易。"
    if opportunity < 45 and risk >= 70:
        return "暂缓新增", "低机会、高风险，暂缓新增。"
    if risk >= 55:
        return "等待回踩", "风险尚未充分释放，等待更好的技术位置。"
    if flow < 45:
        return "等待资金确认", "方向尚可但资金未确认。"
    return "继续持有", "机会和风险均不极端，维持长期观察。"


def _label(component: str) -> str:
    labels = {
        "event_catalyst": "事件催化", "industry_benefit": "产业链受益",
        "fundamental_quality": "基本面质量", "earnings_momentum": "盈利动量",
        "capital_flow": "资金确认", "valuation": "估值",
        "technical_setup": "技术位置", "macro_environment": "宏观环境",
        "risk_control": "风险控制", "data_quality": "数据质量",
    }
    return labels.get(component, component)
