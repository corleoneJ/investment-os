from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc


class StateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {
            "version": 1,
            "alerts": {},
            "news_hashes": {},
            "history": [],
        }

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, json.JSONDecodeError):
            # 损坏的状态不能阻断监控；保留空状态并由本次安全重建。
            return

    def should_send_alert(
        self,
        asset: str,
        alert_type: str,
        strength: float,
        now: datetime,
        cooldown_minutes: int = 60,
        strengthening_ratio: float = 1.2,
        strengthening_points: float = 1.0,
    ) -> bool:
        previous = self.data["alerts"].get(f"{asset}:{alert_type}")
        if not previous:
            return True
        sent_at = parse_datetime(previous.get("sent_at"))
        if now - sent_at >= timedelta(minutes=cooldown_minutes):
            return True
        previous_strength = float(previous.get("strength", 0))
        required = max(previous_strength * strengthening_ratio, previous_strength + strengthening_points)
        return strength >= required

    def record_alert(
        self,
        asset: str,
        alert_type: str,
        strength: float,
        now: datetime,
        summary: str,
    ) -> None:
        self.data["alerts"][f"{asset}:{alert_type}"] = {
            "sent_at": now.astimezone(UTC).isoformat(),
            "strength": strength,
        }
        self.data["history"].append(
            {
                "time": now.astimezone(UTC).isoformat(),
                "asset": asset,
                "type": alert_type,
                "summary": summary,
            }
        )
        self._prune(now)

    def record_v4_decision(
        self,
        asset: str,
        now: datetime,
        price: float | None,
        investment_score: int,
        opportunity_score: int,
        risk_score: int,
        data_quality_score: int,
        action: str,
        summary: str,
    ) -> None:
        """保存可用于每日复盘的早期判断，不承担发送限流职责。"""
        self.data["history"].append(
            {
                "time": now.astimezone(UTC).isoformat(),
                "asset": asset,
                "type": "V4决策",
                "price": price,
                "investment_score": investment_score,
                "opportunity_score": opportunity_score,
                "risk_score": risk_score,
                "data_quality_score": data_quality_score,
                "action": action,
                "summary": summary,
            }
        )
        self._prune(now)

    def news_seen(self, fingerprint: str) -> bool:
        return fingerprint in self.data["news_hashes"]

    def record_news(self, fingerprint: str, now: datetime) -> None:
        self.data["news_hashes"][fingerprint] = now.astimezone(UTC).isoformat()
        self._prune(now)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary, self.path)

    def _prune(self, now: datetime) -> None:
        history_cutoff = now.astimezone(UTC) - timedelta(days=14)
        news_cutoff = now.astimezone(UTC) - timedelta(days=30)
        self.data["history"] = [
            item for item in self.data["history"]
            if parse_datetime(item.get("time")) >= history_cutoff
        ][-1000:]
        self.data["news_hashes"] = {
            key: value for key, value in self.data["news_hashes"].items()
            if parse_datetime(value) >= news_cutoff
        }


def parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
