from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .data_quality import (
    DataQualityResult,
    ProviderResult,
    ProviderState,
    evaluate_data_quality,
    placeholder_status,
    provider_status,
)
from .indicators import ema
from .market_data import MarketSnapshot, build_session

LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
VALUATION_LABELS = {
    "明显低估", "相对便宜", "合理", "偏贵", "明显过热", "周期数据失真", "数据不足"
}


@dataclass(frozen=True)
class ValuationResult:
    symbol: str
    valuation_type: str
    current_metrics: dict[str, float | str | None]
    historical_percentiles: dict[str, float | None]
    peer_comparison: str
    growth_adjusted_value: str
    cycle_adjustment: str
    valuation_score: int
    valuation_label: str
    confidence: int
    data_time: datetime | None
    missing_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    data_quality: DataQualityResult


class NasdaqFundamentalsProvider:
    BASE = "https://api.nasdaq.com/api"

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout
        self.session = build_session(retries=1)
        self.headers = {"User-Agent": "Mozilla/5.0 InvestmentOS/4.0", "Accept": "application/json"}

    def fetch(self, symbol: str) -> ProviderResult[dict[str, Any]]:
        endpoints = {
            "summary": f"{self.BASE}/quote/{symbol}/summary?assetclass=stocks",
            "quarterly": f"{self.BASE}/company/{symbol}/financials?frequency=2",
            "annual": f"{self.BASE}/company/{symbol}/financials?frequency=1",
            "forecast": f"{self.BASE}/analyst/{symbol}/earnings-forecast",
        }
        data: dict[str, Any] = {}
        errors: list[str] = []
        for name, url in endpoints.items():
            try:
                response = self.session.get(url, headers=self.headers, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json().get("data")
                if payload:
                    data[name] = payload
                else:
                    errors.append(f"{name}无数据")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}:{type(exc).__name__}")
        state = ProviderState.HEALTHY if len(data) == len(endpoints) else ProviderState.DEGRADED if data else ProviderState.UNAVAILABLE
        meta = provider_status(
            status=state,
            source="Nasdaq公开公司数据",
            source_url=f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}",
            # Nasdaq响应中的各表披露期格式并不统一；不把抓取时间冒充财务数据时间。
            data_timestamp=None,
            confidence=80 if state == ProviderState.HEALTHY else 55 if data else 0,
            error="；".join(errors) or None,
        )
        return ProviderResult(data=data or None, meta=meta)


class ValuationEngine:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.provider = NasdaqFundamentalsProvider()
        self.session = build_session(retries=1)

    def analyze_many(
        self,
        snapshots: dict[str, MarketSnapshot],
        symbols: list[str],
    ) -> dict[str, ValuationResult]:
        selected = symbols[: int(self.rules.get("max_fundamental_symbols_per_scan", 15))]
        results: dict[str, ValuationResult] = {}
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(selected)))) as executor:
            futures = {
                executor.submit(self.analyze, symbol, snapshots[symbol]): symbol
                for symbol in selected
                if symbol in snapshots
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("估值分析失败：%s（%s）", symbol, type(exc).__name__)
                    results[symbol] = unavailable_valuation(symbol, "估值计算失败")
        return results

    def analyze(self, symbol: str, snapshot: MarketSnapshot) -> ValuationResult:
        if snapshot.asset_type == "crypto":
            return self._crypto(symbol, snapshot)
        provider_result = self.provider.fetch(symbol)
        if not provider_result.data:
            return unavailable_valuation(symbol, provider_result.meta.error or "Nasdaq数据不可用", provider_result.meta)
        metrics = _extract_stock_metrics(provider_result.data, snapshot.price)
        cyclical = symbol in set(self.rules.get("cyclical", {}).get("symbols", []))
        score, label, cycle_note = self._label_stock(metrics, cyclical)
        placeholder = placeholder_status("历史估值百分位", "无稳定免费历史估值序列，当前不参与评分")
        required = {
            "PE TTM": metrics.get("pe_ttm"),
            "Forward PE": metrics.get("forward_pe"),
            "PS": metrics.get("ps"),
            "PB": metrics.get("pb"),
            "FCF收益率": metrics.get("fcf_yield_pct"),
            "营收增速": metrics.get("revenue_growth_pct"),
            "毛利率": metrics.get("gross_margin_pct"),
        }
        quality = evaluate_data_quality(required, [provider_result.meta, placeholder])
        warnings = [
            "Nasdaq公开接口无SLA，财务单位已按其页面展示规则换算。",
            "历史估值百分位数据暂不可用，不参与估值分。",
        ]
        if cyclical:
            warnings.append("周期股不能仅依据静态PE判断便宜。")
        return ValuationResult(
            symbol=symbol,
            valuation_type="周期股估值" if cyclical else "成长/股票估值",
            current_metrics=metrics,
            historical_percentiles={"pe": None, "ps": None, "pb": None},
            peer_comparison="等待同行比较模块聚合",
            growth_adjusted_value=_growth_adjusted_text(metrics),
            cycle_adjustment=cycle_note,
            valuation_score=round(score * quality.score / 100),
            valuation_label=label if quality.score >= 35 else "数据不足",
            confidence=min(quality.confidence, 75),
            data_time=provider_result.meta.data_timestamp,
            missing_fields=quality.missing_fields,
            warnings=tuple(warnings) + quality.warnings,
            data_quality=quality,
        )

    def _label_stock(self, metrics: dict[str, Any], cyclical: bool) -> tuple[int, str, str]:
        if metrics.get("ps") is None or metrics.get("fcf_yield_pct") is None:
            return 0, "数据不足", "周期位置数据不足" if cyclical else "不适用"
        if cyclical:
            low_pe = metrics.get("pe_ttm") is not None and metrics["pe_ttm"] < self.rules["cyclical"]["low_pe_warning"]
            margin_expanding = (metrics.get("gross_margin_pct") or 0) > (metrics.get("prior_gross_margin_pct") or 0) + 5
            if low_pe and margin_expanding:
                return 45, "周期数据失真", "盈利与毛利率处于快速上行阶段，低PE可能来自周期高盈利。"
        growth = self.rules["growth_tech"]
        score = 50
        score += 15 if metrics["ps"] <= growth["cheap_ps"] else -20 if metrics["ps"] >= growth["expensive_ps"] else 0
        fcf_yield = metrics["fcf_yield_pct"]
        score += 15 if fcf_yield >= growth["cheap_fcf_yield_pct"] else -10 if fcf_yield <= growth["expensive_fcf_yield_pct"] else 0
        forward_pe = metrics.get("forward_pe")
        score += 10 if forward_pe and forward_pe < 25 else -15 if forward_pe and forward_pe > 60 else 0
        revenue_growth = metrics.get("revenue_growth_pct")
        score += 10 if revenue_growth and revenue_growth >= growth["strong_revenue_growth_pct"] else -10 if revenue_growth is not None and revenue_growth < 0 else 0
        score = max(0, min(100, score))
        label = "明显低估" if score >= 85 else "相对便宜" if score >= 68 else "合理" if score >= 43 else "偏贵" if score >= 25 else "明显过热"
        return score, label, "已结合增长、现金流和资产负债，而非单一PE。"

    def _crypto(self, symbol: str, snapshot: MarketSnapshot) -> ValuationResult:
        providers = []
        metrics: dict[str, float | str | None] = {
            "market_cap": None, "mvrv": None, "realized_cap": None,
            "etf_flow": None, "stablecoin_liquidity": None, "price_vs_ema200d_pct": None,
        }
        warnings: list[str] = []
        try:
            response = self.session.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin", "vs_currencies": "usd", "include_market_cap": "true", "include_last_updated_at": "true"},
                timeout=5,
            )
            response.raise_for_status()
            bitcoin = response.json()["bitcoin"]
            timestamp = datetime.fromtimestamp(bitcoin["last_updated_at"], UTC)
            metrics["market_cap"] = float(bitcoin["usd_market_cap"])
            providers.append(provider_status(
                status=ProviderState.HEALTHY,
                source="CoinGecko公开API",
                source_url="https://www.coingecko.com/en/coins/bitcoin",
                data_timestamp=timestamp,
                confidence=70,
                is_fallback=True,
            ))
        except Exception as exc:  # noqa: BLE001
            providers.append(provider_status(
                status=ProviderState.UNAVAILABLE, source="CoinGecko公开API", source_url="https://www.coingecko.com/en/coins/bitcoin",
                data_timestamp=None, confidence=0, error=type(exc).__name__, is_fallback=True,
            ))
        try:
            response = self.session.get(
                "https://data-api.binance.vision/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1d", "limit": 260}, timeout=5,
            )
            response.raise_for_status()
            closes = [float(row[4]) for row in response.json()[:-1]]
            ema200 = ema(closes, 200)[-1]
            metrics["price_vs_ema200d_pct"] = (snapshot.price / ema200 - 1) * 100
            providers.append(provider_status(
                status=ProviderState.HEALTHY, source="Binance日线", source_url="https://data-api.binance.vision/api/v3/klines",
                data_timestamp=datetime.now(UTC), confidence=85,
            ))
        except Exception as exc:  # noqa: BLE001
            providers.append(provider_status(
                status=ProviderState.UNAVAILABLE, source="Binance日线", source_url="https://data-api.binance.vision/api/v3/klines",
                data_timestamp=None, confidence=0, error=type(exc).__name__,
            ))
        placeholders = [
            placeholder_status("BTC已实现市值/MVRV", "稳定免费源未接入"),
            placeholder_status("BTC ETF资金流", "稳定结构化免费源未接入"),
            placeholder_status("稳定币与持有者数据", "稳定免费源未接入"),
        ]
        quality = evaluate_data_quality(
            {"市值": metrics["market_cap"], "200日均线距离": metrics["price_vs_ema200d_pct"]},
            providers + placeholders,
        )
        distance = metrics.get("price_vs_ema200d_pct")
        if distance is None:
            label, score = "数据不足", 0
        elif distance > self.rules["crypto"]["overheat_distance_pct"]:
            label, score = "明显过热", 25
        elif distance > 15:
            label, score = "偏贵", 40
        elif distance < -20:
            label, score = "相对便宜", 70
        else:
            label, score = "合理", 55
        warnings.extend(("BTC不使用股票PE模型。", "MVRV、ETF流和链上持有者数据缺失，不参与评分。"))
        return ValuationResult(
            symbol=symbol, valuation_type="Crypto Valuation", current_metrics=metrics,
            historical_percentiles={"historical_drawdown": None}, peer_comparison="不与股票估值直接比较",
            growth_adjusted_value="不适用", cycle_adjustment="参考200日均线，不代表减半周期的完整估值。",
            valuation_score=round(score * quality.score / 100), valuation_label=label,
            confidence=min(quality.confidence, 65), data_time=datetime.now(UTC),
            missing_fields=quality.missing_fields, warnings=tuple(warnings) + quality.warnings, data_quality=quality,
        )


def _extract_stock_metrics(payload: dict[str, Any], price: float) -> dict[str, float | str | None]:
    quarterly = payload.get("quarterly", {})
    annual = payload.get("annual", {})
    summary = payload.get("summary", {})
    forecast = payload.get("forecast", {})
    market_cap = _number(((summary.get("summaryData") or {}).get("MarketCap") or {}).get("value"), scale=1)
    revenue_ttm = _sum_row(quarterly, "incomeStatementTable", "Total Revenue")
    net_income_ttm = _sum_row(quarterly, "incomeStatementTable", "Net Income")
    gross_profit_ttm = _sum_row(quarterly, "incomeStatementTable", "Gross Profit")
    operating_income_ttm = _sum_row(quarterly, "incomeStatementTable", "Operating Income")
    operating_cash_ttm = _sum_row(quarterly, "cashFlowTable", "Net Cash Flow-Operating")
    capex_ttm = abs(_sum_row(quarterly, "cashFlowTable", "Capital Expenditures") or 0)
    equity = _row_value(annual, "balanceSheetTable", "Total Equity", 2)
    cash = _first_row_value(annual, "balanceSheetTable", ("Cash", "Cash and Equivalents"), 2)
    debt = (_row_value(annual, "balanceSheetTable", "Long-Term Debt", 2) or 0) + (_row_value(annual, "balanceSheetTable", "Short-Term Debt", 2) or 0)
    revenue_latest = _row_value(annual, "incomeStatementTable", "Total Revenue", 2)
    revenue_prior = _row_value(annual, "incomeStatementTable", "Total Revenue", 3)
    gross_latest = _row_value(annual, "financialRatiosTable", "Gross Margin", 2, scale=1)
    gross_prior = _row_value(annual, "financialRatiosTable", "Gross Margin", 3, scale=1)
    roe = _row_value(annual, "financialRatiosTable", "After Tax ROE", 2, scale=1)
    yearly = ((forecast.get("yearlyForecast") or {}).get("rows") or [])
    forecast_eps = _safe_float(yearly[0].get("consensusEPSForecast")) if yearly else None
    next_eps = _safe_float(yearly[1].get("consensusEPSForecast")) if len(yearly) > 1 else None
    forward_pe = price / forecast_eps if price and forecast_eps and forecast_eps > 0 else None
    earnings_growth = (next_eps / forecast_eps - 1) * 100 if forecast_eps and next_eps else None
    fcf = operating_cash_ttm - capex_ttm if operating_cash_ttm is not None else None
    enterprise_value = market_cap + debt - (cash or 0) if market_cap is not None else None
    return {
        "pe_ttm": market_cap / net_income_ttm if market_cap and net_income_ttm and net_income_ttm > 0 else None,
        "forward_pe": forward_pe,
        "ps": market_cap / revenue_ttm if market_cap and revenue_ttm else None,
        "pb": market_cap / equity if market_cap and equity else None,
        "peg": forward_pe / earnings_growth if forward_pe and earnings_growth and earnings_growth > 0 else None,
        "ev_ebitda": None,
        "ev_sales": enterprise_value / revenue_ttm if enterprise_value and revenue_ttm else None,
        "fcf_yield_pct": fcf / market_cap * 100 if fcf is not None and market_cap else None,
        "gross_margin_pct": gross_profit_ttm / revenue_ttm * 100 if gross_profit_ttm and revenue_ttm else gross_latest,
        "prior_gross_margin_pct": gross_prior,
        "operating_margin_pct": operating_income_ttm / revenue_ttm * 100 if operating_income_ttm and revenue_ttm else None,
        "revenue_growth_pct": (revenue_latest / revenue_prior - 1) * 100 if revenue_latest and revenue_prior else None,
        "eps_growth_pct": earnings_growth,
        "net_cash": (cash or 0) - debt if cash is not None else None,
        "roe_pct": roe,
        "capex_ttm": capex_ttm,
        "market_cap": market_cap,
        "revenue_ttm": revenue_ttm,
        "free_cash_flow_ttm": fcf,
    }


def _table_rows(payload: dict[str, Any], table: str) -> list[dict[str, Any]]:
    return ((payload.get(table) or {}).get("rows") or [])


def _row_value(payload: dict[str, Any], table: str, label: str, column: int, scale: int = 1000) -> float | None:
    row = next((item for item in _table_rows(payload, table) if item.get("value1") == label), None)
    return _number(row.get(f"value{column}") if row else None, scale=scale)


def _first_row_value(payload: dict[str, Any], table: str, labels: tuple[str, ...], column: int) -> float | None:
    for label in labels:
        value = _row_value(payload, table, label, column)
        if value is not None:
            return value
    return None


def _sum_row(payload: dict[str, Any], table: str, label: str) -> float | None:
    row = next((item for item in _table_rows(payload, table) if item.get("value1") == label), None)
    if not row:
        return None
    values = [_number(row.get(f"value{column}")) for column in range(2, 6)]
    return sum(value for value in values if value is not None) if all(value is not None for value in values) else None


def _number(value: Any, scale: int = 1000) -> float | None:
    if value in (None, "", "--", "N/A"):
        return None
    text = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
    negative = text.startswith("-")
    text = text.removeprefix("-")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    result = float(match.group()) * scale
    return -result if negative else result


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _growth_adjusted_text(metrics: dict[str, Any]) -> str:
    growth = metrics.get("revenue_growth_pct")
    forward_pe = metrics.get("forward_pe")
    if growth is None or forward_pe is None:
        return "数据暂不可用"
    return f"Forward PE {forward_pe:.1f} 倍，对应最近年度营收增速 {growth:.1f}%。"


def unavailable_valuation(
    symbol: str,
    reason: str,
    provider=None,
) -> ValuationResult:
    provider = provider or provider_status(
        status=ProviderState.UNAVAILABLE, source="估值数据源", source_url="",
        data_timestamp=None, confidence=0, error=reason,
    )
    quality = evaluate_data_quality({"估值指标": None}, [provider])
    return ValuationResult(
        symbol=symbol, valuation_type="数据不足", current_metrics={}, historical_percentiles={},
        peer_comparison="数据暂不可用", growth_adjusted_value="数据暂不可用", cycle_adjustment="数据暂不可用",
        valuation_score=0, valuation_label="数据不足", confidence=0, data_time=None,
        missing_fields=("全部估值字段",), warnings=(reason,), data_quality=quality,
    )
