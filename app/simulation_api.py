from __future__ import annotations
from pydantic import BaseModel, field_validator

class PlanningRunParams(BaseModel):
    """
    /planning/run と /planning/run_job のためのパラメータモデル。
    FastAPIのバリデーションが空文字""をうまく扱えない問題へのワークアラウンドとして導入。
    バリデーションの前に空文字をNoneに変換する。
    """
    input_dir: str = "samples/planning"
    out_dir: str | None = None
    weeks: int = 4
    round_mode: str = "int"
    lt_unit: str = "day"
    version_id: str = ""
    cutover_date: str | None = None
    recon_window_days: int | None = None
    anchor_policy: str | None = None
    calendar_mode: str | None = None
    carryover: str | None = None
    carryover_split: float | None = None
    blend_split_next: float | None = None
    blend_weight_mode: str | None = None
    max_adjust_ratio: float | None = None
    tol_abs: float | None = None
    tol_rel: float | None = None
    apply_adjusted: int | None = None
    redirect_to_plans: int | None = None

    @field_validator('*', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """すべてのフィールドで、空文字列をNoneに変換する"""
        if v == '':
            return None
        return v