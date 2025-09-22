"""Canonical設定の整合チェックユーティリティ。"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Literal, Set

from pydantic import BaseModel, Field

from .models import CanonicalArc, CanonicalBom, CanonicalConfig, CanonicalNode


Severity = Literal["error", "warning"]


class ValidationIssue(BaseModel):
    """単一の検証結果。"""

    severity: Severity
    code: str
    message: str
    context: Dict[str, str] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """検証結果の集約。"""

    issues: List[ValidationIssue] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    def add_issue(
        self,
        *,
        severity: Severity,
        code: str,
        message: str,
        context: Dict[str, str] | None = None,
    ) -> None:
        self.issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                context=context or {},
            )
        )

    def add_error(
        self, code: str, message: str, context: Dict[str, str] | None = None
    ) -> None:
        self.add_issue(severity="error", code=code, message=message, context=context)

    def add_warning(
        self, code: str, message: str, context: Dict[str, str] | None = None
    ) -> None:
        self.add_issue(severity="warning", code=code, message=message, context=context)


def validate_canonical_config(config: CanonicalConfig) -> ValidationResult:
    """Canonical設定の整合性を検証する。"""

    result = ValidationResult()

    item_codes = {item.code for item in config.items}
    node_codes = _validate_nodes(config.nodes, result)
    _validate_node_items(config.nodes, item_codes, result)
    _validate_arcs(config.arcs, node_codes, result)
    _validate_bom(config.bom, item_codes, result)
    _validate_demands(config.demands, node_codes, item_codes, result)
    _validate_capacities(config.capacities, node_codes, result)
    _validate_hierarchies(config.hierarchies, result)

    return result


def _validate_nodes(
    nodes: Iterable[CanonicalNode], result: ValidationResult
) -> Set[str]:
    codes: Set[str] = set()
    for node in nodes:
        if node.code in codes:
            result.add_error(
                code="DUPLICATE_NODE",
                message=f"ノードコード '{node.code}' が重複しています。",
                context={"node_code": node.code},
            )
        else:
            codes.add(node.code)
    return codes


def _validate_node_items(
    nodes: Iterable[CanonicalNode],
    item_codes: Set[str],
    result: ValidationResult,
) -> None:
    for node in nodes:
        seen: Set[str] = set()
        for policy in node.inventory_policies:
            if policy.item_code not in item_codes:
                result.add_error(
                    code="NODE_ITEM_UNKNOWN",
                    message=f"ノード '{node.code}' で未定義の品目 '{policy.item_code}' を参照しています。",
                    context={"node_code": node.code, "item_code": policy.item_code},
                )
            if policy.item_code in seen:
                result.add_error(
                    code="NODE_ITEM_DUPLICATE",
                    message=f"ノード '{node.code}' で品目 '{policy.item_code}' が重複定義されています。",
                    context={"node_code": node.code, "item_code": policy.item_code},
                )
            else:
                seen.add(policy.item_code)
        capacity_seen: Set[str] = set()
        for policy in node.production_policies:
            base_key = policy.item_code or "__any__"
            if base_key in capacity_seen:
                context = {"node_code": node.code}
                if policy.item_code:
                    context["item_code"] = policy.item_code
                result.add_warning(
                    code="NODE_PROD_DUPLICATE",
                    message=f"ノード '{node.code}' の生産ポリシーが重複しています。",
                    context=context,
                )
            else:
                capacity_seen.add(base_key)


def _validate_arcs(
    arcs: Iterable[CanonicalArc],
    node_codes: Set[str],
    result: ValidationResult,
) -> None:
    seen_pairs: Set[tuple[str, str, str]] = set()
    for arc in arcs:
        pair = (arc.from_node, arc.to_node, arc.arc_type)
        if pair in seen_pairs:
            result.add_warning(
                code="ARC_DUPLICATE",
                message=f"リンク {arc.from_node}->{arc.to_node} ({arc.arc_type}) が重複しています。",
                context={"from_node": arc.from_node, "to_node": arc.to_node},
            )
        else:
            seen_pairs.add(pair)

        if arc.from_node == arc.to_node:
            result.add_warning(
                code="ARC_SELF_LOOP",
                message=f"ノード '{arc.from_node}' への自己リンクが存在します。",
                context={"node_code": arc.from_node},
            )
        if arc.from_node not in node_codes:
            result.add_error(
                code="ARC_FROM_MISSING",
                message=f"リンクの起点ノード '{arc.from_node}' が定義されていません。",
                context={"from_node": arc.from_node, "to_node": arc.to_node},
            )
        if arc.to_node not in node_codes:
            result.add_error(
                code="ARC_TO_MISSING",
                message=f"リンクの終点ノード '{arc.to_node}' が定義されていません。",
                context={"from_node": arc.from_node, "to_node": arc.to_node},
            )


def _validate_bom(
    bom_rows: Iterable[CanonicalBom],
    item_codes: Set[str],
    result: ValidationResult,
) -> None:
    graph: Dict[str, Set[str]] = defaultdict(set)

    for row in bom_rows:
        if row.parent_item not in item_codes:
            result.add_error(
                code="BOM_PARENT_UNKNOWN",
                message=f"BOM親品目 '{row.parent_item}' が未定義です。",
                context={"parent_item": row.parent_item},
            )
        if row.child_item not in item_codes:
            result.add_error(
                code="BOM_CHILD_UNKNOWN",
                message=f"BOM子品目 '{row.child_item}' が未定義です。",
                context={"child_item": row.child_item},
            )
        graph[row.parent_item].add(row.child_item)

    if _has_cycle(graph):
        result.add_error(
            code="BOM_CYCLE",
            message="BOMに循環が検出されました。",
            context={},
        )


def _has_cycle(graph: Dict[str, Set[str]]) -> bool:
    visited: Set[str] = set()
    stack: Set[str] = set()

    def dfs(node: str) -> bool:
        if node in stack:
            return True
        if node in visited:
            return False
        stack.add(node)
        for child in graph.get(node, set()):
            if dfs(child):
                return True
        stack.remove(node)
        visited.add(node)
        return False

    for root in graph.keys():
        if dfs(root):
            return True
    return False


def _validate_demands(
    demands, node_codes: Set[str], item_codes: Set[str], result: ValidationResult
) -> None:
    for row in demands:
        if row.node_code not in node_codes:
            result.add_error(
                code="DEMAND_NODE_UNKNOWN",
                message=f"需要ノード '{row.node_code}' が未定義です。",
                context={"node_code": row.node_code, "item_code": row.item_code},
            )
        if row.item_code not in item_codes:
            result.add_error(
                code="DEMAND_ITEM_UNKNOWN",
                message=f"需要対象品目 '{row.item_code}' が未定義です。",
                context={"node_code": row.node_code, "item_code": row.item_code},
            )


def _validate_capacities(
    capacities, node_codes: Set[str], result: ValidationResult
) -> None:
    for row in capacities:
        if row.resource_type == "node" and row.resource_code not in node_codes:
            result.add_error(
                code="CAPACITY_NODE_UNKNOWN",
                message=f"能力対象ノード '{row.resource_code}' が未定義です。",
                context={"resource_code": row.resource_code},
            )


def _validate_hierarchies(hierarchies, result: ValidationResult) -> None:
    seen: Set[tuple[str, str]] = set()
    for row in hierarchies:
        key = (row.hierarchy_type, row.node_key)
        if key in seen:
            result.add_warning(
                code="HIERARCHY_DUPLICATE",
                message=f"{row.hierarchy_type}階層キー '{row.node_key}' が重複しています。",
                context={
                    "hierarchy_type": row.hierarchy_type,
                    "node_key": row.node_key,
                },
            )
        else:
            seen.add(key)


__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "validate_canonical_config",
]
