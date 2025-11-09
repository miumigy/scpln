import os
import json
import sqlite3
import time
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.metrics import PLAN_ARTIFACT_WRITE_ERROR_TOTAL


_BASE_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _BASE_DIR / "data" / "scpln.db"
_current_db_path: str | None = None

_logger = logging.getLogger(__name__)
_init_lock = threading.Lock()
_initialized = False

Path(_DEFAULT_DB).parent.mkdir(parents=True, exist_ok=True)


def set_db_path(path: str) -> None:
    global _current_db_path
    _current_db_path = path


def _db_path() -> str:
    path = (
        _current_db_path
        if _current_db_path is not None
        else os.getenv("SCPLN_DB", str(_DEFAULT_DB))
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _conn() -> sqlite3.Connection:
    db_path_to_use = _db_path()
    conn = sqlite3.connect(db_path_to_use)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force: bool = False) -> None:
    """Alembicマイグレーションを適用し、SQLiteスキーマを最新化する。"""
    _logger.info(
        "DB URL: %s | SCPLN_DB: %s",
        os.environ.get("DATABASE_URL"),
        os.environ.get("SCPLN_DB"),
    )

    global _initialized
    if _initialized and not force:
        return

    with _init_lock:
        if _initialized and not force:
            return

        ini_path = _BASE_DIR / "alembic.ini"
        script_location = _BASE_DIR / "alembic"

        if not ini_path.exists() or not script_location.exists():
            _logger.warning(
                "DB初期化をスキップします: alembic設定が見つかりません (ini=%s, script=%s)",
                ini_path,
                script_location,
            )
            _initialized = True
            return

        try:
            from alembic.config import Config
            from alembic import command
        except Exception as exc:  # pragma: no cover - alembic未導入の異常系
            _logger.error("alembicの読み込みに失敗しました: %s", exc)
            raise

        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(script_location))
        db_path_to_use = _db_path()
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path_to_use}")

        _logger.info("DBマイグレーションを適用します: %s", db_path_to_use)
        try:
            command.upgrade(cfg, "head")
        except Exception as exc:
            _logger.error("DBマイグレーションに失敗しました: %s", exc)
            raise
        else:
            _initialized = True
            _logger.info("DBマイグレーションが完了しました")


def create_job(
    job_id: str, jtype: str, status: str, submitted_at: int, params_json: str | None
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO jobs(job_id, type, status, submitted_at, params_json) VALUES(?,?,?,?,?)",
            (job_id, jtype, status, submitted_at, params_json),
        )


def update_job_status(
    job_id: str,
    *,
    status: str,
    started_at: int | None = None,
    finished_at: int | None = None,
    run_id: str | None = None,
    error: str | None = None,
    submitted_at: int | None = None,
) -> None:
    with _conn() as c:
        row = c.execute("SELECT job_id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return
        # Build dynamic update
        sets = ["status=?"]
        params: list = [status]
        if started_at is not None:
            sets.append("started_at=?")
            params.append(started_at)
        if finished_at is not None:
            sets.append("finished_at=?")
            params.append(finished_at)
        if run_id is not None:
            sets.append("run_id=?")
            params.append(run_id)
        if error is not None:
            sets.append("error=?")
            params.append(error)
        if submitted_at is not None:
            sets.append("submitted_at=?")
            params.append(submitted_at)
        params.append(job_id)
        c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id=?", tuple(params))


def update_job_params(job_id: str, params_json: str) -> None:
    with _conn() as c:
        c.execute("UPDATE jobs SET params_json=? WHERE job_id=?", (params_json, job_id))


def get_job(job_id: str) -> Dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(status: str | None, offset: int, limit: int) -> Dict[str, Any]:
    with _conn() as c:
        where = []
        params: list = []
        if status:
            where.append("status = ?")
            params.append(status)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        total = c.execute(
            f"SELECT COUNT(*) AS cnt FROM jobs{where_sql}", params
        ).fetchone()["cnt"]
        rows = c.execute(
            f"SELECT * FROM jobs{where_sql} ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return {
            "jobs": [dict(r) for r in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
        }


def set_job_result(job_id: str, result_json: str) -> None:
    with _conn() as c:
        c.execute("UPDATE jobs SET result_json=? WHERE job_id=?", (result_json, job_id))


def set_product_hierarchy(mapping: Dict[str, Dict[str, str]]) -> None:
    with _conn() as c:
        c.execute("DELETE FROM product_hierarchy")
        for k, v in (mapping or {}).items():
            c.execute(
                "INSERT INTO product_hierarchy(key, item, category, department) VALUES(?,?,?,?)",
                (k, v.get("item"), v.get("category"), v.get("department")),
            )


def get_product_hierarchy() -> Dict[str, Dict[str, str]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT key, item, category, department FROM product_hierarchy"
        ).fetchall()
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            out[r["key"]] = {
                "item": r["item"],
                "category": r["category"],
                "department": r["department"],
            }
        return out


def set_location_hierarchy(mapping: Dict[str, Dict[str, str]]) -> None:
    with _conn() as c:
        c.execute("DELETE FROM location_hierarchy")
        for k, v in (mapping or {}).items():
            c.execute(
                "INSERT INTO location_hierarchy(key, region, country) VALUES(?,?,?)",
                (k, v.get("region"), v.get("country")),
            )


def get_location_hierarchy() -> Dict[str, Dict[str, str]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT key, region, country FROM location_hierarchy"
        ).fetchall()
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            out[r["key"]] = {
                "region": r["region"],
                "country": r["country"],
            }
        return out


# --- Scenarios (phase2 foundation) ---
def list_scenarios(limit: int = 200) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, parent_id, tag, locked, updated_at, created_at FROM scenarios ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_scenario(sid: int) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT * FROM scenarios WHERE id=?", (sid,)).fetchone()
        return dict(row) if row else None


def create_scenario(
    name: str,
    parent_id: Optional[int],
    tag: Optional[str],
    description: Optional[str],
    locked: bool = False,
) -> int:
    now = int(time.time() * 1000)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO scenarios(name, parent_id, tag, description, locked, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (name, parent_id, tag, description, 1 if locked else 0, now, now),
        )
        return int(cur.lastrowid)


def update_scenario(sid: int, **fields: Any) -> None:
    if not fields:
        return
    allowed = {"name", "parent_id", "tag", "description", "locked"}
    keys = [k for k in fields.keys() if k in allowed]
    if not keys:
        return
    sets = []
    params: list[Any] = []
    for k in keys:
        sets.append(f"{k}=?")
        v = fields[k]
        if k == "locked":
            params.append(1 if bool(v) else 0)
        else:
            params.append(v)
    params.append(int(time.time() * 1000))
    params.append(sid)
    with _conn() as c:
        c.execute(
            f"UPDATE scenarios SET {', '.join(sets)}, updated_at=? WHERE id=?",
            tuple(params),
        )


def delete_scenario(sid: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM scenarios WHERE id=?", (sid,))


# --- Plans (v3) ---
def create_plan_version(
    version_id: str,
    *,
    base_scenario_id: int | None = None,
    status: str | None = "active",
    cutover_date: str | None = None,
    recon_window_days: int | None = None,
    objective: str | None = None,
    note: str | None = None,
    config_version_id: int | None = None,
    input_set_label: str | None = None,
) -> None:
    now = int(time.time() * 1000)
    with _conn() as c:
        c.execute(
            """
            INSERT OR REPLACE INTO plan_versions(
                version_id,
                created_at,
                base_scenario_id,
                status,
                cutover_date,
                recon_window_days,
                objective,
                note,
                config_version_id,
                input_set_label
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                version_id,
                now,
                base_scenario_id,
                status,
                cutover_date,
                recon_window_days,
                objective,
                note,
                config_version_id,
                input_set_label,
            ),
        )


def upsert_plan_artifact(version_id: str, name: str, json_text: str) -> None:
    now = int(time.time() * 1000)
    try:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO plan_artifacts(version_id, name, json_text, created_at) VALUES(?,?,?,?)",
                (version_id, name, json_text, now),
            )
    except Exception:
        try:
            PLAN_ARTIFACT_WRITE_ERROR_TOTAL.labels(artifact=name).inc()
        except Exception:
            pass
        raise


def get_plan_artifact(version_id: str, name: str) -> Dict[str, Any] | None:
    with _conn() as c:
        row = c.execute(
            "SELECT json_text FROM plan_artifacts WHERE version_id=? AND name=?",
            (version_id, name),
        ).fetchone()
        if not row:
            return None
        return json.loads(row["json_text"]) if row["json_text"] else None


def get_plan_version(version_id: str) -> Dict[str, Any] | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM plan_versions WHERE version_id=?", (version_id,)
        ).fetchone()
        return dict(row) if row else None


def list_plan_versions(
    limit: int = 100,
    offset: int = 0,
    order: str = "created_desc",
) -> List[Dict[str, Any]]:
    order_map = {
        "created_desc": "created_at DESC",
        "created_asc": "created_at ASC",
        "version_desc": "version_id DESC",
        "version_asc": "version_id ASC",
        "status": "status ASC, created_at DESC",
    }
    order_sql = order_map.get(order, order_map["created_desc"])

    with _conn() as c:
        rows = c.execute(
            f"""
            SELECT version_id, status, cutover_date, recon_window_days,
                   config_version_id, base_scenario_id, created_at, input_set_label
            FROM plan_versions
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_plan_versions() -> int:
    with _conn() as c:
        row = c.execute("SELECT COUNT(*) AS cnt FROM plan_versions").fetchone()
        return int(row["cnt"] if row else 0)


def list_plan_versions_by_base(
    base_scenario_id: int, limit: int = 5
) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT version_id, status, cutover_date, recon_window_days, config_version_id, created_at, input_set_label FROM plan_versions WHERE base_scenario_id=? ORDER BY created_at DESC LIMIT ?",
            (base_scenario_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def update_plan_version(version_id: str, **fields: Any) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "cutover_date",
        "recon_window_days",
        "objective",
        "note",
        "base_scenario_id",
        "config_version_id",
        "input_set_label",
    }
    keys = [k for k in fields.keys() if k in allowed]
    if not keys:
        return
    sets = []
    params: list[Any] = []
    for k in keys:
        sets.append(f"{k}=?")
        params.append(fields[k])
    params.append(version_id)
    with _conn() as c:
        c.execute(
            f"UPDATE plan_versions SET {', '.join(sets)} WHERE version_id=?",
            tuple(params),
        )


def delete_plan_artifacts(version_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))


def delete_plan_version(version_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM plan_versions WHERE version_id=?", (version_id,))


def clear_plan_version_from_runs(version_id: str) -> None:
    with _conn() as c:
        rows = c.execute(
            "SELECT run_id, summary FROM runs WHERE plan_version_id=?", (version_id,)
        ).fetchall()
        for row in rows:
            run_id = row["run_id"]
            summary_text = row["summary"]
            updated_summary = summary_text
            if summary_text:
                try:
                    summary_obj = json.loads(summary_text)
                except Exception:
                    summary_obj = None
                if (
                    isinstance(summary_obj, dict)
                    and summary_obj.get("_plan_version_id") == version_id
                ):
                    summary_obj.pop("_plan_version_id", None)
                    updated_summary = json.dumps(summary_obj, ensure_ascii=False)
            c.execute(
                "UPDATE runs SET summary=?, plan_version_id=NULL WHERE run_id=?",
                (updated_summary, run_id),
            )


# --- Run meta (approve/baseline/archive) ---
def get_run_meta(run_id: str) -> Dict[str, Any]:
    with _conn() as c:
        row = c.execute("SELECT * FROM runs_meta WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else {"run_id": run_id, "baseline": 0, "archived": 0}


def upsert_run_meta(run_id: str, **fields: Any) -> None:
    # ensure row exists
    with _conn() as c:
        int(time.time() * 1000)
        row = c.execute(
            "SELECT run_id FROM runs_meta WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            c.execute(
                "INSERT INTO runs_meta(run_id, approved_at, approved_by, baseline, archived, note) VALUES(?,?,?,?,?,?)",
                (run_id, None, None, 0, 0, None),
            )
        # build update
        allowed = {"approved_at", "approved_by", "baseline", "archived", "note"}
        keys = [k for k in fields.keys() if k in allowed]
        if not keys:
            return
        sets = []
        params: list[Any] = []
        for k in keys:
            sets.append(f"{k}=?")
            params.append(fields[k])
        params.append(run_id)
        c.execute(
            f"UPDATE runs_meta SET {', '.join(sets)} WHERE run_id=?", tuple(params)
        )


def approve_run(run_id: str, approved_by: str | None = None) -> None:
    upsert_run_meta(
        run_id, approved_at=int(time.time() * 1000), approved_by=approved_by
    )


def set_archived(run_id: str, archived: bool) -> None:
    upsert_run_meta(run_id, archived=1 if archived else 0)


def set_baseline(run_id: str) -> None:
    # 同一シナリオ内で単一ベースラインにする（DBで解決）
    with _conn() as c:
        row = c.execute(
            "SELECT scenario_id FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            return
        sid = row["scenario_id"]
        if sid is not None:
            # 同一シナリオの既存ベースラインを解除
            q = c.execute(
                "SELECT run_id FROM runs WHERE scenario_id=?", (sid,)
            ).fetchall()
            for r in q:
                c.execute(
                    "INSERT OR IGNORE INTO runs_meta(run_id, baseline, archived) VALUES(?,0,0)",
                    (r["run_id"],),
                )
                c.execute(
                    "UPDATE runs_meta SET baseline=0 WHERE run_id=?", (r["run_id"],)
                )
        # 対象をベースライン化
        c.execute(
            "INSERT OR IGNORE INTO runs_meta(run_id, baseline, archived) VALUES(?,0,0)",
            (run_id,),
        )
        c.execute("UPDATE runs_meta SET baseline=1 WHERE run_id=?", (run_id,))


def get_runs_meta_bulk(run_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not run_ids:
        return {}
    with _conn() as c:
        ph = ",".join(["?"] * len(run_ids))
        rows = c.execute(
            f"SELECT * FROM runs_meta WHERE run_id IN ({ph})", tuple(run_ids)
        ).fetchall()
        out = {}
        for r in rows:
            out[r["run_id"]] = dict(r)
        # ensure all keys present
        for rid in run_ids:
            if rid not in out:
                out[rid] = {"run_id": rid, "baseline": 0, "archived": 0}
        return out


# --- Run views (server-side saved views) ---
def list_run_views(
    owner: str | None = None, *, org: str | None = None
) -> List[Dict[str, Any]]:
    with _conn() as c:
        # 可視性: 自分のもの、public、同一orgかつscope=org
        cond = ["(owner = ?)"] if owner else ["0"]
        params: list[Any] = [owner] if owner else []
        cond.append("scope = 'public'")
        if org:
            cond.append(
                "(scope = 'org' AND owner IN (SELECT owner FROM run_views WHERE 1=1))"
            )
            # 簡易実装: org毎の所有者紐付けは外部ディレクトリが無い前提のため省略
            # 組織単位共有はUI/運用の約束で運用（将来ユーザテーブル導入時に厳格化）
        where_sql = " WHERE (" + " OR ".join(cond) + ")"
        rows = c.execute(
            f"SELECT id, name, owner, filters, shared, scope, created_at, updated_at FROM run_views{where_sql} ORDER BY updated_at DESC, id DESC",
            tuple(params),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "owner": r["owner"],
                    "filters": json.loads(r["filters"] or "{}"),
                    "shared": bool(r["shared"]),
                    "scope": r["scope"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
            )
        return out


def create_run_view(
    name: str,
    filters: Dict[str, Any],
    owner: str | None,
    shared: bool,
    scope: str = "private",
) -> int:
    now = int(time.time() * 1000)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO run_views(name, owner, filters, shared, scope, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (
                name,
                owner,
                json.dumps(filters, ensure_ascii=False),
                1 if shared else 0,
                scope,
                now,
                now,
            ),
        )
        return int(cur.lastrowid)


def get_run_view(view_id: int) -> Dict[str, Any] | None:
    with _conn() as c:
        r = c.execute(
            "SELECT id, name, owner, filters, shared, scope, created_at, updated_at FROM run_views WHERE id=?",
            (view_id,),
        ).fetchone()
        if not r:
            return None
        return {
            "id": r["id"],
            "name": r["name"],
            "owner": r["owner"],
            "filters": json.loads(r["filters"] or "{}"),
            "shared": bool(r["shared"]),
            "scope": r["scope"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }


def update_run_view(view_id: int, **fields: Any) -> None:
    allowed = {"name", "filters", "shared", "scope"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    sets = []
    params: list[Any] = []
    for k in keys:
        v = fields[k]
        if k == "filters":
            v = json.dumps(v, ensure_ascii=False)
        if k == "shared":
            v = 1 if bool(v) else 0
        sets.append(f"{k}=?")
        params.append(v)
    params.append(int(time.time() * 1000))
    params.append(view_id)
    with _conn() as c:
        c.execute(
            f"UPDATE run_views SET {', '.join(sets)}, updated_at=? WHERE id=?",
            tuple(params),
        )


def delete_run_view(view_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM run_views WHERE id=?", (view_id,))


# --- Baseline lookup ---
def get_baseline_run_id(scenario_id: int) -> str | None:
    with _conn() as c:
        row = c.execute(
            """
            SELECT r.run_id FROM runs r
            JOIN runs_meta m ON r.run_id = m.run_id
            WHERE r.scenario_id = ? AND m.baseline = 1
            ORDER BY r.started_at DESC, r.run_id DESC
            LIMIT 1
            """,
            (scenario_id,),
        ).fetchone()
        return row["run_id"] if row else None
