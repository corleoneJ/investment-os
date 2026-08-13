"""Smart anti-spam layer based on decision fingerprints."""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class SignalRecord:
    signal_id: str
    symbol: str
    time: str
    price: float
    grade: str
    decision: str
    impact_score: int
    opportunity_score: int
    risk_score: int
    entry: float
    stop: float
    targets: tuple
    reason: str
    event_fingerprint: str = ""
    buy_zone: str = ""


@dataclass(frozen=True)
class AlertDecision:
    should_push: bool
    reason: str
    fingerprint: str


class AlertFilter:
    def __init__(self):
        self._last_by_symbol: Dict[str, SignalRecord] = {}

    def should_push(self, record: SignalRecord) -> AlertDecision:
        if record.decision != "BUY":
            return AlertDecision(False, "当前阶段只推送FINAL_ACTION=BUY", "")
        fingerprint = "{}:{}:{}:{}:{}".format(
            record.symbol,
            record.grade,
            record.decision,
            record.event_fingerprint,
            record.buy_zone,
        )
        previous: Optional[SignalRecord] = self._last_by_symbol.get(record.symbol)
        if previous is None:
            self._last_by_symbol[record.symbol] = record
            return AlertDecision(True, "首次出现BUY信号", fingerprint)

        new_substance = (
            record.event_fingerprint
            and record.event_fingerprint != previous.event_fingerprint
        )
        new_buy_zone = record.buy_zone and record.buy_zone != previous.buy_zone
        allowed = new_substance or new_buy_zone
        if allowed:
            self._last_by_symbol[record.symbol] = record
        return AlertDecision(
            allowed,
            "状态升级或出现新实质信息" if allowed else "同一决策指纹，抑制推送",
            fingerprint,
        )
