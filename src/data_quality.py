from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Generic, TypeVar

UTC = timezone.utc
T = TypeVar("T")


class ProviderState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    PLACEHOLDER = "PLACEHOLDER"


@dataclass(frozen=True)
class ProviderStatus:
    status: ProviderState
    source: str
    source_url: str
    fetched_at: datetime
    data_timestamp: datetime | None
    freshness: str
    confidence: int
    error: str | None = None
    is_fallback: bool = False


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    data: T | None
    meta: ProviderStatus


@dataclass(frozen=True)
class DataQualityResult:
    score: int
    confidence: int
    missing_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    providers: tuple[ProviderStatus, ...] = field(default_factory=tuple)


def provider_status(
    *,
    status: ProviderState,
    source: str,
    source_url: str,
    data_timestamp: datetime | None,
    confidence: int,
    error: str | None = None,
    is_fallback: bool = False,
) -> ProviderStatus:
    now = datetime.now(UTC)
    if data_timestamp is None:
        freshness = "数据时间不可用"
    else:
        seconds = max(0, int((now - data_timestamp.astimezone(UTC)).total_seconds()))
        freshness = f"{seconds}秒前"
    return ProviderStatus(
        status=status,
        source=source,
        source_url=source_url,
        fetched_at=now,
        data_timestamp=data_timestamp,
        freshness=freshness,
        confidence=max(0, min(100, confidence)),
        error=error,
        is_fallback=is_fallback,
    )


def placeholder_status(source: str, reason: str) -> ProviderStatus:
    return provider_status(
        status=ProviderState.PLACEHOLDER,
        source=source,
        source_url="",
        data_timestamp=None,
        confidence=0,
        error=reason,
    )


def evaluate_data_quality(
    required_fields: dict[str, object],
    providers: list[ProviderStatus],
) -> DataQualityResult:
    missing = tuple(name for name, value in required_fields.items() if value is None)
    field_coverage = 1 - len(missing) / max(1, len(required_fields))
    active = [provider for provider in providers if provider.status != ProviderState.PLACEHOLDER]
    provider_confidence = (
        sum(provider.confidence for provider in active) / len(active) if active else 0
    )
    penalties = sum(
        20 if provider.status == ProviderState.UNAVAILABLE else
        12 if provider.status == ProviderState.STALE else
        7 if provider.status == ProviderState.DEGRADED else 0
        for provider in providers
    )
    score = round(field_coverage * 65 + provider_confidence * 0.35 - penalties)
    warnings = tuple(
        f"{provider.source}：{provider.status.value}"
        + (f"（{provider.error}）" if provider.error else "")
        for provider in providers
        if provider.status != ProviderState.HEALTHY
    )
    return DataQualityResult(
        score=max(0, min(100, score)),
        confidence=max(0, min(100, round(provider_confidence - len(missing) * 4))),
        missing_fields=missing,
        warnings=warnings,
        providers=tuple(providers),
    )
