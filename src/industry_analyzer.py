from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .news import NewsItem


@dataclass(frozen=True)
class IndustryImpact:
    theme: str
    industries: tuple[str, ...]
    chain: tuple[str, ...]
    beneficiaries: tuple[str, ...]
    victims: tuple[str, ...]
    confidence: int


class IndustryAnalyzer:
    def __init__(self, config: dict[str, Any]) -> None:
        self.themes = config.get("themes", {})
        self.asset_roles = config.get("asset_roles", {})

    def analyze(self, item: NewsItem) -> IndustryImpact:
        text = f"{item.title} {item.category}".lower()
        matches: list[tuple[int, dict[str, Any]]] = []
        for theme in self.themes.values():
            hits = sum(1 for keyword in theme.get("keywords", []) if keyword.lower() in text)
            if hits:
                matches.append((hits, theme))
        if not matches:
            return IndustryImpact(
                theme="影响链尚不明确",
                industries=("待确认",),
                chain=("事件事实", "市场预期", "资产价格"),
                beneficiaries=(),
                victims=(),
                confidence=30,
            )
        hits, selected = max(matches, key=lambda match: match[0])
        beneficiaries = tuple(selected.get("beneficiaries", ()))
        victims = beneficiaries if item.is_negative else ()
        return IndustryImpact(
            theme=selected.get("name", "未分类事件"),
            industries=tuple(selected.get("industries", ())),
            chain=tuple(selected.get("chain", ())),
            beneficiaries=() if item.is_negative else beneficiaries,
            victims=victims,
            confidence=min(90, 55 + hits * 10 + (10 if item.source == "美国 SEC EDGAR" else 0)),
        )

    def role(self, asset: str) -> str:
        return self.asset_roles.get(asset, "全球资本市场资产")
