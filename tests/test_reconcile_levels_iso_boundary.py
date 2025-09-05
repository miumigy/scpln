from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_iso_boundary_marking(tmp_path: Path):
    base = Path.cwd()
    # cutover: 2025-01-15 (ISO week likely W03)
    agg = {"rows": [{"family": "F", "period": "2025-W03", "demand": 0.0, "supply": 0.0, "backlog": 0.0}]}
    det = {"rows": [{"family": "F", "period": "2025-W03", "week": "2025-W03", "demand": 10.0, "supply": 10.0, "backlog": 0.0}]}
    (tmp_path / "aggregate.json").write_text(json.dumps(agg), encoding="utf-8")
    (tmp_path / "det.json").write_text(json.dumps(det), encoding="utf-8")
    env = {"PYTHONPATH": str(base)}
    outp = tmp_path / "recon.json"
    subprocess.run([
        "python3", "scripts/reconcile_levels.py", "-i", str(tmp_path / "aggregate.json"), str(tmp_path / "det.json"),
        "-o", str(outp), "--version", "t", "--cutover-date", "2025-01-15"
    ], check=True, cwd=str(base), env=env)
    out = json.loads(outp.read_text(encoding="utf-8"))
    # boundary_period should be true for the iso period
    assert any(r.get("period") == "2025-W03" and r.get("boundary_period") for r in out.get("deltas", []))

