"""Canonical設定モデル定義。

PSIシミュレーションとPlanning Hubが共通で参照する設定スキーマをPydantic
モデルとして集約する。後続フェーズでDB永続化やビルダーと連携する。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from datetime import date

from pydantic import BaseModel, Field


class PlanningCalendarWeek(BaseModel):
    week_code: str
    sequence: int
    start_date: date
    end_date: date
    weight: float = 1.0
    attributes: Dict[str, Any] = Field(default_factory=dict)


class PlanningCalendarPeriod(BaseModel):
    period: str
    start_date: date
    end_date: date
    weeks: List[PlanningCalendarWeek] = Field(default_factory=list)


class PlanningParams(BaseModel):
    default_anchor_policy: Optional[str] = None
    tolerance_abs: float = 1e-6
    tolerance_rel: float = 1e-6
    carryover_mode: str = "auto"
    carryover_split: float = 0.8
    lt_unit: str = "day"
    recon_window_days: int = 14


class PlanningCalendarSpec(BaseModel):
    calendar_type: str = "custom"
    week_unit: str = "day"
    periods: List[PlanningCalendarPeriod] = Field(default_factory=list)
    planning_params: Optional[PlanningParams] = None


class ConfigMeta(BaseModel):
    """設定バージョンのメタ情報。"""

    version_id: Optional[int] = Field(
        default=None, description="DB上の設定バージョンID"
    )
    name: str = Field(description="設定名")
    schema_version: str = Field(default="canonical-1.0")
    version_tag: Optional[str] = Field(
        default=None, description="外部向けバージョンタグ"
    )
    status: Literal["draft", "active", "archived"] = Field(default="draft")
    description: Optional[str] = Field(default=None)
    attributes: Dict[str, Any] = Field(
        default_factory=dict, description="追加のメタデータ"
    )
    source_config_id: Optional[int] = Field(
        default=None, description="旧`configs`テーブル由来のID"
    )
    parent_version_id: Optional[int] = Field(
        default=None, description="このConfigが派生した元のConfigのバージョンID"
    )
    is_deleted: bool = Field(default=False, description="論理削除フラグ")
    created_at: Optional[int] = Field(default=None, description="ミリ秒UNIX時間")
    updated_at: Optional[int] = Field(default=None, description="ミリ秒UNIX時間")
    attributes: Dict[str, Any] = Field(
        default_factory=dict, description="タグや任意属性"
    )


class CanonicalItem(BaseModel):
    """品目マスタ。"""

    code: str = Field(description="品目コード")
    name: Optional[str] = Field(default=None)
    item_type: Literal["product", "material", "component", "service"] = Field(
        default="product"
    )
    uom: str = Field(default="unit", description="単位")
    lead_time_days: int = Field(default=0, ge=0)
    lot_size: Optional[float] = Field(default=None, gt=0)
    min_order_qty: Optional[float] = Field(default=None, ge=0)
    safety_stock: Optional[float] = Field(default=None, ge=0)
    unit_cost: Optional[float] = Field(default=None, ge=0)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class NodeInventoryPolicy(BaseModel):
    """ノード×品目の在庫・補充ポリシー。"""

    item_code: str = Field(description="品目コード")
    initial_inventory: float = Field(default=0.0)
    reorder_point: Optional[float] = Field(default=None)
    order_up_to: Optional[float] = Field(default=None)
    min_order_qty: Optional[float] = Field(default=None, ge=0)
    order_multiple: Optional[float] = Field(default=None, gt=0)
    safety_stock: Optional[float] = Field(default=None, ge=0)
    storage_cost: Optional[float] = Field(default=None, ge=0)
    stockout_cost: Optional[float] = Field(default=None, ge=0)
    backorder_cost: Optional[float] = Field(default=None, ge=0)
    lead_time_days: Optional[int] = Field(default=None, ge=0)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class NodeProductionPolicy(BaseModel):
    """生産ノード向けの生産能力・コストパラメータ。"""

    item_code: Optional[str] = Field(
        default=None, description="対象品目。Noneで全体適用"
    )
    production_capacity: Optional[float] = Field(default=None, ge=0)
    allow_over_capacity: bool = Field(default=True)
    over_capacity_fixed_cost: Optional[float] = Field(default=None, ge=0)
    over_capacity_variable_cost: Optional[float] = Field(default=None, ge=0)
    production_cost_fixed: Optional[float] = Field(default=None, ge=0)
    production_cost_variable: Optional[float] = Field(default=None, ge=0)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class CanonicalNode(BaseModel):
    """ノードマスタ。"""

    code: str = Field(description="ノードコード")
    name: Optional[str] = Field(default=None)
    node_type: Literal["store", "warehouse", "factory", "supplier", "material"]
    timezone: Optional[str] = Field(default=None)
    region: Optional[str] = Field(default=None)
    service_level: Optional[float] = Field(default=None, ge=0, le=1)
    lead_time_days: int = Field(default=0, ge=0)
    storage_capacity: Optional[float] = Field(default=None, ge=0)
    allow_storage_over_capacity: bool = Field(default=True)
    storage_cost_fixed: Optional[float] = Field(default=None, ge=0)
    storage_over_capacity_fixed_cost: Optional[float] = Field(default=None, ge=0)
    storage_over_capacity_variable_cost: Optional[float] = Field(default=None, ge=0)
    review_period_days: Optional[int] = Field(default=None, ge=0)
    inventory_policies: List[NodeInventoryPolicy] = Field(default_factory=list)
    production_policies: List[NodeProductionPolicy] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class CanonicalArc(BaseModel):
    """ノード間リンク。"""

    from_node: str = Field(description="出発ノード")
    to_node: str = Field(description="到着ノード")
    arc_type: Literal["transport", "supply", "distribution"] = Field(
        default="transport"
    )
    lead_time_days: int = Field(default=0, ge=0)
    capacity_per_day: Optional[float] = Field(default=None, ge=0)
    allow_over_capacity: bool = Field(default=True)
    transportation_cost_fixed: Optional[float] = Field(default=None, ge=0)
    transportation_cost_variable: Optional[float] = Field(default=None, ge=0)
    min_order_qty: Dict[str, float] = Field(default_factory=dict)
    order_multiple: Dict[str, float] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class CanonicalBom(BaseModel):
    """BOM構成。"""

    parent_item: str = Field(description="親品目")
    child_item: str = Field(description="子品目")
    quantity: float = Field(gt=0)
    scrap_rate: Optional[float] = Field(default=None, ge=0, le=1)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class DemandProfile(BaseModel):
    """需要プロファイル。"""

    node_code: str = Field(description="需要ノード")
    item_code: str = Field(description="対象品目")
    bucket: str = Field(description="需要バケット。例: 'D1' や '2025-01'")
    demand_model: Literal["normal", "deterministic"] = Field(default="normal")
    mean: float = Field(ge=0)
    std_dev: Optional[float] = Field(default=None, ge=0)
    min_qty: Optional[float] = Field(default=None, ge=0)
    max_qty: Optional[float] = Field(default=None, ge=0)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class CapacityProfile(BaseModel):
    """能力・稼働プロファイル。"""

    resource_code: str = Field(description="リソース/ノードコード")
    resource_type: Literal["workcenter", "node", "supplier"] = Field(default="node")
    bucket: str = Field(description="能力バケット")
    capacity: float = Field(ge=0)
    calendar_code: Optional[str] = Field(default=None)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class CalendarDefinition(BaseModel):
    """稼働カレンダー定義。"""

    calendar_code: str
    timezone: Optional[str] = Field(default=None)
    definition: Dict[str, Any] = Field(
        default_factory=dict, description="営業日/例外日などのカレンダー情報"
    )
    attributes: Dict[str, Any] = Field(default_factory=dict)


class HierarchyEntry(BaseModel):
    """製品・ロケーション階層。"""

    hierarchy_type: Literal["product", "location"]
    node_key: str = Field(description="階層キー")
    parent_key: Optional[str] = Field(default=None)
    level: Optional[str] = Field(default=None)
    sort_order: Optional[int] = Field(default=None)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class CanonicalConfig(BaseModel):
    """Canonical設定スナップショット。"""

    meta: ConfigMeta
    items: List[CanonicalItem] = Field(default_factory=list)
    nodes: List[CanonicalNode] = Field(default_factory=list)
    arcs: List[CanonicalArc] = Field(default_factory=list)
    bom: List[CanonicalBom] = Field(default_factory=list)
    demands: List[DemandProfile] = Field(default_factory=list)
    capacities: List[CapacityProfile] = Field(default_factory=list)
    calendars: List[CalendarDefinition] = Field(default_factory=list)
    hierarchies: List[HierarchyEntry] = Field(default_factory=list)


__all__ = [
    "ConfigMeta",
    "CanonicalItem",
    "NodeInventoryPolicy",
    "NodeProductionPolicy",
    "CanonicalNode",
    "CanonicalArc",
    "CanonicalBom",
    "DemandProfile",
    "CapacityProfile",
    "CalendarDefinition",
    "HierarchyEntry",
    "CanonicalConfig",
    "PlanningCalendarWeek",
    "PlanningCalendarPeriod",
    "PlanningParams",
    "PlanningCalendarSpec",
]
