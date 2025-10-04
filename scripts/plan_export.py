'''Exports a plan from the database to JSON/CSV files.'''

import argparse
import json
import csv
from pathlib import Path
import sys

# Add project root to path to allow imports from app, core, etc.
project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))

from core.plan_repository import PlanRepository
from app import db

def export_plan(version_id: str, out_dir: Path):
    """
    Exports a plan from the database to JSON/CSV files.
    """
    print(f"Exporting plan {version_id} to {out_dir}...")
    out_dir.mkdir(parents=True, exist_ok=True)

    repo = PlanRepository(db._conn)

    # 1. Fetch data from PlanRepository
    print("Fetching data from database...")
    agg_rows = repo.fetch_plan_series(version_id, level="aggregate")
    det_rows = repo.fetch_plan_series(version_id, level="det")
    mrp_rows = repo.fetch_plan_series(version_id, level="mrp")
    kpi_rows = repo.fetch_plan_kpis(version_id)

    # 2. Convert and write to files
    print("Writing files...")

    # aggregate.json
    agg_json_rows = [
        {
            "family": r.get("item_key"),
            "period": r.get("time_bucket_key"),
            "demand": r.get("demand"),
            "supply": r.get("supply"),
            "backlog": r.get("backlog"),
            "capacity_total": r.get("capacity_used"),
        }
        for r in agg_rows
    ]
    (out_dir / "aggregate.json").write_text(
        json.dumps({"rows": agg_json_rows}, indent=2, ensure_ascii=False)
    )

    # sku_week.json
    det_json_rows = []
    for r in det_rows:
        extra = json.loads(r.get("extra_json") or "{}")
        det_json_rows.append(
            {
                "sku": r.get("item_key"),
                "week": r.get("time_bucket_key"),
                "demand": r.get("demand"),
                "supply_plan": r.get("supply"),  # Note: key name is different
                "backlog": r.get("backlog"),
                "family": extra.get("family"),
                "period": extra.get("period"),
            }
        )
    (out_dir / "sku_week.json").write_text(
        json.dumps({"rows": det_json_rows}, indent=2, ensure_ascii=False)
    )

    # mrp.json
    mrp_json_rows = []
    for r in mrp_rows:
        extra = json.loads(r.get("extra_json") or "{}")
        mrp_json_rows.append(
            {
                "item": r.get("item_key"),
                "week": r.get("time_bucket_key"),
                "gross_req": r.get("demand"),
                "scheduled_receipts": extra.get("scheduled_receipts"),
                "planned_order_receipt": r.get("supply"),
                "planned_order_release": extra.get("planned_order_release"),
                "on_hand_start": extra.get("on_hand_start"),
                "on_hand_end": extra.get("on_hand_end"),
                "net_req": r.get("backlog"),
                "lot": extra.get("lot"),
                "moq": extra.get("moq"),
                "lt_weeks": extra.get("lt_weeks"),
            }
        )
    (out_dir / "mrp.json").write_text(
        json.dumps({"rows": mrp_json_rows}, indent=2, ensure_ascii=False)
    )

    # report.csv (kpi summary)
    if kpi_rows:
        with (out_dir / "report.csv").open("w", newline="", encoding="utf-8") as f:
            # Filter for total KPIs for a simpler report
            total_kpis = [r for r in kpi_rows if r.get("bucket_type") == "total"]
            if total_kpis:
                fieldnames = total_kpis[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(total_kpis)

    print("Export complete.")


def main():
    parser = argparse.ArgumentParser(description="Export a plan from the DB to files.")
    parser.add_argument("version_id", help="The version_id of the plan to export.")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        required=True,
        help="Output directory to save the exported files.",
    )
    args = parser.parse_args()

    try:
        db.init_db()
        export_plan(args.version_id, args.out_dir)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
