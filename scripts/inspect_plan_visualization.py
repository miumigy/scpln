#!/usr/bin/env python
"""
PlanのVisualizationで使用するweekly_summaryデータを点検するユーティリティ。

Usage:
  PYTHONPATH=. .venv/bin/python scripts/inspect_plan_visualization.py <version_id>
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from app import db
from core.plan_repository import PlanRepository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version_id")
    args = parser.parse_args()
    version_id = args.version_id

    plan = db.get_plan_version(version_id)
    if not plan:
        print(f"[error] plan_version {version_id} not found in plan_versions table")
        return

    plan_final = db.get_plan_artifact(version_id, "plan_final.json")
    if plan_final:
        ws_artifact = list(plan_final.get("weekly_summary") or [])
    else:
        ws_artifact = []
    repo = PlanRepository(db._conn)
    ws_repo = repo.fetch_plan_series(version_id, "weekly_summary")

    print(f"[info] plan_version found created_at={plan.get('created_at')}")
    print(f"[info] weekly_summary (artifact) rows={len(ws_artifact)}")
    if ws_artifact:
        sample = ws_artifact[:5]
        print(json.dumps(sample, ensure_ascii=False, indent=2))
    else:
        print("[]")
    print(f"[info] weekly_summary (repository) rows={len(ws_repo)}")
    if ws_repo:
        sample = []
        for row in ws_repo[:5]:
            entry = {
                "week": row.get("time_bucket_key"),
                "zone": row.get("boundary_zone"),
                "demand": row.get("demand"),
                "supply": row.get("supply"),
                "capacity_used": row.get("capacity_used"),
            }
            try:
                extra = json.loads(row.get("extra_json") or "{}")
                entry.update(
                    {
                        "spill_in": extra.get("spill_in"),
                        "spill_out": extra.get("spill_out"),
                        "capacity_extra": extra.get("capacity"),
                    }
                )
            except Exception:
                pass
            sample.append(entry)
        print(json.dumps(sample, ensure_ascii=False, indent=2))
    else:
        print("[]")


if __name__ == "__main__":
    main()
