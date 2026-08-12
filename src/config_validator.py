from __future__ import annotations

import json
from pathlib import Path

import yaml

from .alpha_finder import ALPHA_ACTIONS
from .flow_analyzer import FLOW_LABELS
from .investment_score import V4_ACTIONS, InvestmentScoreCalculator
from .trade_filter_layer import TradeFilterLayer
from .v5_dry_run import NOW, scenarios
from .valuation_engine import VALUATION_LABELS

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_REALTIME = {"BTC-USD", "SNDK", "NVDA", "MSFT", "META", "QQQ"}


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    watchlist = _json(root / "config" / "watchlist.json")
    candidates = _json(root / "config" / "candidate_universe.json")
    weights = _yaml(root / "config" / "scoring_weights.yaml")
    graph = _yaml(root / "config" / "industry_graph.yaml")
    peers = _yaml(root / "config" / "peer_groups.yaml")
    rules = _yaml(root / "config" / "valuation_rules.yaml")
    core = [item.get("symbol") for item in watchlist.get("assets", [])]
    candidate_assets = [*candidates.get("assets", []), *candidates.get("manual_assets", [])]
    candidate_symbols = [item.get("symbol") for item in candidate_assets]
    if not core:
        errors.append("核心监控列表不能为空")
    missing_realtime = REQUIRED_REALTIME - set(core)
    if missing_realtime:
        errors.append(f"实时高优先级必选资产缺失：{sorted(missing_realtime)}")
    if len(candidate_symbols) > min(50, int(candidates.get("max_symbols", 50))):
        errors.append("候选池超过配置上限或50个硬上限")
    if len(core + candidate_symbols) != len(set(core + candidate_symbols)):
        errors.append("核心资产与候选池存在重复标的")
    try:
        InvestmentScoreCalculator.validate_weights(weights)
    except ValueError as exc:
        errors.append(str(exc))
    allowed = set(core + candidate_symbols)
    for event_id, mapping in graph.get("events", graph).items():
        for side in ("beneficiaries", "victims"):
            for segment, definition in mapping.get(side, {}).items():
                weight = definition.get("weight")
                if not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
                    errors.append(f"{event_id}/{segment} 的影响权重必须在0到1之间")
                unknown = set(definition.get("symbols", [])) - allowed
                if unknown:
                    errors.append(f"{event_id}/{segment} 引用了未配置标的：{sorted(unknown)}")
    for group, symbols in peers.items():
        if not isinstance(symbols, list) or len(symbols) < 2:
            errors.append(f"同行组 {group} 至少需要两个标的")
    configured_labels = set(rules.get("labels", []))
    if configured_labels and configured_labels != VALUATION_LABELS:
        errors.append("估值标签配置与代码允许枚举不一致")
    if not ALPHA_ACTIONS <= V4_ACTIONS | {"继续观察"}:
        errors.append("Alpha建议枚举无法映射到V4建议")
    if not FLOW_LABELS:
        errors.append("资金流枚举不能为空")
    errors.extend(_validate_v5_decision_chain())
    return errors


def _validate_v5_decision_chain() -> list[str]:
    errors: list[str] = []
    layer = TradeFilterLayer()
    required = {
        "garbage_news",
        "s_wait_pullback",
        "s_entry_confirmed",
        "s_do_not_chase",
        "a_wait_pullback",
        "a_entry_confirmed",
    }
    available = set(scenarios())
    missing = sorted(required - available)
    if missing:
        errors.append("V5 dry-run场景缺失：" + "、".join(missing))
    for name, context in scenarios().items():
        result = layer.evaluate(context, NOW)
        final_action = result.final_action.final_action
        entry_model = result.entry.entry_model
        if entry_model == "WAIT_FOR_PULLBACK" and final_action == "BUY":
            errors.append(f"{name}: WAIT_FOR_PULLBACK 不能生成 BUY")
        if entry_model == "DO_NOT_CHASE" and final_action == "BUY":
            errors.append(f"{name}: DO_NOT_CHASE 不能生成 BUY")
        if entry_model == "NO_TRADE_VALUE" and final_action == "BUY":
            errors.append(f"{name}: NO_TRADE_VALUE 不能生成 BUY")
        if final_action == "BUY" and entry_model != "ENTRY_CONFIRMED":
            errors.append(f"{name}: BUY 必须来自 ENTRY_CONFIRMED")
    return errors


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main() -> int:
    try:
        errors = validate()
    except (OSError, json.JSONDecodeError, yaml.YAMLError, TypeError, ValueError) as exc:
        errors = [f"配置读取失败：{type(exc).__name__}"]
    if errors:
        print("配置校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("配置校验通过：V4配置与V5 FINAL_ACTION决策链均有效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
