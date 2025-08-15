from typing import List, Dict, Literal, Annotated, Union, Optional
import sys

from pydantic import BaseModel, Field


class BomItem(BaseModel):
    item_name: str
    quantity_per: float = Field(gt=0)


class Product(BaseModel):
    name: str
    sales_price: float = Field(default=0, ge=0)
    assembly_bom: List[BomItem] = Field(default=[])


class NetworkLink(BaseModel):
    from_node: str
    to_node: str
    transportation_cost_fixed: float = Field(default=0, ge=0)
    transportation_cost_variable: float = Field(default=0, ge=0)
    lead_time: int = Field(default=0, ge=0)
    capacity_per_day: float = Field(default=sys.float_info.max, gt=0)
    allow_over_capacity: bool = Field(default=True)
    over_capacity_fixed_cost: float = Field(default=0, ge=0)
    over_capacity_variable_cost: float = Field(default=0, ge=0)
    moq: Dict[str, float] = Field(default_factory=dict)
    order_multiple: Dict[str, float] = Field(default_factory=dict)


class BaseNode(BaseModel):
    name: str
    initial_stock: Dict[str, float] = Field(default_factory=dict)
    lead_time: int = Field(default=1, ge=0)
    storage_cost_fixed: float = Field(default=0, ge=0)
    storage_cost_variable: Dict[str, float] = Field(default_factory=dict)
    backorder_enabled: bool = Field(default=True)
    # 欠品時の販売逸失モード（true の場合はバックオーダーを保持しない）
    lost_sales: bool = Field(default=False)
    # レビュー間隔（日）。R=0で従来互換。
    review_period_days: int = Field(default=0, ge=0)
    # ペナルティコスト
    stockout_cost_per_unit: float = Field(default=0, ge=0)
    backorder_cost_per_unit_per_day: float = Field(default=0, ge=0)
    storage_capacity: float = Field(default=sys.float_info.max, gt=0)
    allow_storage_over_capacity: bool = Field(default=True)
    storage_over_capacity_fixed_cost: float = Field(default=0, ge=0)
    storage_over_capacity_variable_cost: float = Field(default=0, ge=0)


class StoreNode(BaseNode):
    node_type: Literal["store"] = "store"
    service_level: float = Field(default=0.95, ge=0, le=1)
    backorder_enabled: bool = Field(default=True)
    moq: Dict[str, float] = Field(default_factory=dict)
    order_multiple: Dict[str, float] = Field(default_factory=dict)


class WarehouseNode(BaseNode):
    node_type: Literal["warehouse"] = "warehouse"
    service_level: float = Field(default=0.95, ge=0, le=1)
    moq: Dict[str, float] = Field(default_factory=dict)
    order_multiple: Dict[str, float] = Field(default_factory=dict)


class MaterialNode(BaseNode):
    node_type: Literal["material"] = "material"
    material_cost: Dict[str, float] = Field(default_factory=dict)


class FactoryNode(BaseNode):
    node_type: Literal["factory"] = "factory"
    producible_products: List[str]
    service_level: float = Field(default=0.95, ge=0, le=1)
    production_capacity: float = Field(default=sys.float_info.max, gt=0)
    production_cost_fixed: float = Field(default=0, ge=0)
    production_cost_variable: float = Field(default=0, ge=0)
    allow_production_over_capacity: bool = Field(default=True)
    production_over_capacity_fixed_cost: float = Field(default=0, ge=0)
    production_over_capacity_variable_cost: float = Field(default=0, ge=0)
    reorder_point: Dict[str, float] = Field(default_factory=dict)
    order_up_to_level: Dict[str, float] = Field(default_factory=dict)
    moq: Dict[str, float] = Field(default_factory=dict)
    order_multiple: Dict[str, float] = Field(default_factory=dict)


AnyNode = Annotated[
    Union[StoreNode, WarehouseNode, MaterialNode, FactoryNode],
    Field(discriminator="node_type"),
]


class CustomerDemand(BaseModel):
    store_name: str
    product_name: str
    demand_mean: float = Field(ge=0)
    demand_std_dev: float = Field(ge=0)


class SimulationInput(BaseModel):
    schema_version: str = Field(default="1.0")
    planning_horizon: int = Field(gt=0)
    products: List[Product]
    nodes: List[AnyNode]
    network: List[NetworkLink]
    customer_demand: List[CustomerDemand]
    random_seed: Optional[int] = None
