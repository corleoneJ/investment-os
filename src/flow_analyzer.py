from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .data_quality import ProviderState, ProviderStatus, placeholder_status
from .market_data import MarketSnapshot

FLOW_LABELS = {
    "增量资金确认",
    "资金流入但持续性待验证",
    "可能是空头回补",
    "可能是事件型追涨",
    "资金未确认",
    "资金流出",
    "数据不足",
}


@dataclass(frozen=True)
class FlowResult:
    symbol: str
    flow_score: int
    flow_direction: str
    volume_confirmation: str
    relative_volume: float | None
    obv_trend: str
    vwap_position: str
    etf_flow: str
    institutional_change: str
    insider_activity: str
    short_interest: str
    options_signal: str
    likely_driver: str
    confidence: int
    source_times: dict[str, str]
    warnings: tuple[str, ...]
    providers: tuple[ProviderStatus, ...]


class FlowAnalyzer:
    def analyze(self, snapshot: MarketSnapshot) -> FlowResult:
        placeholders = (
            placeholder_status("ETF申购赎回", "未接入稳定的免费公开接口"),
            placeholder_status("13F机构持仓", "季度滞后数据未接入，不能描述今日机构行为"),
            placeholder_status("内部人交易", "尚未解析Form 4明细"),
            placeholder_status("空头与期权", "免费实时数据暂不可用"),
        )
        provider = snapshot.provider
        providers = tuple(item for item in (provider, *placeholders) if item is not None)
        if snapshot.error or snapshot.volume_ratio is None:
            return FlowResult(
                symbol=snapshot.asset,
                flow_score=0,
                flow_direction="数据不足",
                volume_confirmation="数据暂不可用",
                relative_volume=None,
                obv_trend="数据暂不可用",
                vwap_position="数据暂不可用",
                etf_flow="数据暂不可用",
                institutional_change="数据暂不可用（13F仅能代表上个披露期）",
                insider_activity="数据暂不可用",
                short_interest="数据暂不可用",
                options_signal="数据暂不可用",
                likely_driver="无法判断",
                confidence=0,
                source_times={"行情": snapshot.data_time.isoformat()},
                warnings=("行情或成交量缺失，资金结论不可用。",),
                providers=providers,
            )
        relative = snapshot.volume_ratio
        above_vwap = snapshot.vwap is not None and snapshot.price > snapshot.vwap
        obv_positive = snapshot.obv_trend == "上升"
        price_change = snapshot.changes.get("1h") or 0
        score = 35
        score += 25 if relative >= 1.5 else 10 if relative >= 1.0 else -10
        score += 20 if obv_positive else -15 if snapshot.obv_trend == "下降" else 0
        score += 15 if above_vwap else -10
        score += 5 if price_change > 0 else -5
        score = max(0, min(100, score))
        if relative >= 1.5 and obv_positive and above_vwap and price_change > 0:
            label = "增量资金确认"
            driver = "量价、OBV与VWAP代理指标同向"
        elif price_change > 2 and relative >= 1.5 and not obv_positive:
            label = "可能是事件型追涨"
            driver = "价格快速上涨但OBV持续性尚未确认"
        elif obv_positive and above_vwap:
            label = "资金流入但持续性待验证"
            driver = "代理指标偏正面，但缺少直接机构/ETF数据"
        elif snapshot.obv_trend == "下降" and not above_vwap:
            label = "资金流出"
            driver = "OBV下降且价格位于VWAP下方"
        else:
            label = "资金未确认"
            driver = "量价代理信号不一致"
        warnings = (
            "资金流为价格、成交量、OBV和VWAP代理推断，不是账户级资金流水。",
            "13F、内部人、空头、期权和ETF流当前不参与评分。",
        )
        confidence = min(75, 35 + (20 if relative >= 1 else 0) + (15 if snapshot.vwap else 0))
        if provider and provider.status == ProviderState.STALE:
            confidence = min(confidence, 40)
            warnings = (*warnings, "行情Provider已过期，不能把资金代理描述为当前实时流向。")
        return FlowResult(
            symbol=snapshot.asset,
            flow_score=score,
            flow_direction=label,
            volume_confirmation=snapshot.volume_state,
            relative_volume=relative,
            obv_trend=snapshot.obv_trend or "数据暂不可用",
            vwap_position="价格在VWAP上方" if above_vwap else "价格在VWAP下方或不可用",
            etf_flow="数据暂不可用",
            institutional_change="数据暂不可用（13F仅能代表上个披露期）",
            insider_activity="数据暂不可用",
            short_interest="数据暂不可用",
            options_signal="数据暂不可用",
            likely_driver=driver,
            confidence=confidence,
            source_times={
                "行情": snapshot.data_time.isoformat(),
                "代理计算": datetime.now().astimezone().isoformat(),
            },
            warnings=warnings,
            providers=providers,
        )
