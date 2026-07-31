from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .market_data import MarketSnapshot
from .news import NewsItem
from .scoring import Scores

BEIJING = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class AlertCandidate:
    asset: str
    alert_type: str
    strength: float
    reasons: tuple[str, ...]
    advice: tuple[str, ...]
    invalidation: str
    news: NewsItem | None = None


def detect_alerts(
    snapshot: MarketSnapshot,
    scores: Scores,
    news: list[NewsItem],
    thresholds: dict,
) -> list[AlertCandidate]:
    result = [_news_candidate(snapshot.asset, item) for item in news if item.is_major]
    if snapshot.error or not snapshot.fresh:
        return result
    changes = snapshot.changes

    rise_hits = _threshold_hits(changes, thresholds["rapid_rise"], rising=True)
    if rise_hits:
        result.append(
            AlertCandidate(
                snapshot.asset,
                "急涨预警",
                max(rise_hits),
                tuple(_change_reason(label, changes[label]) for label in _hit_labels(changes, thresholds["rapid_rise"], True)),
                ("短线快速上涨，不建议直接追高，等待回踩确认。", "维持原定预算，避免一次性重仓。"),
                "价格回落至突破位下方且成交量走弱时，本次强势判断失效。",
            )
        )

    fall_hits = _threshold_hits(changes, thresholds["rapid_fall"], rising=False)
    if fall_hits:
        negative = next((item for item in news if item.is_major and item.is_negative), None)
        reason = (
            f"发现可能相关的重大利空：{negative.title}"
            if negative
            else "暂未发现明确重大利空，更接近技术性回调，但仍需等待确认。"
        )
        result.append(
            AlertCandidate(
                snapshot.asset,
                "急跌预警",
                max(abs(value) for value in fall_hits),
                tuple(_change_reason(label, changes[label]) for label in _hit_labels(changes, thresholds["rapid_fall"], False))
                + (reason,),
                ("暂缓新增仓位，等待波动收敛和重新企稳。", "不使用杠杆，不因短线下跌盲目加仓。"),
                "价格重新站稳 EMA20、RSI 回升且下跌不再放量时，风险判断失效。",
                negative,
            )
        )

    breakout_config = thresholds["breakout"]
    if (
        snapshot.breakout
        and snapshot.volume_ratio is not None
        and snapshot.volume_ratio >= breakout_config["volume_ratio"]
        and scores.trend >= breakout_config["trend_score"]
    ):
        strength = scores.trend + min(snapshot.volume_ratio * 5, 20)
        result.append(
            AlertCandidate(
                snapshot.asset,
                "突破预警",
                strength,
                (
                    f"价格突破近 20 周期高点 {format_price(snapshot.recent_high)}。",
                    f"成交量为近 20 周期均量的 {snapshot.volume_ratio:.2f} 倍。",
                    f"趋势评分 {scores.trend}/100，突破强度 {min(round(strength), 100)}/100。",
                ),
                ("仅适合按原定预算小额分批。", "等待回踩确认，不使用“必涨”假设，不追高。"),
                f"价格重新跌回近 20 周期高点 {format_price(snapshot.recent_high)} 下方且放量转弱。",
            )
        )

    pullback_config = thresholds["pullback"]
    ema_distance = (
        abs(snapshot.price / snapshot.ema20 - 1) * 100 if snapshot.ema20 else float("inf")
    )
    medium_up = bool(snapshot.ema20 and snapshot.ema60 and snapshot.ema20 > snapshot.ema60)
    rsi_recovering = bool(
        snapshot.rsi is not None
        and snapshot.rsi_previous is not None
        and snapshot.rsi > snapshot.rsi_previous
        and snapshot.rsi <= 50
    )
    negative_news = any(item.is_major and item.is_negative for item in news)
    if (
        medium_up
        and ema_distance <= pullback_config["ema20_distance_pct"]
        and rsi_recovering
        and not negative_news
        and scores.opportunity >= pullback_config["opportunity_score"]
    ):
        result.append(
            AlertCandidate(
                snapshot.asset,
                "回踩机会预警",
                float(scores.opportunity),
                (
                    "EMA20 位于 EMA60 上方，中期趋势仍向上。",
                    f"价格距离 EMA20 约 {ema_distance:.2f}%。",
                    f"RSI 从 {snapshot.rsi_previous:.1f} 回升至 {snapshot.rsi:.1f}，暂未发现明确利空。",
                ),
                ("可考虑按原定预算小额分批，不要一次性重仓。", "继续定投也应遵守每日约 10 USDT 预算。"),
                "跌破近期低点或 EMA20 下穿 EMA60 时，本次回踩机会判断失效。",
            )
        )

    weakening = thresholds["weakening"]
    if (
        snapshot.ema20
        and snapshot.ema60
        and snapshot.price < snapshot.ema20
        and snapshot.ema20 < snapshot.ema60
        and snapshot.rsi is not None
        and snapshot.rsi < weakening["rsi_below"]
        and snapshot.rsi_previous is not None
        and snapshot.rsi_previous < weakening["rsi_below"]
        and snapshot.volume_ratio is not None
        and snapshot.volume_ratio >= weakening["volume_ratio"]
        and (snapshot.changes.get("5m") or 0) < 0
    ):
        result.append(
            AlertCandidate(
                snapshot.asset,
                "趋势转弱预警",
                min(100.0, 40 - snapshot.rsi + snapshot.volume_ratio * 20),
                (
                    "价格跌破 EMA20，且 EMA20 已位于 EMA60 下方。",
                    f"RSI 为 {snapshot.rsi:.1f}，持续弱于 40。",
                    f"下跌成交量为近 20 周期均量的 {snapshot.volume_ratio:.2f} 倍。",
                ),
                ("趋势转弱，暂缓新增，等待重新企稳。", "风险规避，不抄底、不加杠杆。"),
                "价格重新站稳 EMA20、EMA20 上穿 EMA60 且 RSI 回到 40 上方。",
            )
        )

    return result


def _news_candidate(asset: str, item: NewsItem) -> AlertCandidate:
    return AlertCandidate(
        asset,
        "重大新闻预警",
        80.0 if item.source in {"美国 SEC EDGAR", "美联储", "美国劳工统计局"} else 70.0,
        (
            f"事实：{item.source} 发布“{item.title}”。",
            f"事件类别：{item.category}。",
            "影响链（推测）：事件可能先影响预期和风险偏好，再影响估值与价格；实际方向需结合公告正文和行情确认。",
        ),
        ("先核对原文，不把标题直接当作确定性机会。", "若波动放大，等待回踩或暂缓新增。"),
        "后续官方澄清、完整公告内容或市场价格反应与当前推测不一致。",
        item,
    )


def format_alert(candidate: AlertCandidate, snapshot: MarketSnapshot, news: list[NewsItem]) -> str:
    background = candidate.news or next((item for item in news if item.is_major), None)
    if background:
        news_text = (
            f"事实：{background.title}\n"
            f"来源：{background.source}\n"
            f"发布时间：{background.published_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')}\n"
            f"链接：{background.url}\n"
            "推测：其影响方向仍需结合原文和后续行情确认。"
        )
    else:
        news_text = "暂未发现明确消息驱动。"
    volume = (
        f"{snapshot.volume_ratio:.2f} 倍近 20 周期均量"
        if snapshot.volume_ratio is not None
        else "数据暂不可用"
    )
    technical = (
        f"EMA20 {format_price(snapshot.ema20)} / EMA60 {format_price(snapshot.ema60)} / "
        f"RSI {snapshot.rsi:.1f}" if snapshot.rsi is not None else "数据暂不可用"
    )
    reasons = "\n".join(f"{index}. {reason}" for index, reason in enumerate(candidate.reasons, 1))
    advice = "\n".join(f"- {item}" for item in candidate.advice)
    return f"""【Investment OS 实时预警】

资产：{snapshot.asset}
时间：{snapshot.data_time.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S %Z")}（数据时间）
预警类型：{candidate.alert_type}
当前价格：{format_price(None if snapshot.error else snapshot.price)}
5分钟涨跌：{format_pct(snapshot.changes.get("5m"))}
15分钟涨跌：{format_pct(snapshot.changes.get("15m"))}
1小时涨跌：{format_pct(snapshot.changes.get("1h"))}
24小时涨跌：{format_pct(snapshot.changes.get("24h"))}

触发原因：
{reasons}

新闻背景：
{news_text}

判断：
- 趋势：{"EMA20 高于 EMA60" if snapshot.ema20 and snapshot.ema60 and snapshot.ema20 > snapshot.ema60 else "偏弱或待确认"}
- 资金/成交量：{volume}
- 技术面：{technical}
- 新闻面：{"存在需核实的重大事件" if background else "暂未发现明确消息驱动"}

执行建议：
{advice}

失效条件：
{candidate.invalidation}

风险提示：
本系统只做辅助分析，不构成收益保证。"""


def _threshold_hits(changes: dict[str, float | None], thresholds: dict, rising: bool) -> list[float]:
    return [
        value for key, limit in thresholds.items()
        if (value := changes.get(key)) is not None and (value >= limit if rising else value <= limit)
    ]


def _hit_labels(changes: dict[str, float | None], thresholds: dict, rising: bool) -> list[str]:
    return [
        key for key, limit in thresholds.items()
        if changes.get(key) is not None and (changes[key] >= limit if rising else changes[key] <= limit)
    ]


def _change_reason(label: str, value: float | None) -> str:
    return f"{label} 涨跌幅为 {format_pct(value)}，达到预警阈值。"


def format_pct(value: float | None) -> str:
    return "数据暂不可用" if value is None else f"{value:+.2f}%"


def format_price(value: float | None) -> str:
    if value is None:
        return "数据暂不可用"
    return f"{value:,.2f}"
