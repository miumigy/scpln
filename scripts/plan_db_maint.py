"""Exports a plan from the database to JSON/CSV files."""

import argparse
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path to allow imports from app, core, etc.
project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))

from core.plan_repository import PlanRepository
from app import db


def backup_db(source_db_path: Path, destination_path: Path):
    """
    Backs up the SQLite database file.
    """
    print(f"Backing up DB from {source_db_path} to {destination_path}...")
    shutil.copy2(source_db_path, destination_path)
    print("Backup complete.")


def trim_old_plans(repo: PlanRepository, days: int):
    """
    Deletes plan versions older than a specified number of days.
    """
    print(f"Trimming plans older than {days} days...")
    cutoff_timestamp_ms = int(
        (datetime.now() - timedelta(days=days)).timestamp() * 1000
    )

    # Fetch plan versions (need a method in db.py or PlanRepository to list plan versions with created_at)
    # For now, we'll assume db.list_plan_versions returns created_at
    old_plans = []
    for p in db.list_plan_versions(limit=99999):  # Fetch all for now
        if p.get("created_at", 0) < cutoff_timestamp_ms:
            old_plans.append(p["version_id"])

    if not old_plans:
        print("No old plans to trim.")
        return

    print(f"Found {len(old_plans)} plans to trim: {', '.join(old_plans)}")
    for version_id in old_plans:
        try:
            repo.delete_plan(version_id)
            print(f"Deleted plan: {version_id}")
        except Exception as e:
            print(f"Error deleting plan {version_id}: {e}", file=sys.stderr)
    print("Trim complete.")


def trim_max_rows(repo: PlanRepository, max_rows: int):
    """
    Deletes oldest plan versions if the total count exceeds max_rows.
    """
    print(f"Trimming plans to keep max {max_rows} rows...")
    current_count = db.count_plan_versions()
    if current_count <= max_rows:
        print(
            f"Current plan count ({current_count}) is within limit ({max_rows}). No trim needed."
        )
        return

    to_delete_count = current_count - max_rows
    print(
        f"Current plan count ({current_count}) exceeds limit. Deleting {to_delete_count} oldest plans."
    )

    # Fetch oldest plan versions
    plans_to_delete_objs = db.list_plan_versions(
        limit=to_delete_count, order="created_asc"
    )
    plans_to_delete = [p["version_id"] for p in plans_to_delete_objs]

    if not plans_to_delete:
        print("No plans to trim by max rows.")
        return

    print(f"Found {len(plans_to_delete)} plans to trim: {', '.join(plans_to_delete)}")
    for version_id in plans_to_delete:
        try:
            repo.delete_plan(version_id)
            print(f"Deleted plan: {version_id}")
        except Exception as e:
            print(f"Error deleting plan {version_id}: {e}", file=sys.stderr)
    print("Trim complete.")


def trim_kpis(repo: PlanRepository, months: int):
    """
    Deletes KPI records older than a specified number of months.
    """
    print(f"Trimming KPIs older than {months} months...")
    try:
        deleted_count = repo.trim_kpis_by_age(months)
        print(f"Trimmed {deleted_count} KPI records.")
    except Exception as e:
        print(f"Error trimming KPIs: {e}", file=sys.stderr)


def show_backfill_summary(conn: sqlite3.Connection):
    """
    Displays a summary of backfill script runs.
    """
    print("Showing backfill run summary...")
    try:
        conn.row_factory = sqlite3.Row
        # Check if table exists
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='plan_backfill_runs'"
        )
        if cur.fetchone() is None:
            print("`plan_backfill_runs` table not found. No summary to show.")
            return

        summary_query = """
        SELECT
            COUNT(*) as total_runs,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_runs,
            SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) as partial_runs,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_runs,
            SUM(processed) as total_processed,
            SUM(skipped) as total_skipped,
            SUM(errors) as total_errors,
            AVG(duration_ms) as avg_duration_ms,
            MAX(started_at) as last_run_ts
        FROM plan_backfill_runs
        """
        summary = conn.execute(summary_query).fetchone()

        if not summary or summary["total_runs"] == 0:
            print("No backfill runs found.")
            return

        last_run_str = "N/A"
        if summary["last_run_ts"]:
            last_run_dt = datetime.fromtimestamp(summary["last_run_ts"] / 1000)
            last_run_str = last_run_dt.strftime("%Y-%m-%d %H:%M:%S")

        print("\n--- Backfill Run Summary ---")
        print(f"  Total Runs: {summary['total_runs']}")
        print(f"    - Success: {summary['success_runs'] or 0}")
        print(f"    - Partial: {summary['partial_runs'] or 0}")
        print(f"    - Failed: {summary['failed_runs'] or 0}")
        print(f"  Total Processed Plans: {summary['total_processed'] or 0}")
        print(f"  Total Skipped Plans: {summary['total_skipped'] or 0}")
        print(f"  Total Errors: {summary['total_errors'] or 0}")
        print(
            f"  Average Duration (ms): {summary['avg_duration_ms']:.2f}"
            if summary["avg_duration_ms"]
            else "N/A"
        )
        print(f"  Last Run Started: {last_run_str}")
        print("--------------------------\n")

    except Exception as e:
        print(f"Error fetching backfill summary: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Plan DB maintenance script.")
    parser.add_argument(
        "--backup",
        type=Path,
        help="Path to backup the DB file to.",
    )
    parser.add_argument(
        "--trim-old",
        type=int,
        metavar="DAYS",
        help="Delete plan versions older than specified days.",
    )
    parser.add_argument(
        "--trim-max-rows",
        type=int,
        metavar="COUNT",
        help="Delete oldest plan versions if total count exceeds specified number.",
    )
    parser.add_argument(
        "--trim-kpis",
        action="store_true",
        help="Delete KPI records older than the specified retention period.",
    )
    parser.add_argument(
        "--kpi-retention-months",
        type=int,
        default=24,
        metavar="MONTHS",
        help="Set the retention period in months for KPIs (default: 24).",
    )
    parser.add_argument(
        "--show-backfill-summary",
        action="store_true",
        help="Show a summary of backfill script runs.",
    )
    args = parser.parse_args()

    try:
        db.init_db()
        repo = PlanRepository(db._conn)
        source_db_path = Path(db._db_path())

        if args.backup:
            backup_db(source_db_path, args.backup)

        if args.trim_old:
            trim_old_plans(repo, args.trim_old)

        if args.trim_max_rows:
            trim_max_rows(repo, args.trim_max_rows)

        if args.trim_kpis:
            trim_kpis(repo, args.kpi_retention_months)

        if args.show_backfill_summary:
            show_backfill_summary(db._conn())

        if not (
            args.backup
            or args.trim_old
            or args.trim_max_rows
            or args.trim_kpis
            or args.show_backfill_summary
        ):
            parser.print_help()

    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
