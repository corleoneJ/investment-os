from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .news import NewsItem


@dataclass(frozen=True)
class GraphImpact:
    event_id: str
    industry: str
    business_segment: str
    symbol: str
    direction: str
    weight: float
    lag_days: tuple[int, int]
    path: tuple[str, ...]
    hypothesis: str


class IndustryGraph:
    def __init__(self, config: dict[str, Any]) -> None:
        self.events = config.get("events", {})

    @classmethod
    def from_yaml(cls, path: str | Path) -> IndustryGraph:
        config = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(config)

    def match(self, item: NewsItem) -> list[GraphImpact]:
        text = f"{item.title} {item.category}".lower()
        impacts: list[GraphImpact] = []
        for event_id, event in self.events.items():
            if not any(keyword.lower() in text for keyword in event.get("keywords", [])):
                continue
            for segment, relation in event.get("beneficiaries", {}).items():
                for symbol in relation.get("symbols", []):
                    direction = "负向影响假设" if item.is_negative else "正向影响假设"
                    lag = tuple(relation.get("lag_days", [0, 0]))
                    impacts.append(
                        GraphImpact(
                            event_id=event_id,
                            industry=event.get("industry", "未分类"),
                            business_segment=segment,
                            symbol=symbol,
                            direction=direction,
                            weight=float(relation.get("weight", 0)),
                            lag_days=(int(lag[0]), int(lag[-1])),
                            path=(item.title, event.get("industry", "未分类"), segment, symbol),
                            hypothesis=event.get("hypothesis", "产业链关系暂无法验证。"),
                        )
                    )
        return impacts

    def impacts_for_news(self, news: list[NewsItem]) -> list[GraphImpact]:
        return [impact for item in news for impact in self.match(item)]

    def validate_symbols(self, allowed_symbols: set[str]) -> list[str]:
        errors: list[str] = []
        for event_id, event in self.events.items():
            for segment, relation in event.get("beneficiaries", {}).items():
                for symbol in relation.get("symbols", []):
                    if symbol not in allowed_symbols:
                        errors.append(f"{event_id}.{segment} 引用了候选池外标的 {symbol}")
                weight = float(relation.get("weight", 0))
                if not 0 <= weight <= 1:
                    errors.append(f"{event_id}.{segment} 权重必须位于0到1")
        return errors
