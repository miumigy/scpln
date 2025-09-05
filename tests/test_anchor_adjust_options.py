from __future__ import annotations

import json
import subprocess
from pathlib import Path


def write_json(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def test_anchor_adjust_tol_rel_skip(tmp_path: Path):
    base = Path.cwd()
    agg = {"rows": [{"family": "F", "period": "2025-01", "demand": 100.0, "supply": 100.0, "backlog": 0.0}]}
    # DETは1%のズレ
    det = {"rows": [{"family": "F", "period": "2025-01", "week": "2025-01-Wk1", "demand": 100.0, "supply": 99.0, "backlog": 1.0}]}
    write_json(tmp_path / "aggregate.json", agg)
    write_json(tmp_path / "sku_week.json", det)
    env = {"PYTHONPATH": str(base)}
    subprocess.run([
        "python3", "scripts/anchor_adjust.py", "-i", str(tmp_path / "aggregate.json"), str(tmp_path / "sku_week.json"),
        "-o", str(tmp_path / "out.json"), "--cutover-date", "2025-01-15", "--tol-rel", "0.02"  # 2% 許容
    ], check=True, cwd=str(base), env=env)
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    # スキップにより行がそのまま
    assert out.get("rows", []) == det["rows"]


def test_anchor_adjust_carryover_both(tmp_path: Path):
    base = Path.cwd()
    agg = {"rows": [
        {"family": "F", "period": "2025-01", "demand": 100.0, "supply": 100.0, "backlog": 0.0},
        {"family": "F", "period": "2025-02", "demand": 100.0, "supply": 100.0, "backlog": 0.0},
    ]}
    # DETの2025-01 に残差を意図的に残す設定（max-adjust-ratio=0でcarryoverさせる）
    det = {"rows": [
        {"family": "F", "period": "2025-01", "week": "2025-01-Wk1", "demand": 100.0, "supply": 90.0, "backlog": 10.0}
    ]}
    write_json(tmp_path / "aggregate.json", agg)
    write_json(tmp_path / "sku_week.json", det)
    env = {"PYTHONPATH": str(base)}
    subprocess.run([
        "python3", "scripts/anchor_adjust.py", "-i", str(tmp_path / "aggregate.json"), str(tmp_path / "sku_week.json"),
        "-o", str(tmp_path / "out.json"), "--cutover-date", "2025-01-15", "--anchor-policy", "blend",
        "--max-adjust-ratio", "0", "--carryover", "both"
    ], check=True, cwd=str(base), env=env)
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    cov = out.get("carryover") or []
    # prev(2024-12) or next(2025-02) のいずれか、通常は next が存在
    assert any(r.get("to_period") == "2025-02" for r in cov)

