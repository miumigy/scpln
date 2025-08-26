from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class FamilyDemandRecord(BaseModel):
    family: str
    period: str = Field(description="期間キー。例: '2025-01' または 'M1'")
    demand: float = Field(ge=0)


class CapacityRecord(BaseModel):
    workcenter: str
    period: str
    capacity: float = Field(ge=0)


class MixShareRecord(BaseModel):
    family: str
    sku: str
    share: float = Field(ge=0, le=1, description="配賦比率。family内で合計≒1を推奨")


class ItemMasterRecord(BaseModel):
    item: str
    lt: int = Field(ge=0, description="リードタイム（日）")
    lot: float = Field(default=1.0, gt=0, description="発注倍数/ロット")
    moq: float = Field(default=0.0, ge=0)


class InventoryRecord(BaseModel):
    item: str
    loc: str
    qty: float = Field(ge=0)


class OpenPORecord(BaseModel):
    item: str
    due: str = Field(description="入荷期日。例: '2025-01-15' または '2025-01'")
    qty: float = Field(ge=0)


class AggregatePlanInput(BaseModel):
    schema_version: str = Field(default="agg-1.0")
    demand_family: List[FamilyDemandRecord] = Field(default_factory=list)
    capacity: List[CapacityRecord] = Field(default_factory=list)
    mix_share: List[MixShareRecord] = Field(default_factory=list)
    item_master: List[ItemMasterRecord] = Field(default_factory=list)
    inventory: List[InventoryRecord] = Field(default_factory=list)
    open_po: List[OpenPORecord] = Field(default_factory=list)


class AggregatePlanRow(BaseModel):
    family: str
    period: str
    demand: float = 0.0
    supply: float = 0.0
    backlog: float = 0.0


class AggregatePlanOutput(BaseModel):
    schema_version: str = Field(default="agg-1.0")
    rows: List[AggregatePlanRow] = Field(default_factory=list)
    note: Optional[str] = None

