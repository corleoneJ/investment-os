"""Risk/reward planning with dynamic stop logic."""

from dataclasses import dataclass

from src.models import MarketData, ValuationData


@dataclass(frozen=True)
class RiskRewardPlan:
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward_ratio: float
    stop_type: str
    stop_price: float
    stop_percent: float
    invalidation_reason: str


class RiskRewardEngine:
    def plan(self, market: MarketData, valuation: ValuationData) -> RiskRewardPlan:
        entry = market.price
        stop_candidates = []
        if market.atr:
            stop_candidates.append(("ATR止损", entry - market.atr * 1.5))
        if market.support:
            stop_candidates.append(("技术支撑止损", market.support * 0.985))
        if market.ema20:
            stop_candidates.append(("EMA20失效", market.ema20 * 0.985))
        if market.recent_low:
            stop_candidates.append(("前低失效", market.recent_low * 0.99))
        if not stop_candidates:
            stop_candidates.append(("事件逻辑失效", entry * 0.94))

        stop_type, stop = max(
            (item for item in stop_candidates if item[1] < entry),
            key=lambda item: item[1],
            default=("事件逻辑失效", entry * 0.94),
        )
        target_1 = (
            market.resistance
            if market.resistance and market.resistance > entry
            else entry * (1 + max(0.08, valuation.target_upside_pct / 200.0))
        )
        target_2 = (
            max(target_1, entry * (1 + valuation.target_upside_pct / 100.0))
            if valuation.target_upside_pct > 0
            else entry * 1.15
        )
        risk = max(0.01, entry - stop)
        reward = max(0.01, target_2 - entry)
        ratio = round(reward / risk, 2)
        stop_percent = round((stop / entry - 1.0) * 100.0, 2)
        reason = "{}：价格跌破关键结构后，事件驱动判断失效。".format(stop_type)
        return RiskRewardPlan(
            entry,
            round(stop, 2),
            round(target_1, 2),
            round(target_2, 2),
            ratio,
            stop_type,
            round(stop, 2),
            stop_percent,
            reason,
        )
