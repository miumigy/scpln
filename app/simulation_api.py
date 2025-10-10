from __future__ import annotations
from pydantic import BaseModel, field_validator
from uuid import uuid4
import logging
from fastapi import Query, Request, HTTPException, APIRouter
from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator
import time
import os
from typing import Optional

from app.metrics import RUNS_TOTAL, SIM_DURATION
from app import run_latest as _run_latest
from core.config import build_simulation_input
from core.config.storage import (
    CanonicalConfigNotFoundError,
    load_canonical_config_from_db,
)

_metrics_path = os.path.join(os.path.dirname(__file__), "metrics.py")
if os.path.exists(_metrics_path):
    with open(_metrics_path, "r") as f:
        print(f"DEBUG: Content of app/metrics.py:\n{f.read()}")


router = APIRouter()


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
    recon_window_days: str | None = None
    anchor_policy: str | None = None
    calendar_mode: str | None = None
    carryover: str | None = None
    carryover_split: str | None = None
    blend_split_next: float | None = None
    blend_weight_mode: str | None = None
    max_adjust_ratio: float | None = None
    tol_abs: str | None = None
    tol_rel: str | None = None
    apply_adjusted: int | None = None
    redirect_to_plans: int | None = None

    @field_validator("*", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        """すべてのフィールドで、空文字列をNoneに変換する"""
        if v == "":
            return None
        return v


def _get_registry():
    from app.run_registry import REGISTRY, _BACKEND, _DB_MAX_ROWS  # type: ignore

    return REGISTRY, _BACKEND, _DB_MAX_ROWS


@router.post("/simulation")
def post_simulation(
    payload: SimulationInput | None = None,
    include_trace: bool = Query(False),
    config_id: int | None = Query(None),
    scenario_id: int | None = Query(None),
    config_version_id: int | None = Query(
        None,
        description="Canonical設定のバージョンID。指定時はCanonicalから入力を生成",
    ),
    request: Request = None,
):
    canonical_version_id: Optional[int] = config_version_id
    canonical_config = None
    canonical_validation = None

    if canonical_version_id is not None:
        try:
            canonical_config, canonical_validation = load_canonical_config_from_db(
                canonical_version_id, validate=True
            )
        except CanonicalConfigNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        if canonical_validation and canonical_validation.has_errors:
            errors = [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "context": issue.context,
                }
                for issue in canonical_validation.issues
                if issue.severity == "error"
            ]
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "canonical config validation failed",
                    "errors": errors,
                },
            )

        payload = build_simulation_input(canonical_config)

    if payload is None:
        raise HTTPException(status_code=400, detail="simulation payload is required")

    # RBAC（ライト）: 変更系のためロール/テナント必須（有効化時）
    import os

    if os.getenv("RBAC_ENABLED", "0") == "1":
        role = request.headers.get("X-Role") if request else None
        org = request.headers.get("X-Org-ID") if request else None
        tenant = request.headers.get("X-Tenant-ID") if request else None
        allowed = {
            x.strip()
            for x in (os.getenv("RBAC_MUTATE_ROLES", "planner,admin").split(","))
            if x.strip()
        }
        if not role or role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden: role not allowed")
        if not org or not tenant:
            raise HTTPException(status_code=400, detail="missing org/tenant headers")

    run_id = str(uuid4())
    start = time.time()
    logging.info("run_started", extra={"event": "run_started", "run_id": run_id})
    sim = SupplyChainSimulator(payload)
    results, daily_pl = sim.run()
    duration_ms = int((time.time() - start) * 1000)
    try:
        SIM_DURATION.observe(duration_ms)
        RUNS_TOTAL.inc()
    except Exception:
        pass
    try:
        summary = sim.compute_summary()
    except Exception:
        summary = {}
    # optional: attach config context (id and json) when provided
    # fallback: header X-Config-Id
    try:
        if config_id is None and canonical_version_id is None and request is not None:
            hdr = request.headers.get("X-Config-Id")
            if hdr:
                config_id = int(hdr)
    except Exception:
        pass

    cfg_json = None
    if canonical_config is not None:
        try:
            cfg_json = canonical_config.model_dump(mode="json")
        except Exception:
            cfg_json = None
    else:
        try:
            if payload is not None:
                cfg_json = payload.model_dump()
        except Exception:
            cfg_json = None

    REGISTRY, _BACKEND, _DB_MAX_ROWS = _get_registry()
    REGISTRY.put(
        run_id,
        {
            "run_id": run_id,
            "started_at": int(start * 1000),
            "duration_ms": duration_ms,
            "schema_version": getattr(payload, "schema_version", "1.0"),
            "summary": summary,
            # 後から参照できるよう主要出力も保存
            "results": results,
            "daily_profit_loss": daily_pl,
            "cost_trace": getattr(sim, "cost_trace", []),
            "config_id": config_id,
            "config_version_id": canonical_version_id,
            "scenario_id": scenario_id,
            "config_json": cfg_json,
        },
    )
    try:
        _run_latest.record(scenario_id, run_id)
    except Exception:
        pass
    try:
        logging.debug(
            "config_saved",
            extra={
                "event": "config_saved",
                "route": "/simulation",
                "run_id": run_id,
                "config_id": config_id,
                "config_json_present": bool(cfg_json),
            },
        )
    except Exception:
        pass
    # DB使用時は容量上限で古いRunをクリーンアップ
    try:
        if (
            (_BACKEND == "db")
            and (_DB_MAX_ROWS > 0)
            and hasattr(REGISTRY, "cleanup_by_capacity")
        ):
            REGISTRY.cleanup_by_capacity(_DB_MAX_ROWS)
    except Exception:
        pass
    logging.info(
        "run_completed",
        extra={
            "event": "run_completed",
            "run_id": run_id,
            "duration": duration_ms,
            "results": len(results or []),
            "pl_days": len(daily_pl or []),
            "trace_events": len(getattr(sim, "cost_trace", []) or []),
            "schema": getattr(payload, "schema_version", "1.0"),
        },
    )
    # UIとの互換性のため、profit_loss と summary も返す。
    # また、トレースCSV用途で cost_trace も常に返す（サイズ増を許容）。
    resp = {
        "run_id": run_id,
        "results": results,
        "daily_profit_loss": daily_pl,
        "profit_loss": daily_pl,
        "summary": summary,
        "cost_trace": getattr(sim, "cost_trace", []),
    }
    if canonical_version_id is not None:
        resp["config_version_id"] = canonical_version_id
        if canonical_validation:
            warnings = [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "context": issue.context,
                }
                for issue in canonical_validation.issues
                if issue.severity == "warning"
            ]
            if warnings:
                resp["validation_warnings"] = warnings
    return resp


# FastAPI appへルーターを登録（import時の副作用で有効化）
try:
    from app.api import app as _app  # 循環依存を避けるため遅延import

    _app.include_router(router)
except Exception:
    # テストや一部実行環境での遅延初期化に備え、失敗しても例外は伝播しない
    pass
