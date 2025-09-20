from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run_recon(tmp: Path, agg_rows, det_rows, cutover: str | None = None):
    base = Path.cwd()
    (tmp / "aggregate.json").write_text(
        json.dumps({"rows": agg_rows}), encoding="utf-8"
    )
    (tmp / "det.json").write_text(json.dumps({"rows": det_rows}), encoding="utf-8")
    env = {"PYTHONPATH": str(base)}
    outp = tmp / "recon.json"
    cmd = [
        "python3",
        "scripts/reconcile_levels.py",
        "-i",
        str(tmp / "aggregate.json"),
        str(tmp / "det.json"),
        "-o",
        str(outp),
        "--version",
        "t",
    ]
    if cutover:
        cmd += ["--cutover-date", cutover]
    subprocess.run(cmd, check=True, cwd=str(base), env=env)
    return json.loads(outp.read_text(encoding="utf-8"))


def test_supply_plan_fallback_month(tmp_path: Path):
    # AGGはYYYY-MM、DETはsupply_planのみを持つケース
    # 週は月内に完全に含まれる週（W03/W04）を使用し、年跨ぎの影響を排除
    agg_rows = [
        {
            "family": "F",
            "period": "2025-01",
            "demand": 10.0,
            "supply": 20.0,
            "backlog": 0.0,
        }
    ]
    det_rows = [
        {
            "family": "F",
            "week": "2025-W03",
            "demand": 5.0,
            "supply_plan": 7.0,
            "backlog": 0.0,
        },
        {
            "family": "F",
            "week": "2025-W04",
            "demand": 5.0,
            "supply_plan": 13.0,
            "backlog": 0.0,
        },
    ]
    out = _run_recon(tmp_path, agg_rows, det_rows)
    # tol違反が0（DET供給=20が集計されAGGと一致）
    assert out.get("summary", {}).get("tol_violations", 1) == 0


def test_period_iso_week_match(tmp_path: Path):
    # AGGはYYYY-Www、DETはperiod=YYYY-Www を持ち、demand/supply/backlog が一致
    agg_rows = [
        {
            "family": "G",
            "period": "2025-W03",
            "demand": 1.0,
            "supply": 2.0,
            "backlog": 3.0,
        }
    ]
    det_rows = [
        {
            "family": "G",
            "period": "2025-W03",
            "week": "2025-W03",
            "demand": 1.0,
            "supply": 2.0,
            "backlog": 3.0,
        }
    ]
    out = _run_recon(tmp_path, agg_rows, det_rows, cutover="2025-01-15")
    assert out.get("summary", {}).get("tol_violations", 1) == 0
    # 境界タグも機能（cutoverに対応するISO週）
    assert any(
        (r.get("period") == "2025-W03") and r.get("boundary_period")
        for r in out.get("deltas", [])
    )