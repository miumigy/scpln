import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app import db
from core.plan_repository import PlanRepository


def _insert_plan_fixture(
    db_path: str, version_id: str, *, config_version_id: int | None = 100
) -> None:
    now = 1700000000000
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO plan_versions(
                version_id, created_at, base_scenario_id, status, cutover_date,
                recon_window_days, objective, note, config_version_id
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                version_id,
                now,
                None,
                "active",
                None,
                None,
                None,
                None,
                config_version_id,
            ),
        )

        artifacts: dict[str, dict] = {
            "aggregate.json": {
                "schema_version": "agg-1.0",
                "note": "unit-test",
                "inputs_summary": {},
                "rows": [
                    {
                        "family": "F1",
                        "period": "2025-01",
                        "demand": 100.0,
                        "supply": 90.0,
                        "backlog": 10.0,
                        "capacity_total": 120.0,
                    }
                ],
            },
            "sku_week.json": {
                "schema_version": "det-1.0",
                "note": "unit-test",
                "inputs_summary": {},
                "rows": [
                    {
                        "family": "F1",
                        "period": "2025-01",
                        "sku": "SKU1",
                        "week": "2025-01-W1",
                        "demand": 30.0,
                        "supply": 25.0,
                        "backlog": 5.0,
                    }
                ],
            },
            "mrp.json": {
                "schema_version": "mrp-1.0",
                "note": "unit-test",
                "inputs_summary": {},
                "rows": [
                    {
                        "item": "COMP1",
                        "week": "2025-01-W1",
                        "gross_req": 40.0,
                        "scheduled_receipts": 5.0,
                        "on_hand_start": 0.0,
                        "net_req": 10.0,
                        "planned_order_receipt": 10.0,
                        "planned_order_release": 10.0,
                        "lt_weeks": 2,
                        "lot": 1.0,
                        "moq": 0.0,
                    }
                ],
            },
            "plan_final.json": {
                "schema_version": "recon-1.0",
                "note": "unit-test",
                "inputs_summary": {},
                "rows": [
                    {
                        "item": "COMP1",
                        "week": "2025-01-W1",
                        "gross_req": 40.0,
                        "scheduled_receipts": 5.0,
                        "on_hand_start": 0.0,
                        "net_req": 10.0,
                        "planned_order_receipt": 10.0,
                        "planned_order_release": 10.0,
                        "planned_order_receipt_adj": 12.0,
                        "planned_order_release_adj": 12.0,
                        "lt_weeks": 2,
                        "lot": 1.0,
                        "moq": 0.0,
                    }
                ],
                "weekly_summary": [
                    {
                        "week": "2025-01-W1",
                        "capacity": 120.0,
                        "original_load": 80.0,
                        "adjusted_load": 90.0,
                        "carried_slack_in": 5.0,
                        "spill_in": 2.0,
                        "spill_out": 1.0,
                        "slack_carry_out": 3.0,
                    }
                ],
            },
            "source.json": {
                "source_run_id": "backfill-run",
            },
        }

        for name, payload in artifacts.items():
            conn.execute(
                "INSERT INTO plan_artifacts(version_id, name, json_text, created_at) VALUES(?,?,?,?)",
                (version_id, name, json.dumps(payload, ensure_ascii=False), now),
            )

        conn.commit()
    finally:
        conn.close()


def _run_script(
    db_path: str, *args: str, state_file: Path | None = None
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "scripts/plan_backfill_repository.py", *args]
    env = os.environ.copy()
    env["SCPLN_DB"] = db_path
    env.setdefault("PYTHONPATH", ".")
    result = subprocess.run(
        cmd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("STDOUT:\n" + result.stdout)
        print("STDERR:\n" + result.stderr)
    return result


def test_backfill_writes_plan_repository(db_setup, seed_canonical_data, tmp_path):
    version_id = "v-backfill"
    _insert_plan_fixture(db_setup, version_id)
    state_file = tmp_path / "state.json"

    result = _run_script(db_setup, "--state-file", str(state_file))
    assert result.returncode == 0

    repo = PlanRepository(db._conn)
    agg_rows = repo.fetch_plan_series(version_id, "aggregate")
    assert agg_rows, "aggregate rows should be backfilled"
    assert agg_rows[0]["config_version_id"] == 100
    assert agg_rows[0]["source_run_id"] == "backfill-run"

    kpi_rows = repo.fetch_plan_kpis(version_id)
    assert any(row.get("metric") == "fill_rate" for row in kpi_rows)

    state_payload = json.loads(state_file.read_text())
    assert version_id in state_payload.get("completed_versions", [])
    assert version_id not in state_payload.get("failed_versions", {})

    with sqlite3.connect(db_setup) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, processed, skipped, errors, dry_run FROM plan_backfill_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["status"] == "success"
        assert row["processed"] >= 1
        assert row["dry_run"] == 0
        assert row["errors"] == 0


def test_backfill_dry_run_does_not_write(db_setup, seed_canonical_data):
    version_id = "v-backfill-dry"
    _insert_plan_fixture(db_setup, version_id)

    result = _run_script(db_setup, "--dry-run")
    assert result.returncode == 0

    repo = PlanRepository(db._conn)
    agg_rows = repo.fetch_plan_series(version_id, "aggregate")
    assert not agg_rows, "dry-run must not persist data"

    with sqlite3.connect(db_setup) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, processed, skipped, errors, dry_run FROM plan_backfill_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["status"] == "success"
        assert row["dry_run"] == 1
        assert row["processed"] == 0


def test_backfill_state_file_skip(db_setup, seed_canonical_data, tmp_path):
    version_id = "v-backfill-skip"
    _insert_plan_fixture(db_setup, version_id)
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {"completed_versions": [version_id], "failed_versions": {}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = _run_script(db_setup, "--state-file", str(state_file))
    assert result.returncode == 0
    assert "state fileで既に完了扱い" in result.stdout

    repo = PlanRepository(db._conn)
    agg_rows = repo.fetch_plan_series(version_id, "aggregate")
    assert not agg_rows, "state skip should prevent writes when force未指定"
