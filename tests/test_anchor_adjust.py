from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def _write_json(p: Path, payload: dict) -> None:
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_anchor_adjust_reduces_boundary_delta(tmp_path: Path):
    base = Path.cwd()
    # Prepare aggregate (family F1, period 2025-01)
    agg = {
        "schema_version": "agg-1.0",
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "demand": 100.0,
                "supply": 90.0,
                "backlog": 10.0,
            }
        ],
    }
    det_rows = []
    for i in range(1, 5):
        det_rows.append(
            {
                "family": "F1",
                "period": "2025-01",
                "week": f"2025-01-Wk{i}",
                "demand": 25.0,
                "supply": 20.0,  # total 80 (short of 90)
                "backlog": 5.0,  # total 20 (over 10)
            }
        )
    det = {"schema_version": "agg-1.0", "rows": det_rows}

    out_dir = tmp_path
    _write_json(out_dir / "aggregate.json", agg)
    _write_json(out_dir / "sku_week.json", det)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(base)
    env.setdefault("PLAN_STORAGE_MODE", "files")
    # before: compute reconciliation
    subprocess.run(
        [
            sys.executable,
            "scripts/reconcile_levels.py",
            "-i",
            str(out_dir / "aggregate.json"),
            str(out_dir / "sku_week.json"),
            "-o",
            str(out_dir / "recon_before.json"),
            "--version",
            "t",
            "--cutover-date",
            "2025-01-15",
        ],
        check=True,
        cwd=str(base),
        env=env,
    )
    before = json.loads((out_dir / "recon_before.json").read_text(encoding="utf-8"))
    assert before["summary"]["boundary"]["violations"] >= 1

    # adjust
    subprocess.run(
        [
            sys.executable,
            "scripts/anchor_adjust.py",
            "-i",
            str(out_dir / "aggregate.json"),
            str(out_dir / "sku_week.json"),
            "-o",
            str(out_dir / "sku_week_adjusted.json"),
            "--cutover-date",
            "2025-01-15",
            "--anchor-policy",
            "DET_near",
        ],
        check=True,
        cwd=str(base),
        env=env,
    )
    # after: compute reconciliation on adjusted
    subprocess.run(
        [
            sys.executable,
            "scripts/reconcile_levels.py",
            "-i",
            str(out_dir / "aggregate.json"),
            str(out_dir / "sku_week_adjusted.json"),
            "-o",
            str(out_dir / "recon_after.json"),
            "--version",
            "t2",
            "--cutover-date",
            "2025-01-15",
        ],
        check=True,
        cwd=str(base),
        env=env,
    )
    after = json.loads((out_dir / "recon_after.json").read_text(encoding="utf-8"))
    # Expect boundary violations reduced (ideally to 0)
    assert (
        after["summary"]["boundary"]["violations"]
        <= before["summary"]["boundary"]["violations"]
    )

    # and deltas for supply/backlog closer to 0
    # find row for (F1, 2025-01)
    def _row(d):
        for r in d.get("deltas", []):
            if r.get("family") == "F1" and r.get("period") == "2025-01":
                return r
        return None

    rb = _row(before)
    ra = _row(after)
    assert rb and ra
    assert abs(float(ra.get("delta_supply", 0))) <= abs(
        float(rb.get("delta_supply", 0))
    )
    assert abs(float(ra.get("delta_backlog", 0))) <= abs(
        float(rb.get("delta_backlog", 0))
    )
