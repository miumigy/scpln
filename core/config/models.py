"""Canonical設定モデル定義。

PSIシミュレーションとPlanning Hubが共通で参照する設定スキーマをPydantic
モデルとして集約する。後続フェーズでDB永続化やビルダーと連携する。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanningCalendarWeek(BaseModel):
    week_code: str
    sequence: int
    start_date: date
    end_date: date
    weight: float = 1.0
    attributes: dict[str, Any] = Field(default_factory=dict)


class PlanningCalendarPeriod(BaseModel):
    period: str
    start_date: date
    end_date: date
    weeks: list[PlanningCalendarWeek] = Field(default_factory=list)


class PlanningParams(BaseModel):
    default_anchor_policy: str | None = None
    tolerance_abs: float = 1e-6
    tolerance_rel: float = 1e-6
    carryover_mode: str = "auto"
    carryover_split: float = 0.8
    lt_unit: str = "day"
    recon_window_days: int = 14


class PlanningCalendarSpec(BaseModel):
    calendar_type: str = "custom"
    week_unit: str = "day"
    periods: list[PlanningCalendarPeriod] = Field(default_factory=list)
    planning_params: PlanningParams | None = None


class PlanningFamilyDemand(BaseModel):
    family_code: str = Field(description="製品ファミリキー")
    period: str = Field(description="計画期間キー（例: 2025-01, 2025-W03）")
    demand: float = Field(ge=0.0)
    source_type: Literal["canonical", "override", "imported"] = Field(
        default="canonical"
    )
    tolerance_abs: float | None = Field(default=None, ge=0.0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class PlanningCapacityBucket(BaseModel):
    resource_code: str = Field(description="能力リソース/ノードコード")
    resource_type: Literal["workcenter", "node", "supplier"] = Field(
        default="workcenter"
    )
    period: str = Field(description="計画期間キー")
    capacity: float = Field(ge=0.0)
    calendar_code: str | None = Field(default=None)
    attributes: dict[str, Any] = Field(default_factory=dict)


class PlanningMixShare(BaseModel):
    family_code: str = Field(description="ファミリコード")
    sku_code: str = Field(description="SKUコード")
    share: float = Field(ge=0.0, le=1.0)
    effective_from: date | None = Field(default=None)
    effective_to: date | None = Field(default=None)
    weight_source: Literal["historical", "manual", "promotion", "other"] = Field(
        default="manual"
    )
    attributes: dict[str, Any] = Field(default_factory=dict)


class PlanningInventorySnapshot(BaseModel):
    node_code: str = Field(description="ノードコード")
    item_code: str = Field(description="品目コード")
    initial_qty: float = Field(ge=0.0)
    reorder_point: float | None = Field(default=None, ge=0.0)
    order_up_to: float | None = Field(default=None, ge=0.0)
    safety_stock: float | None = Field(default=None, ge=0.0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class PlanningInboundOrder(BaseModel):
    po_id: str | None = Field(
        default=None, description="外部参照ID（未指定なら内部IDを付与）"
    )
    item_code: str = Field(description="品目コード")
    source_node: str | None = Field(
        default=None, description="供給元ノード（ない場合はグローバル）"
    )
    dest_node: str | None = Field(
        default=None, description="受け取りノード（Noneでdefault_location）"
    )
    due_date: str = Field(description="入荷期日（ISO日付または期間キー）")
    qty: float = Field(ge=0.0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class PlanningPeriodMetric(BaseModel):
    metric_code: Literal["cost", "score", "custom"] = Field(default="cost")
    period: str = Field(description="計画期間キー")
    value: float = Field()
    unit: str | None = Field(default=None)
    source: str | None = Field(default=None)
    attributes: dict[str, Any] = Field(default_factory=dict)


class PlanningInputAggregates(BaseModel):
    family_demands: list[PlanningFamilyDemand] = Field(default_factory=list)
    capacity_buckets: list[PlanningCapacityBucket] = Field(default_factory=list)
    mix_shares: list[PlanningMixShare] = Field(default_factory=list)
    inventory_snapshots: list[PlanningInventorySnapshot] = Field(default_factory=list)
    inbound_orders: list[PlanningInboundOrder] = Field(default_factory=list)
    period_metrics: list[PlanningPeriodMetric] = Field(default_factory=list)


class PlanningInputSet(BaseModel):
    id: int | None = Field(default=None, description="InputSet内部ID")
    config_version_id: int = Field(description="対象 Canonical version ID")
    label: str = Field(description="InputSet 表示名")
    status: Literal["draft", "ready", "archived"] = Field(default="draft")
    source: Literal["csv", "ui", "api", "seed"] = Field(default="csv")
    created_by: str | None = Field(default=None)
    created_at: int | None = Field(default=None, description="UNIX ms")
    updated_at: int | None = Field(default=None, description="UNIX ms")
    approved_by: str | None = Field(default=None, description="承認者")
    approved_at: int | None = Field(default=None, description="承認日時 (UNIX ms)")
    review_comment: str | None = Field(default=None, description="承認/差戻しコメント")
    metadata: dict[str, Any] = Field(default_factory=dict)
    calendar_spec: PlanningCalendarSpec | None = Field(default=None)
    planning_params: PlanningParams | None = Field(default=None)
    aggregates: PlanningInputAggregates = Field(default_factory=PlanningInputAggregates)


class PlanningInputSetEvent(BaseModel):
    id: int | None = Field(default=None)
    input_set_id: int
    action: Literal["upload", "update", "approve", "revert"]
    actor: str | None = None
    comment: str | None = None
    created_at: int | None = Field(default=None, description="UNIX ms")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfigMeta(BaseModel):
    """設定バージョンのメタ情報。"""

    version_id: int | None = Field(default=None, description="DB上の設定バージョンID")
    name: str = Field(description="設定名")
    schema_version: str = Field(default="canonical-1.0")
    version_tag: str | None = Field(default=None, description="外部向けバージョンタグ")
    status: Literal["draft", "active", "archived"] = Field(default="draft")
    description: str | None = Field(default=None)
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="追加のメタデータ"
    )
    source_config_id: int | None = Field(
        default=None, description="旧`configs`テーブル由来のID"
    )
    parent_version_id: int | None = Field(
        default=None, description="このConfigが派生した元のConfigのバージョンID"
    )
    is_deleted: bool = Field(default=False, description="論理削除フラグ")
    created_at: int | None = Field(default=None, description="ミリ秒UNIX時間")
    updated_at: int | None = Field(default=None, description="ミリ秒UNIX時間")
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="タグや任意属性"
    )


class CanonicalItem(BaseModel):
    """品目マスタ。"""

    code: str = Field(description="品目コード")
    name: str | None = Field(default=None)
    item_type: Literal["product", "material", "component", "service"] = Field(
        default="product"
    )
    uom: str = Field(default="unit", description="単位")
    lead_time_days: int = Field(default=0, ge=0)
    lot_size: float | None = Field(default=None, gt=0)
    min_order_qty: float | None = Field(default=None, ge=0)
    safety_stock: float | None = Field(default=None, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class NodeInventoryPolicy(BaseModel):
    """ノード×品目の在庫・補充ポリシー。"""

    item_code: str = Field(description="品目コード")
    initial_inventory: float = Field(default=0.0)
    reorder_point: float | None = Field(default=None)
    order_up_to: float | None = Field(default=None)
    min_order_qty: float | None = Field(default=None, ge=0)
    order_multiple: float | None = Field(default=None, gt=0)
    safety_stock: float | None = Field(default=None, ge=0)
    storage_cost: float | None = Field(default=None, ge=0)
    stockout_cost: float | None = Field(default=None, ge=0)
    backorder_cost: float | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class NodeProductionPolicy(BaseModel):
    """生産ノード向けの生産能力・コストパラメータ。"""

    item_code: str | None = Field(default=None, description="対象品目。Noneで全体適用")
    production_capacity: float | None = Field(default=None, ge=0)
    allow_over_capacity: bool = Field(default=True)
    over_capacity_fixed_cost: float | None = Field(default=None, ge=0)
    over_capacity_variable_cost: float | None = Field(default=None, ge=0)
    production_cost_fixed: float | None = Field(default=None, ge=0)
    production_cost_variable: float | None = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CanonicalNode(BaseModel):
    """ノードマスタ。"""

    code: str = Field(description="ノードコード")
    name: str | None = Field(default=None)
    node_type: Literal["store", "warehouse", "factory", "supplier", "material"]
    timezone: str | None = Field(default=None)
    region: str | None = Field(default=None)
    service_level: float | None = Field(default=None, ge=0, le=1)
    lead_time_days: int = Field(default=0, ge=0)
    storage_capacity: float | None = Field(default=None, ge=0)
    allow_storage_over_capacity: bool = Field(default=True)
    storage_cost_fixed: float | None = Field(default=None, ge=0)
    storage_over_capacity_fixed_cost: float | None = Field(default=None, ge=0)
    storage_over_capacity_variable_cost: float | None = Field(default=None, ge=0)
    review_period_days: int | None = Field(default=None, ge=0)
    inventory_policies: list[NodeInventoryPolicy] = Field(default_factory=list)
    production_policies: list[NodeProductionPolicy] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CanonicalArc(BaseModel):
    """ノード間リンク。"""

    from_node: str = Field(description="出発ノード")
    to_node: str = Field(description="到着ノード")
    arc_type: Literal["transport", "supply", "distribution"] = Field(
        default="transport"
    )
    lead_time_days: int = Field(default=0, ge=0)
    capacity_per_day: float | None = Field(default=None, ge=0)
    allow_over_capacity: bool = Field(default=True)
    transportation_cost_fixed: float | None = Field(default=None, ge=0)
    transportation_cost_variable: float | None = Field(default=None, ge=0)
    min_order_qty: dict[str, float] = Field(default_factory=dict)
    order_multiple: dict[str, float] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CanonicalBom(BaseModel):
    """BOM構成。"""

    parent_item: str = Field(description="親品目")
    child_item: str = Field(description="子品目")
    quantity: float = Field(gt=0)
    scrap_rate: float | None = Field(default=None, ge=0, le=1)
    attributes: dict[str, Any] = Field(default_factory=dict)


class DemandProfile(BaseModel):
    """需要プロファイル。"""

    node_code: str = Field(description="需要ノード")
    item_code: str = Field(description="対象品目")
    bucket: str = Field(description="需要バケット。例: 'D1' や '2025-01'")
    demand_model: Literal["normal", "deterministic"] = Field(default="normal")
    mean: float = Field(ge=0)
    std_dev: float | None = Field(default=None, ge=0)
    min_qty: float | None = Field(default=None, ge=0)
    max_qty: float | None = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CapacityProfile(BaseModel):
    """能力・稼働プロファイル。"""

    resource_code: str = Field(description="リソース/ノードコード")
    resource_type: Literal["workcenter", "node", "supplier"] = Field(default="node")
    bucket: str = Field(description="能力バケット")
    capacity: float = Field(ge=0)
    calendar_code: str | None = Field(default=None)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CalendarDefinition(BaseModel):
    """稼働カレンダー定義。"""

    calendar_code: str
    timezone: str | None = Field(default=None)
    definition: dict[str, Any] = Field(
        default_factory=dict, description="営業日/例外日などのカレンダー情報"
    )
    attributes: dict[str, Any] = Field(default_factory=dict)


class HierarchyEntry(BaseModel):
    """製品・ロケーション階層。"""

    hierarchy_type: Literal["product", "location"]
    node_key: str = Field(description="階層キー")
    parent_key: str | None = Field(default=None)
    level: str | None = Field(default=None)
    sort_order: int | None = Field(default=None)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CanonicalConfig(BaseModel):
    """Canonical設定スナップショット。"""

    meta: ConfigMeta
    items: list[CanonicalItem] = Field(default_factory=list)
    nodes: list[CanonicalNode] = Field(default_factory=list)
    arcs: list[CanonicalArc] = Field(default_factory=list)
    bom: list[CanonicalBom] = Field(default_factory=list)
    demands: list[DemandProfile] = Field(default_factory=list)
    capacities: list[CapacityProfile] = Field(default_factory=list)
    calendars: list[CalendarDefinition] = Field(default_factory=list)
    hierarchies: list[HierarchyEntry] = Field(default_factory=list)


__all__ = [
    "CalendarDefinition",
    "CanonicalArc",
    "CanonicalBom",
    "CanonicalConfig",
    "CanonicalItem",
    "CanonicalNode",
    "CapacityProfile",
    "ConfigMeta",
    "DemandProfile",
    "HierarchyEntry",
    "NodeInventoryPolicy",
    "NodeProductionPolicy",
    "PlanningCalendarPeriod",
    "PlanningCalendarSpec",
    "PlanningCalendarWeek",
    "PlanningCapacityBucket",
    "PlanningFamilyDemand",
    "PlanningInboundOrder",
    "PlanningInputAggregates",
    "PlanningInputSet",
    "PlanningInputSetEvent",
    "PlanningInventorySnapshot",
    "PlanningMixShare",
    "PlanningParams",
    "PlanningPeriodMetric",
]
