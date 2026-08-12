"""Noise Filter: keep non-tradable information out of alerts."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Set

from src.models import Event


@dataclass(frozen=True)
class NoiseFilterResult:
    event_id: str
    is_noise: bool
    noise_score: int
    reason: str
    source_quality: str
    freshness: str
    duplication_status: str


class NoiseFilter:
    """Rule-based event filter.

    Scores >= 70 are considered noise and must not enter Feishu.
    """

    weak_patterns = (
        "partnership",
        "collaboration",
        "product update",
        "minor order",
        "small order",
        "management says",
        "price target",
        "target price",
        "initiates coverage",
        "maintains rating",
        "multimedia",
        "video",
        "podcast",
        "rumor",
        "unconfirmed",
        "could",
        "may",
    )

    def __init__(self):
        self._seen: Set[str] = set()

    def evaluate(
        self, event: Event, now: Optional[datetime] = None
    ) -> NoiseFilterResult:
        current = now or datetime.now(timezone.utc)
        score = 0
        reasons = []
        title = event.title.lower()

        if not event.source:
            score += 35
            reasons.append("来源缺失")
            source_quality = "LOW"
        elif event.source_quality_hint == "low":
            score += 25
            reasons.append("来源质量偏低")
            source_quality = "LOW"
        else:
            source_quality = "HIGH" if event.source_quality_hint == "high" else "NORMAL"

        if event.published_at is None:
            score += 35
            reasons.append("缺少明确时间戳")
            freshness = "UNKNOWN"
        else:
            published = event.published_at
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            age_hours = (
                current.astimezone(timezone.utc) - published.astimezone(timezone.utc)
            ).total_seconds() / 3600.0
            if age_hours > 72:
                score += 35
                reasons.append("旧消息，可能已充分定价")
                freshness = "STALE"
            elif age_hours > 24:
                score += 15
                reasons.append("新鲜度下降")
                freshness = "AGING"
            else:
                freshness = "FRESH"

        if event.duplicate_of or event.event_id in self._seen:
            score += 70
            reasons.append("重复新闻")
            duplication_status = "DUPLICATE"
        else:
            duplication_status = "UNIQUE"

        if any(pattern in title for pattern in self.weak_patterns):
            score += 30
            reasons.append("标题交易价值弱或疑似标题党")

        if event.previously_priced:
            score += 30
            reasons.append("市场可能已经充分定价")

        if (
            event.revenue_impact
            + event.profit_impact
            + event.guidance_impact
            + event.supply_demand_impact
            + event.industry_impact
        ) < 20:
            score += 20
            reasons.append("与收入利润关系较弱")

        score = max(0, min(100, score))
        is_noise = score >= 70
        if not is_noise:
            self._seen.add(event.event_id)
        return NoiseFilterResult(
            event.event_id,
            is_noise,
            score,
            "；".join(reasons) if reasons else "具备继续评估价值",
            source_quality,
            freshness,
            duplication_status,
        )
