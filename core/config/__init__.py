"""Canonical設定管理のパッケージ。"""

from .models import (
    ConfigMeta,
    CanonicalItem,
    CanonicalNode,
    NodeInventoryPolicy,
    NodeProductionPolicy,
    CanonicalArc,
    CanonicalBom,
    DemandProfile,
    CapacityProfile,
    CalendarDefinition,
    HierarchyEntry,
    CanonicalConfig,
)
from .validators import ValidationIssue, ValidationResult, validate_canonical_config
from .loader import CanonicalLoaderError, load_canonical_config
from .builders import PlanningDataBundle, build_planning_inputs, build_simulation_input
from .storage import (
    CanonicalVersionSummary,
    list_canonical_version_summaries,
    save_canonical_config,
    load_canonical_config_from_db,
    get_canonical_config,
    CanonicalConfigNotFoundError,
)
from .diff import EntityDiff, diff_canonical_configs

__all__ = [
    "ConfigMeta",
    "CanonicalItem",
    "CanonicalNode",
    "NodeInventoryPolicy",
    "NodeProductionPolicy",
    "CanonicalArc",
    "CanonicalBom",
    "DemandProfile",
    "CapacityProfile",
    "CalendarDefinition",
    "HierarchyEntry",
    "CanonicalConfig",
    "ValidationIssue",
    "ValidationResult",
    "validate_canonical_config",
    "CanonicalLoaderError",
    "load_canonical_config",
    "PlanningDataBundle",
    "build_simulation_input",
    "build_planning_inputs",
    "CanonicalVersionSummary",
    "list_canonical_version_summaries",
    "save_canonical_config",
    "load_canonical_config_from_db",
    "get_canonical_config",
    "CanonicalConfigNotFoundError",
    "EntityDiff",
    "diff_canonical_configs",
]
