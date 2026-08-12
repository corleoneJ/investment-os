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
        fingerprint = "{}:{}:{}:{}:{}".format(
            record.symbol,
            record.grade,
            record.decision,
            record.event_fingerprint,
            record.buy_zone,
        )
        previous: Optional[SignalRecord] = self._last_by_symbol.get(record.symbol)
        if previous is None:
            allowed = record.grade == "S" or record.decision in (
                "BUY",
                "ADD",
                "EXIT",
                "AVOID",
            ) or record.grade == "A"
            if allowed:
                self._last_by_symbol[record.symbol] = record
            return AlertDecision(allowed, "首次出现可推送机会" if allowed else "B/C级不推送", fingerprint)

        transitions = {
            ("WATCH", "BUY"),
            ("BUY", "ADD"),
            ("BUY", "EXIT"),
        }
        upgraded = previous.grade == "A" and record.grade == "S"
        risk_jump = record.risk_score - previous.risk_score >= 20
        new_substance = (
            record.event_fingerprint
            and record.event_fingerprint != previous.event_fingerprint
        )
        new_buy_zone = record.buy_zone and record.buy_zone != previous.buy_zone
        transition = (previous.decision, record.decision) in transitions
        allowed = upgraded or risk_jump or new_substance or new_buy_zone or transition
        if allowed:
            self._last_by_symbol[record.symbol] = record
        return AlertDecision(
            allowed,
            "状态升级或出现新实质信息" if allowed else "同一决策指纹，抑制推送",
            fingerprint,
        )

