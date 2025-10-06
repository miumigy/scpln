import os
import subprocess
import sys

from app import db
from core.plan_repository import PlanRepository


def test_plan_aggregate_storage_db_only(db_setup, tmp_path):
    output = tmp_path / "aggregate.json"
    version_id = "agg-cli-db"
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"  # ensure env doesn't force db

    cmd = [
        sys.executable,
        "scripts/plan_aggregate.py",
        "-i",
        "samples/planning",
        "-o",
        str(output),
        "--storage",
        "db",
        "--version-id",
        version_id,
    ]
    subprocess.run(cmd, check=True, env=env)

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


def test_plan_aggregate_storage_files_only(db_setup, tmp_path):
    output = tmp_path / "aggregate.json"
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    cmd = [
        sys.executable,
        "scripts/plan_aggregate.py",
        "-i",
        "samples/planning",
        "-o",
        str(output),
    ]
    subprocess.run(cmd, check=True, env=env)

    assert output.exists()

    # cleanup JSON only
    output.unlink()


def test_allocate_storage_db_with_aggregate_merge(db_setup, tmp_path):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/plan_aggregate.py",
            "-i",
            "samples/planning",
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        check=True,
        env=env,
    )

    assert agg_output.exists()

    version_id = "alloc-cli-db"
    detail_output = tmp_path / "sku_week.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/allocate.py",
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            "samples/planning",
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
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


def test_mrp_storage_db_append(db_setup, tmp_path):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/plan_aggregate.py",
            "-i",
            "samples/planning",
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        check=True,
        env=env,
    )

    version_id = "mrp-cli-db"
    detail_output = tmp_path / "sku_week.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/allocate.py",
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            "samples/planning",
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
    )

    assert detail_output.exists()

    mrp_output = tmp_path / "mrp.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/mrp.py",
            "-i",
            str(detail_output),
            "-I",
            "samples/planning",
            "-o",
            str(mrp_output),
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
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


def test_anchor_adjust_storage_db(db_setup, tmp_path):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/plan_aggregate.py",
            "-i",
            "samples/planning",
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        check=True,
        env=env,
    )

    version_id = "anchor-cli-db"
    detail_output = tmp_path / "sku_week.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/allocate.py",
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            "samples/planning",
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
    )

    adjust_output = tmp_path / "sku_week_adjusted.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/anchor_adjust.py",
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
        check=True,
        env=env,
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


def test_reconcile_storage_db(db_setup, tmp_path):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/plan_aggregate.py",
            "-i",
            "samples/planning",
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        check=True,
        env=env,
    )

    assert agg_output.exists()

    version_id = "reconcile-cli-db"
    detail_output = tmp_path / "sku_week.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/allocate.py",
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            "samples/planning",
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
    )

    mrp_output = tmp_path / "mrp.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/mrp.py",
            "-i",
            str(detail_output),
            "-I",
            "samples/planning",
            "-o",
            str(mrp_output),
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
    )

    plan_output = tmp_path / "plan_final.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/reconcile.py",
            "-i",
            str(detail_output),
            str(mrp_output),
            "-I",
            "samples/planning",
            "-o",
            str(plan_output),
            "--weeks",
            "4",
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
    )

    assert not plan_output.exists()

    repo = PlanRepository(db._conn)
    final_rows = repo.fetch_plan_series(version_id, "mrp_final")
    weekly_rows = repo.fetch_plan_series(version_id, "weekly_summary")
    assert final_rows
    assert weekly_rows

    log_output = tmp_path / "reconciliation_log.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/reconcile_levels.py",
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
        check=True,
        env=env,
    )

    log_artifact = db.get_plan_artifact(version_id, log_output.name)
    assert log_artifact
    assert log_artifact.get("schema_version") == "recon-aggdet-1.0"

    csv_output = tmp_path / "reconciliation_before.csv"
    subprocess.run(
        [
            sys.executable,
            "scripts/export_reconcile_csv.py",
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
        check=True,
        env=env,
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


def test_report_storage_db(db_setup, tmp_path):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    env["SCPLN_DB"] = db_setup
    env["PLAN_STORAGE_MODE"] = "files"

    agg_output = tmp_path / "aggregate.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/plan_aggregate.py",
            "-i",
            "samples/planning",
            "-o",
            str(agg_output),
            "--storage",
            "files",
        ],
        check=True,
        env=env,
    )

    version_id = "report-cli-db"
    detail_output = tmp_path / "sku_week.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/allocate.py",
            "-i",
            str(agg_output),
            "-o",
            str(detail_output),
            "-I",
            "samples/planning",
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
    )

    mrp_output = tmp_path / "mrp.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/mrp.py",
            "-i",
            str(detail_output),
            "-I",
            "samples/planning",
            "-o",
            str(mrp_output),
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
    )

    plan_output = tmp_path / "plan_final.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/reconcile.py",
            "-i",
            str(detail_output),
            str(mrp_output),
            "-I",
            "samples/planning",
            "-o",
            str(plan_output),
            "--weeks",
            "4",
            "--storage",
            "both",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
    )

    report_output = tmp_path / "report.csv"
    subprocess.run(
        [
            sys.executable,
            "scripts/report.py",
            "-i",
            str(plan_output),
            "-I",
            "samples/planning",
            "-o",
            str(report_output),
            "--storage",
            "db",
            "--version-id",
            version_id,
        ],
        check=True,
        env=env,
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
