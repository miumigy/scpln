import csv
import os
import runpy
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from app import db
from core.plan_repository import PlanRepository

pytestmark = pytest.mark.slow


def _write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


@contextmanager
def _override_environ(env: dict[str, str]):
    original = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(env)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _run_cli(module: str, args: list[str], env: dict[str, str]) -> None:
    with _override_environ(env):
        argv_backup = sys.argv[:]
        sys.argv = [module, *args]
        try:
            runpy.run_module(module, run_name="__main__")
        except SystemExit as exc:  # pragma: no cover - CLIがexitする場合
            if exc.code not in (0, None):
                raise
        finally:
            sys.argv = argv_backup


@pytest.fixture
def tiny_planning_dir(tmp_path) -> Path:
    base = tmp_path / "tiny_planning"
    base.mkdir()

    _write_csv(
        base / "demand_family.csv",
        ["family", "period", "demand"],
        [
            ["F1", "2025-01", 40],
            ["F1", "2025-02", 45],
            ["F2", "2025-01", 20],
        ],
    )
    _write_csv(
        base / "capacity.csv",
        ["workcenter", "period", "capacity"],
        [
            ["WC1", "2025-01", 80],
            ["WC1", "2025-02", 60],
        ],
    )
    _write_csv(
        base / "mix_share.csv",
        ["family", "sku", "share"],
        [
            ["F1", "SKU1", 0.6],
            ["F1", "SKU2", 0.4],
            ["F2", "SKU3", 1.0],
        ],
    )
    _write_csv(
        base / "item.csv",
        ["item", "lt", "lot", "moq"],
        [
            ["SKU1", 1, 1, 0],
            ["SKU2", 1, 1, 0],
            ["SKU3", 2, 1, 0],
        ],
    )
    _write_csv(
        base / "inventory.csv",
        ["item", "qty"],
        [
            ["SKU1", 10],
            ["SKU2", 5],
            ["SKU3", 2],
        ],
    )
    _write_csv(
        base / "open_po.csv",
        ["item", "due", "qty"],
        [
            ["SKU1", "2025-01-15", 5],
            ["SKU3", "2025-01", 3],
        ],
    )
    _write_csv(
        base / "bom.csv",
        ["parent", "child", "qty"],
        [
            ["SKU1", "COMP1", 1],
            ["SKU2", "COMP2", 1],
        ],
    )

    return base


def test_plan_aggregate_storage_db_only(db_setup, tmp_path, tiny_planning_dir):
    output = tmp_path / "aggregate.json"
    version_id = "agg-cli-db"
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"  # ensure env doesn't force db

    _run_cli(
        "scripts.plan_aggregate",
        [
            "-i",
            str(tiny_planning_dir),
            "-o",
            str(output),
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        env,
    )

    # fileは生成されない
    assert not output.exists()

    repo = PlanRepository(db._conn)
    rows = repo.fetch_plan_series(version_id, "aggregate")
    assert rows

    # cleanup
    with db._conn() as conn:
        conn.execute("DELETE FROM plan_series WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_kpis WHERE version_id=?", (version_id,))
        conn.execute(
            "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
        )
        conn.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_jobs WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
        conn.commit()


def test_plan_aggregate_storage_files_only(db_setup, tmp_path, tiny_planning_dir):
    output = tmp_path / "aggregate.json"
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    _run_cli(
        "scripts.plan_aggregate",
        [
            "-i",
            str(tiny_planning_dir),
            "-o",
            str(output),
        ],
        env,
    )

    assert output.exists()

    # cleanup JSON only
    output.unlink()


def test_allocate_storage_db_with_aggregate_merge(
    db_setup, tmp_path, tiny_planning_dir
):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    _run_cli(
        "scripts.plan_aggregate",
        [
            "-i",
            str(tiny_planning_dir),
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        env,
    )

    assert agg_output.exists()

    version_id = "alloc-cli-db"
    detail_output = tmp_path / "sku_week.json"
    _run_cli(
        "scripts.allocate",
        [
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            str(tiny_planning_dir),
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        env,
    )

    # storage=db のためファイルは生成されない
    assert not detail_output.exists()

    repo = PlanRepository(db._conn)
    agg_rows = repo.fetch_plan_series(version_id, "aggregate")
    det_rows = repo.fetch_plan_series(version_id, "det")
    kpi_rows = repo.fetch_plan_kpis(version_id)
    assert agg_rows
    assert det_rows
    assert kpi_rows

    # cleanup
    with db._conn() as conn:
        conn.execute("DELETE FROM plan_series WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_kpis WHERE version_id=?", (version_id,))
        conn.execute(
            "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
        )
        conn.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_jobs WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
        conn.commit()

    agg_output.unlink()


def test_mrp_storage_db_append(db_setup, tmp_path, tiny_planning_dir):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    _run_cli(
        "scripts.plan_aggregate",
        [
            "-i",
            str(tiny_planning_dir),
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        env,
    )

    version_id = "mrp-cli-db"
    detail_output = tmp_path / "sku_week.json"
    _run_cli(
        "scripts.allocate",
        [
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            str(tiny_planning_dir),
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        env,
    )

    assert detail_output.exists()

    mrp_output = tmp_path / "mrp.json"
    _run_cli(
        "scripts.mrp",
        [
            "-i",
            str(detail_output),
            "-I",
            str(tiny_planning_dir),
            "-o",
            str(mrp_output),
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        env,
    )

    assert not mrp_output.exists()

    repo = PlanRepository(db._conn)
    agg_rows = repo.fetch_plan_series(version_id, "aggregate")
    det_rows = repo.fetch_plan_series(version_id, "det")
    mrp_rows = repo.fetch_plan_series(version_id, "mrp")
    assert agg_rows
    assert det_rows
    assert mrp_rows

    with db._conn() as conn:
        conn.execute("DELETE FROM plan_series WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_kpis WHERE version_id=?", (version_id,))
        conn.execute(
            "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
        )
        conn.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_jobs WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
        conn.commit()

    agg_output.unlink()
    detail_output.unlink()


def test_anchor_adjust_storage_db(db_setup, tmp_path, tiny_planning_dir):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    _run_cli(
        "scripts.plan_aggregate",
        [
            "-i",
            str(tiny_planning_dir),
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        env,
    )

    version_id = "anchor-cli-db"
    detail_output = tmp_path / "sku_week.json"
    _run_cli(
        "scripts.allocate",
        [
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            str(tiny_planning_dir),
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        env,
    )

    adjust_output = tmp_path / "sku_week_adjusted.json"
    _run_cli(
        "scripts.anchor_adjust",
        [
            "-i",
            str(agg_output),
            str(detail_output),
            "-o",
            str(adjust_output),
            "--cutover-date",
            "2025-09-01",
            "--anchor-policy",
            "DET_near",
            "--weeks",
            "4",
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        env,
    )

    assert not adjust_output.exists()

    repo = PlanRepository(db._conn)
    adjusted_rows = repo.fetch_plan_series(version_id, "det_adjusted")
    assert adjusted_rows

    with db._conn() as conn:
        conn.execute("DELETE FROM plan_series WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_kpis WHERE version_id=?", (version_id,))
        conn.execute(
            "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
        )
        conn.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_jobs WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
        conn.commit()

    agg_output.unlink()
    detail_output.unlink()


def test_reconcile_storage_db(db_setup, tmp_path, tiny_planning_dir):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    _run_cli(
        "scripts.plan_aggregate",
        [
            "-i",
            str(tiny_planning_dir),
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        env,
    )

    assert agg_output.exists()

    version_id = "reconcile-cli-db"
    detail_output = tmp_path / "sku_week.json"
    _run_cli(
        "scripts.allocate",
        [
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            str(tiny_planning_dir),
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        env,
    )

    mrp_output = tmp_path / "mrp.json"
    _run_cli(
        "scripts.mrp",
        [
            "-i",
            str(detail_output),
            "-I",
            str(tiny_planning_dir),
            "-o",
            str(mrp_output),
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        env,
    )

    plan_output = tmp_path / "plan_final.json"
    _run_cli(
        "scripts.reconcile",
        [
            "-i",
            str(detail_output),
            str(mrp_output),
            "-I",
            str(tiny_planning_dir),
            "-o",
            str(plan_output),
            "--weeks",
            "4",
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        env,
    )

    assert not plan_output.exists()

    repo = PlanRepository(db._conn)
    final_rows = repo.fetch_plan_series(version_id, "mrp_final")
    weekly_rows = repo.fetch_plan_series(version_id, "weekly_summary")
    assert final_rows
    assert weekly_rows

    log_output = tmp_path / "reconciliation_log.json"
    _run_cli(
        "scripts.reconcile_levels",
        [
            "-i",
            str(agg_output),
            str(detail_output),
            "-o",
            str(log_output),
            "--version",
            "pytest",
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        env,
    )

    log_artifact = db.get_plan_artifact(version_id, log_output.name)
    assert log_artifact
    assert log_artifact.get("schema_version") == "recon-aggdet-1.0"

    csv_output = tmp_path / "reconciliation_before.csv"
    _run_cli(
        "scripts.export_reconcile_csv",
        [
            "-i",
            str(log_output),
            "-o",
            str(csv_output),
            "--label",
            "before",
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        env,
    )

    csv_artifact = db.get_plan_artifact(version_id, csv_output.name)
    assert csv_artifact
    assert csv_artifact.get("type") == "csv"
    assert "label,family,period" in csv_artifact["content"]

    with db._conn() as conn:
        conn.execute("DELETE FROM plan_series WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_kpis WHERE version_id=?", (version_id,))
        conn.execute(
            "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
        )
        conn.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_jobs WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
        conn.commit()

    agg_output.unlink()
    detail_output.unlink()
    mrp_output.unlink()
    if log_output.exists():
        log_output.unlink()


def test_report_storage_db(db_setup, tmp_path, tiny_planning_dir):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    _run_cli(
        "scripts.plan_aggregate",
        [
            "-i",
            str(tiny_planning_dir),
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        env,
    )

    version_id = "report-cli-db"
    detail_output = tmp_path / "sku_week.json"
    _run_cli(
        "scripts.allocate",
        [
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            str(tiny_planning_dir),
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        env,
    )

    mrp_output = tmp_path / "mrp.json"
    _run_cli(
        "scripts.mrp",
        [
            "-i",
            str(detail_output),
            "-I",
            str(tiny_planning_dir),
            "-o",
            str(mrp_output),
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        env,
    )

    plan_output = tmp_path / "plan_final.json"
    _run_cli(
        "scripts.reconcile",
        [
            "-i",
            str(detail_output),
            str(mrp_output),
            "-I",
            str(tiny_planning_dir),
            "-o",
            str(plan_output),
            "--weeks",
            "4",
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        env,
    )

    report_output = tmp_path / "report.csv"
    _run_cli(
        "scripts.report",
        [
            "-i",
            str(plan_output),
            "-I",
            str(tiny_planning_dir),
            "-o",
            str(report_output),
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        env,
    )

    assert not report_output.exists()

    artifact = db.get_plan_artifact(version_id, report_output.name)
    assert artifact
    assert artifact.get("type") == "csv"
    assert "content" in artifact and "type,week" in artifact["content"]

    with db._conn() as conn:
        conn.execute("DELETE FROM plan_series WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_kpis WHERE version_id=?", (version_id,))
        conn.execute(
            "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
        )
        conn.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_jobs WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
        conn.commit()

    agg_output.unlink()
    detail_output.unlink()
    mrp_output.unlink()
    plan_output.unlink()
