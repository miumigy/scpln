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
]
