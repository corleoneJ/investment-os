from __future__ import annotations

import hashlib
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
            "version": 2,
            "alerts": {},
            "news_hashes": {},
            "events": {},
            "decision_fingerprints": {},
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

    def upsert_event(
        self,
        *,
        event_id: str,
        kind: str,
        title: str,
        source: str,
        source_url: str,
        event_time: datetime,
        assets: tuple[str, ...],
        category: str,
        workflow: str,
        is_major: bool = True,
        is_negative: bool = False,
    ) -> dict[str, Any]:
        """不同工作流用同一 event_id 补充事件，不重复创建或重复通知。"""
        now = datetime.now(UTC)
        events = self.data.setdefault("events", {})
        previous = events.get(event_id, {})
        workflows = sorted({*previous.get("workflows", []), workflow})
        combined_assets = sorted({*previous.get("assets", []), *assets})
        entry = {
            **previous,
            "event_id": event_id,
            "kind": kind,
            "title": title or previous.get("title", "数据暂不可用"),
            "source": source or previous.get("source", "数据暂不可用"),
            "source_url": source_url or previous.get("source_url", ""),
            "event_time": event_time.astimezone(UTC).isoformat(),
            "assets": combined_assets,
            "category": category,
            "workflows": workflows,
            "is_major": bool(is_major or previous.get("is_major")),
            "is_negative": bool(is_negative or previous.get("is_negative")),
            "first_seen": previous.get("first_seen", now.isoformat()),
            "last_seen": now.isoformat(),
            "notified": bool(previous.get("notified", False)),
        }
        events[event_id] = entry
        self._prune(now)
        return entry

    def mark_events_notified(self, event_ids: list[str], now: datetime) -> None:
        for event_id in event_ids:
            entry = self.data.setdefault("events", {}).get(event_id)
            if entry:
                entry["notified"] = True
                entry["notified_at"] = now.astimezone(UTC).isoformat()
        self._prune(now)

    def decision_is_duplicate(self, asset: str, fingerprint: str) -> bool:
        return self.data.setdefault("decision_fingerprints", {}).get(asset, {}).get(
            "fingerprint"
        ) == fingerprint

    def record_decision_fingerprint(
        self, asset: str, fingerprint: str, now: datetime
    ) -> None:
        self.data.setdefault("decision_fingerprints", {})[asset] = {
            "fingerprint": fingerprint,
            "sent_at": now.astimezone(UTC).isoformat(),
        }

    def cached_news(self, now: datetime | None = None) -> list:
        from .news import NewsItem

        current = (now or datetime.now(UTC)).astimezone(UTC)
        items = []
        for entry in self.data.get("events", {}).values():
            event_time = parse_datetime(entry.get("event_time"))
            if entry.get("kind") != "news" or current - event_time > timedelta(days=7):
                continue
            items.append(
                NewsItem(
                    title=entry.get("title", "数据暂不可用"),
                    source=entry.get("source", "共享事件状态"),
                    published_at=event_time,
                    url=entry.get("source_url", ""),
                    assets=tuple(entry.get("assets", [])),
                    category=entry.get("category", "共享事件"),
                    is_major=bool(entry.get("is_major", False)),
                    is_negative=bool(entry.get("is_negative", False)),
                )
            )
        return sorted(items, key=lambda item: item.published_at, reverse=True)

    def cached_future_events(self, now: datetime | None = None) -> list:
        from .future_events import FutureEvent

        current = (now or datetime.now(UTC)).astimezone(UTC)
        items = []
        for entry in self.data.get("events", {}).values():
            event_time = parse_datetime(entry.get("event_time"))
            if entry.get("kind") != "future" or not current <= event_time <= current + timedelta(days=7):
                continue
            items.append(
                FutureEvent(
                    name=entry.get("title", "数据暂不可用"),
                    event_time=event_time,
                    source=entry.get("source", "共享事件状态"),
                    assets=tuple(entry.get("assets", [])),
                    expected_impact=entry.get("category", "事件可能放大波动"),
                    url=entry.get("source_url", ""),
                )
            )
        return sorted(items, key=lambda item: item.event_time)

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
        event_cutoff = now.astimezone(UTC) - timedelta(days=30)
        self.data["events"] = {
            key: value for key, value in self.data.get("events", {}).items()
            if parse_datetime(value.get("last_seen")) >= event_cutoff
        }


def stable_event_id(*parts: str) -> str:
    normalized = "|".join(" ".join(str(part).strip().lower().split()) for part in parts)
    return "evt_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
