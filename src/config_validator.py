from __future__ import annotations

import json
from pathlib import Path

import yaml

from .alpha_finder import ALPHA_ACTIONS
from .flow_analyzer import FLOW_LABELS
from .investment_score import V4_ACTIONS, InvestmentScoreCalculator
from .valuation_engine import VALUATION_LABELS

ROOT = Path(__file__).resolve().parents[1]


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
    print("配置校验通过：监控列表、候选池、产业链、同行组、估值规则和评分权重均有效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
