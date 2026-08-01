from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from urllib.parse import quote

from .market_data import build_session
from .replay_engine import HistoricalBar, ReplayEngine

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def fetch_daily(symbol: str, start: date, end: date) -> list[HistoricalBar]:
    provider = "BTC-USD" if symbol == "BTC-USD" else symbol
    response = build_session().get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(provider, safe='')}",
        params={
            "period1": int(datetime.combine(start, datetime.min.time(), UTC).timestamp()),
            "period2": int(datetime.combine(end, datetime.min.time(), UTC).timestamp()),
            "interval": "1d",
        },
        timeout=10,
    )
    response.raise_for_status()
    result = (response.json().get("chart", {}).get("result") or [None])[0]
    if not result:
        raise ValueError("历史行情数据暂不可用")
    quote_data = result["indicators"]["quote"][0]
    bars: list[HistoricalBar] = []
    for index, timestamp in enumerate(result.get("timestamp", [])):
        values = [quote_data.get(key, [None])[index] for key in ("high", "low", "close", "volume")]
        if any(value is None for value in values[:3]):
            continue
        bars.append(
            HistoricalBar(
                date=datetime.fromtimestamp(timestamp, UTC).date(),
                high=float(values[0]), low=float(values[1]), close=float(values[2]),
                volume=float(values[3] or 0),
            )
        )
    return bars


def run_case(case: dict) -> dict:
    event_date = date.fromisoformat(case["event_date"])
    try:
        bars = fetch_daily(case["symbol"], event_date - timedelta(days=420), event_date + timedelta(days=50))
        signal_index = max(index for index, bar in enumerate(bars) if bar.date <= event_date)
        signal = ReplayEngine().generate_signal(case["symbol"], bars, signal_index)
        future = bars[signal_index + 1 : signal_index + 21]
        entry = bars[signal_index].close
        returns = {
            str(days): ((bars[signal_index + days].close / entry - 1) * 100)
            if signal_index + days < len(bars) else None
            for days in (1, 5, 20)
        }
        maximum_favorable = max(((bar.high / entry - 1) * 100 for bar in future), default=None)
        maximum_adverse = min(((bar.low / entry - 1) * 100 for bar in future), default=None)
        return {
            **case,
            "status": "OK",
            "signal": asdict(signal),
            "returns_pct": returns,
            "maximum_favorable_excursion_pct": maximum_favorable,
            "maximum_adverse_excursion_pct": maximum_adverse,
            "no_lookahead_evidence": f"评分仅使用截至 {signal.used_until.isoformat()} 的K线",
        }
    except Exception as exc:  # noqa: BLE001 - 单案例失败必须降级，不阻断整批回测
        return {**case, "status": "UNAVAILABLE", "error": type(exc).__name__}


def aggregate(results: list[dict]) -> dict:
    usable = [item for item in results if item["status"] == "OK"]
    returns20 = [item["returns_pct"]["20"] for item in usable if item["returns_pct"]["20"] is not None]
    wins = [value for value in returns20 if value > 0]
    losses = [value for value in returns20 if value <= 0]
    pairs = [
        (item["signal"]["score"], item["returns_pct"]["20"])
        for item in usable if item["returns_pct"]["20"] is not None
    ]
    return {
        "case_count": len(results),
        "usable_count": len(usable),
        "hit_rate_20d": len(wins) / len(returns20) if returns20 else None,
        "profit_loss_ratio_20d": (mean(wins) / abs(mean(losses))) if wins and losses else None,
        "false_positive_rate": len(losses) / len(returns20) if returns20 else None,
        "score_return_correlation_20d": correlation(pairs),
        "high_opportunity_high_risk": _bucket(usable, lambda signal: signal["opportunity_score"] >= 70 and signal["risk_score"] >= 70),
        "by_data_quality": _bucket(usable, lambda signal: signal["data_quality"] >= 70),
    }


def correlation(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    xs, ys = zip(*pairs)
    x_mean, y_mean = mean(xs), mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys))
    return numerator / denominator if denominator else None


def _bucket(items: list[dict], predicate) -> dict:
    matched = [item for item in items if predicate(item["signal"])]
    values = [item["returns_pct"]["20"] for item in matched if item["returns_pct"]["20"] is not None]
    return {"count": len(matched), "average_20d_return_pct": mean(values) if values else None}


def write_reports(results: list[dict], metrics: dict, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(UTC).isoformat(), "metrics": metrics, "cases": results}
    (reports_dir / "backtest_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Investment OS V4 历史回放报告", "",
        "> 该回放只使用信号日及以前的数据生成评分；未来数据仅用于评价。免费历史行情无 SLA，结果不代表未来收益。", "",
        f"- 案例数：{metrics['case_count']}", f"- 可用案例：{metrics['usable_count']}",
        f"- 20日命中率：{_format_metric(metrics['hit_rate_20d'], percent=True)}",
        f"- 20日盈亏比：{_format_metric(metrics['profit_loss_ratio_20d'])}",
        f"- 假阳性率：{_format_metric(metrics['false_positive_rate'], percent=True)}",
        f"- 分数与20日收益相关性：{_format_metric(metrics['score_return_correlation_20d'])}", "",
        "## 案例明细", "",
    ]
    for item in results:
        if item["status"] != "OK":
            lines.extend([f"### {item['type']}｜{item['symbol']}", "", "数据暂不可用，本案例未纳入统计。", ""])
            continue
        returns = item["returns_pct"]
        lines.extend([
            f"### {item['type']}｜{item['symbol']}", "",
            f"- 事件：{item['title']}", f"- 信号分：{item['signal']['score']}",
            f"- 1/5/20日收益：{_format_percent_value(returns['1'])} / {_format_percent_value(returns['5'])} / {_format_percent_value(returns['20'])}",
            f"- MFE/MAE：{_format_percent_value(item['maximum_favorable_excursion_pct'])} / {_format_percent_value(item['maximum_adverse_excursion_pct'])}",
            f"- 无前视证据：{item['no_lookahead_evidence']}", "",
        ])
    lines.extend(["## 限制", "", "案例由已知历史事件构成，存在样本选择和幸存者偏差；事件文本未进入评分，当前主要验证技术、量价和风险规则。免费行情失败时案例明确标为不可用。", ""])
    (reports_dir / "backtest_report.md").write_text("\n".join(lines), encoding="utf-8")


def _format_metric(value: float | None, percent: bool = False) -> str:
    if value is None:
        return "数据暂不可用"
    return f"{value * 100:.2f}%" if percent else f"{value:.2f}"


def _format_percent_value(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:.2f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Investment OS V4 历史回放")
    parser.add_argument("--cases", default=str(ROOT / "config" / "backtest_cases.json"))
    parser.add_argument("--output", default=str(ROOT / "reports"))
    args = parser.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    results = [run_case(case) for case in cases]
    metrics = aggregate(results)
    write_reports(results, metrics, Path(args.output))
    print(f"回测完成：{metrics['usable_count']}/{metrics['case_count']} 个案例可用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
