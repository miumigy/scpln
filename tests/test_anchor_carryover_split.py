from __future__ import annotations

import json
import subprocess
from pathlib import Path


def wj(p: Path, o: dict):
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")


def test_carryover_both_policy_split(tmp_path: Path):
    base = Path.cwd()
    # Build DET rows in prev/current/next periods so carryover can apply to both sides.
    agg = {
        "rows": [
            {
                "family": "F",
                "period": "2025-01",
                "demand": 100.0,
                "supply": 110.0,
                "backlog": 0.0,
            },
            {
                "family": "F",
                "period": "2025-02",
                "demand": 100.0,
                "supply": 100.0,
                "backlog": 0.0,
            },
            {
                "family": "F",
                "period": "2024-12",
                "demand": 100.0,
                "supply": 100.0,
                "backlog": 0.0,
            },
        ]
    }
    det = {
        "rows": [
            {
                "family": "F",
                "period": "2025-01",
                "week": "2025-01-Wk1",
                "demand": 100.0,
                "supply": 100.0,
                "backlog": 0.0,
            },
            {
                "family": "F",
                "period": "2025-02",
                "week": "2025-02-Wk1",
                "demand": 100.0,
                "supply": 100.0,
                "backlog": 0.0,
            },
            {
                "family": "F",
                "period": "2024-12",
                "week": "2024-12-Wk1",
                "demand": 100.0,
                "supply": 100.0,
                "backlog": 0.0,
            },
        ]
    }
    wj(tmp_path / "aggregate.json", agg)
    wj(tmp_path / "sku_week.json", det)
    env = {"PYTHONPATH": str(base)}
    subprocess.run(
        [
            "python3",
            "scripts/anchor_adjust.py",
            "-i",
            str(tmp_path / "aggregate.json"),
            str(tmp_path / "sku_week.json"),
            "-o",
            str(tmp_path / "out.json"),
            "--cutover-date",
            "2025-01-15",
            "--anchor-policy",
            "blend",
            "--max-adjust-ratio",
            "0",
            "--carryover",
            "both",
            "--carryover-split",
            "0.7",
        ],
        check=True,
        cwd=str(base),
        env=env,
    )
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    cov = out.get("carryover") or []
    # Expect logs to both prev and next
    assert any(r.get("to_period") == "2025-02" for r in cov)
    assert any(r.get("to_period") == "2024-12" for r in cov)
