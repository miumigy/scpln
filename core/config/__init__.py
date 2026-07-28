"""Canonical設定管理のパッケージ。"""

from .builders import PlanningDataBundle, build_planning_inputs, build_simulation_input
from .diff import EntityDiff, diff_canonical_configs
from .loader import CanonicalLoaderError, load_canonical_config
from .models import (
    CalendarDefinition,
    CanonicalArc,
    CanonicalBom,
    CanonicalConfig,
    CanonicalItem,
    CanonicalNode,
    CapacityProfile,
    ConfigMeta,
    DemandProfile,
    HierarchyEntry,
    NodeInventoryPolicy,
    NodeProductionPolicy,
)
from .storage import (
    CanonicalConfigNotFoundError,
    CanonicalVersionSummary,
    delete_canonical_config,
    get_canonical_config,
    list_canonical_version_summaries,
    load_canonical_config_from_db,
    save_canonical_config,
)
from .validators import ValidationIssue, ValidationResult, validate_canonical_config

__all__ = [
    "CalendarDefinition",
    "CanonicalArc",
    "CanonicalBom",
    "CanonicalConfig",
    "CanonicalConfigNotFoundError",
    "CanonicalItem",
    "CanonicalLoaderError",
    "CanonicalNode",
    "CanonicalVersionSummary",
    "CapacityProfile",
    "ConfigMeta",
    "DemandProfile",
    "EntityDiff",
    "HierarchyEntry",
    "NodeInventoryPolicy",
    "NodeProductionPolicy",
    "PlanningDataBundle",
    "ValidationIssue",
    "ValidationResult",
    "build_planning_inputs",
    "build_simulation_input",
    "delete_canonical_config",
    "diff_canonical_configs",
    "get_canonical_config",
    "list_canonical_version_summaries",
    "load_canonical_config",
    "load_canonical_config_from_db",
    "save_canonical_config",
    "validate_canonical_config",
]
