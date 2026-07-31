from __future__ import annotations

from dataclasses import dataclass

from .industry_analyzer import IndustryAnalyzer, IndustryImpact
from .news import NewsItem

POSITIVE_TERMS = (
    "beat", "raises guidance", "record revenue", "growth", "inflow", "increase capex",
    "超预期", "上调指引", "增长", "资金流入", "增加资本开支",
)


@dataclass(frozen=True)
class EventImpact:
    item: NewsItem
    level: int
    direction: str
    industry: IndustryImpact
    fact: str
    inference: str

    @property
    def stars(self) -> str:
        return "★" * self.level + "☆" * (5 - self.level)


class EventAnalyzer:
    def __init__(self, industry_analyzer: IndustryAnalyzer) -> None:
        self.industry_analyzer = industry_analyzer

    def analyze_all(self, news: list[NewsItem]) -> list[EventImpact]:
        return [self.analyze(item) for item in news if item.is_major]

    def analyze(self, item: NewsItem) -> EventImpact:
        title = item.title.lower()
        official = item.source in {"美国 SEC EDGAR", "美联储", "美国劳工统计局"}
        level = 5 if official and any(term in title for term in ("10-q", "10-k", "fomc", "cpi")) else 4
        if not official:
            level = 4 if any(term in title for term in ("earnings", "guidance", "capex", "fomc")) else 3
        direction = (
            "负面"
            if item.is_negative
            else "正面"
            if any(term in title for term in POSITIVE_TERMS)
            else "方向待确认"
        )
        industry = self.industry_analyzer.analyze(item)
        return EventImpact(
            item=item,
            level=level,
            direction=direction,
            industry=industry,
            fact=f"{item.source} 已发布：{item.title}",
            inference=(
                f"推测影响将沿“{' → '.join(industry.chain)}”传导；"
                f"当前方向为{direction}，需由原文和后续价格确认。"
            ),
        )
