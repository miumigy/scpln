from typing import Dict, Any
from fastapi import HTTPException, Request
from fastapi import Body
from app.api import app
from app import db
import logging
import os
import threading
import json
import requests


def _ensure_run_exists(run_id: str) -> None:
    """Runの存在確認。
    1) メモリREGISTRY
    2) DBのrunsテーブル
    いずれにも無ければ404。
    """
    try:
        from app.run_registry import REGISTRY  # type: ignore

        rec = REGISTRY.get(run_id)
        if rec:
            return
    except Exception:
        pass
    # Fallback to DB
    try:
        from app import db as _db

        with _db._conn() as c:  # type: ignore[attr-defined]
            row = c.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row:
                return
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="run not found")


def _require_role(request: Request, *, action: str) -> None:
    """RBACライト: RBAC_ENABLED=1 のとき、X-Role を検証。
    - 環境変数で許可ロールを上書き可能（例: RBAC_APPROVE_ROLES="approver,lead,admin"）
    - 無効時（RBAC_ENABLED!=1）はスキップ
    """
    if os.getenv("RBAC_ENABLED", "0") != "1":
        return
    role = request.headers.get("X-Role", "").strip()
    env_key = {
        "approve": "RBAC_APPROVE_ROLES",
        "promote": "RBAC_PROMOTE_ROLES",
        "archive": "RBAC_ARCHIVE_ROLES",
        "note": "RBAC_MUTATE_ROLES",
    }.get(action)
    default_roles = {
        "approve": "approver,lead,admin",
        "promote": "approver,lead,admin",
        "archive": "planner,admin",
        "note": "planner,approver,lead,admin",
    }[action]
    allowed = {
        x.strip()
        for x in (os.getenv(env_key or "", default_roles).split(","))
        if x.strip()
    }
    if role not in allowed:
        raise HTTPException(status_code=403, detail="forbidden: role not allowed")


def _notify(event: str, payload: dict) -> None:
    """Webhook通知（ベストエフォート）。
    - NOTIFY_WEBHOOK_URLS にカンマ区切りで指定
    - タイムアウト短め、失敗は無視
    """
    urls = [
        u.strip() for u in os.getenv("NOTIFY_WEBHOOK_URLS", "").split(",") if u.strip()
    ]
    if not urls:
        return
    body = {"event": event, **payload}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-Scpln-Event": event}
    secret = os.getenv("NOTIFY_WEBHOOK_SECRET", "")
    if secret:
        try:
            import hmac
            import hashlib

            sig = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()
            headers["X-Scpln-Signature"] = f"sha256={sig}"
        except Exception:
            pass

    def _post(u: str):
        try:
            # 簡易リトライ（合計3回）
            for i in range(3):
                try:
                    requests.post(u, data=data, headers=headers, timeout=3)
                    break
                except Exception:
                    import time as _t

                    _t.sleep(0.5 * (i + 1))
        except Exception:
            pass

    for u in urls:
        threading.Thread(target=_post, args=(u,), daemon=True).start()


@app.get("/runs/{run_id}/meta")
def get_run_meta(run_id: str) -> Dict[str, Any]:
    _ensure_run_exists(run_id)
    meta = db.get_run_meta(run_id)
    return meta


@app.get("/runs/meta")
def get_runs_meta(run_ids: str) -> Dict[str, Dict[str, Any]]:
    ids = [x.strip() for x in (run_ids or "").split(",") if x.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="run_ids required")
    return db.get_runs_meta_bulk(ids)


@app.post("/runs/{run_id}/approve")
def post_approve(run_id: str, request: Request) -> Dict[str, Any]:
    _ensure_run_exists(run_id)
    _require_role(request, action="approve")
    user = request.headers.get("X-User") or request.headers.get("X-Email") or ""
    db.approve_run(run_id, approved_by=user or None)
    logging.info(
        "run_approved", extra={"event": "run_approved", "run_id": run_id, "user": user}
    )
    _notify("run_approved", {"run_id": run_id, "user": user})
    return {"status": "approved", "run_id": run_id, "approved_by": user}


@app.post("/runs/{run_id}/promote-baseline")
def post_promote_baseline(run_id: str, request: Request) -> Dict[str, Any]:
    _ensure_run_exists(run_id)
    _require_role(request, action="promote")
    db.set_baseline(run_id)
    logging.info(
        "run_promoted_baseline",
        extra={"event": "run_promoted_baseline", "run_id": run_id},
    )
    _notify("run_promoted_baseline", {"run_id": run_id})
    return {"status": "baseline", "run_id": run_id}


@app.post("/runs/{run_id}/archive")
def post_archive(run_id: str, request: Request) -> Dict[str, Any]:
    _ensure_run_exists(run_id)
    _require_role(request, action="archive")
    db.set_archived(run_id, True)
    logging.info("run_archived", extra={"event": "run_archived", "run_id": run_id})
    _notify("run_archived", {"run_id": run_id})
    return {"status": "archived", "run_id": run_id}


@app.post("/runs/{run_id}/unarchive")
def post_unarchive(run_id: str, request: Request) -> Dict[str, Any]:
    _ensure_run_exists(run_id)
    _require_role(request, action="archive")
    db.set_archived(run_id, False)
    logging.info("run_unarchived", extra={"event": "run_unarchived", "run_id": run_id})
    _notify("run_unarchived", {"run_id": run_id})
    return {"status": "unarchived", "run_id": run_id}


@app.post("/runs/{run_id}/note")
def post_note(
    run_id: str, request: Request, body: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    _ensure_run_exists(run_id)
    _require_role(request, action="note")
    note = (body.get("note") or "").strip()
    db.upsert_run_meta(run_id, note=note)
    logging.info("run_note_saved", extra={"event": "run_note_saved", "run_id": run_id})
    return {"status": "ok"}


@app.get("/runs/baseline")
def get_baseline(scenario_id: int) -> Dict[str, Any]:
    # DBからbaseline取得
    rid = db.get_baseline_run_id(int(scenario_id))
    return {"run_id": rid}
