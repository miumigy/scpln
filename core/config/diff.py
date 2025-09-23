"""Canonical設定差分ユーティリティ。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List

from .models import CanonicalConfig, ConfigMeta


@dataclass
class EntityDiff:
    """単一エンティティ種別の差分サマリ。"""

    name: str
    base_count: int
    compare_count: int
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    @property
    def unchanged_count(self) -> int:
        return max(self.base_count - len(self.removed) - len(self.changed), 0)


def diff_canonical_configs(
    base: CanonicalConfig, compare: CanonicalConfig
) -> Dict[str, Any]:
    """2つのCanonical設定を比較し、差分サマリを返す。"""

    meta_diff = _diff_meta(base.meta, compare.meta)

    entities = {
        "items": _diff_entities(
            "items",
            base.items,
            compare.items,
            lambda item: item.code,
        ),
        "nodes": _diff_entities(
            "nodes",
            base.nodes,
            compare.nodes,
            lambda node: node.code,
        ),
        "arcs": _diff_entities(
            "arcs",
            base.arcs,
            compare.arcs,
            lambda arc: f"{arc.from_node}->{arc.to_node}:{arc.arc_type}",
        ),
        "bom": _diff_entities(
            "bom",
            base.bom,
            compare.bom,
            lambda row: f"{row.parent_item}->{row.child_item}",
        ),
        "demands": _diff_entities(
            "demands",
            base.demands,
            compare.demands,
            lambda row: f"{row.node_code}:{row.item_code}:{row.bucket}",
        ),
        "capacities": _diff_entities(
            "capacities",
            base.capacities,
            compare.capacities,
            lambda row: f"{row.resource_type}:{row.resource_code}:{row.bucket}",
        ),
        "calendars": _diff_entities(
            "calendars",
            base.calendars,
            compare.calendars,
            lambda cal: cal.calendar_code,
        ),
        "hierarchies": _diff_entities(
            "hierarchies",
            base.hierarchies,
            compare.hierarchies,
            lambda row: f"{row.hierarchy_type}:{row.node_key}",
        ),
    }

    return {
        "meta": meta_diff,
        "entities": entities,
    }


def _diff_meta(base: ConfigMeta, compare: ConfigMeta) -> Dict[str, Any]:
    fields = [
        "name",
        "schema_version",
        "version_tag",
        "status",
        "description",
    ]
    result: Dict[str, Any] = {
        "field_changes": {},
        "attribute_changes": {},
    }
    for field in fields:
        base_val = getattr(base, field, None)
        compare_val = getattr(compare, field, None)
        if base_val != compare_val:
            result["field_changes"][field] = {
                "base": base_val,
                "compare": compare_val,
            }

    attr_diff = _diff_dict(base.attributes or {}, compare.attributes or {})
    result["attribute_changes"] = attr_diff

    return result


def _diff_entities(
    name: str,
    base_list: Iterable[Any],
    compare_list: Iterable[Any],
    key_func: Callable[[Any], str],
) -> EntityDiff:
    base_map = {key_func(item): _to_dict(item) for item in base_list}
    compare_map = {key_func(item): _to_dict(item) for item in compare_list}

    base_keys = set(base_map.keys())
    compare_keys = set(compare_map.keys())

    added = sorted(compare_keys - base_keys)
    removed = sorted(base_keys - compare_keys)
    changed = sorted(
        key for key in base_keys & compare_keys if base_map[key] != compare_map[key]
    )

    return EntityDiff(
        name=name,
        base_count=len(base_map),
        compare_count=len(compare_map),
        added=added,
        removed=removed,
        changed=changed,
    )


def _to_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _diff_dict(base: Dict[str, Any], compare: Dict[str, Any]) -> Dict[str, Any]:
    base_keys = set(base.keys())
    compare_keys = set(compare.keys())
    added_keys = sorted(compare_keys - base_keys)
    removed_keys = sorted(base_keys - compare_keys)
    changed_keys: List[str] = []
    changes: Dict[str, Any] = {}
    for key in sorted(base_keys & compare_keys):
        if base[key] != compare[key]:
            changed_keys.append(key)
            changes[key] = {
                "base": base[key],
                "compare": compare[key],
            }
    return {
        "added": added_keys,
        "removed": removed_keys,
        "changed": changed_keys,
        "changes": changes,
    }


__all__ = ["EntityDiff", "diff_canonical_configs"]
