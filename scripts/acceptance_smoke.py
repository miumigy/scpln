#!/usr/bin/env python3
"""
Acceptance smoke for Planning Hub (AT-01 .. AT-07)

Usage:
  python scripts/acceptance_smoke.py --base-url http://localhost:8000

前提:
- アプリが起動済み（uvicorn main:app --reload など）

検証観点（要約）:
- AT-01: Plan作成→summary取得、/ui/plans と /ui/plans/{id} のHTML軽検証
- AT-02: '/' が /ui/plans へリダイレクト
- AT-03: /runs 非同期でジョブ投入され、/ui/jobs への location が返る
- AT-04: Plan & Run（自動補完）で新規Planが作成される
- AT-05: /plans/{id}/summary に recon/weekly_summary が出力される
- AT-06: /plans/{id}/compare(.csv) 取得（limit/violations_only 整合）
- AT-07: /metrics 主要カウンタの存在と増分
"""

from __future__ import annotations

import sys
import time
import argparse
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import requests  # type: ignore
except Exception:
    print("[ERROR] requests が必要です: pip install requests", file=sys.stderr)
    sys.exit(2)


def seed_test_data(db_path: str):
    """テスト用の canonical config (id=100) をDBに直接挿入する。"""
    import sqlite3
    import json

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # 既に存在する場合は何もしない
        res = cur.execute("SELECT id FROM canonical_config_versions WHERE id=100").fetchone()
        if res:
            print("[INFO] Test data (config_version_id=100) already exists.")
            return

        print("[INFO] Seeding test data (config_version_id=100)...")
        meta_attributes = {
            "planning_horizon": 90,
            "sources": {"psi_input": "seed.json"},
        }
        cur.execute(
            """
            INSERT INTO canonical_config_versions(
                id, name, schema_version, version_tag, status, description,
                source_config_id, metadata_json, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                100,
                "test-config",
                "canonical-1.0",
                "v-test",
                "draft",
                "acceptance smoke seed",
                None,
                json.dumps(meta_attributes, ensure_ascii=False),
                1700000000000,
                1700000000000,
            ),
        )
        # 簡易的に item, node, demand のみ追加
        cur.execute(
            "INSERT INTO canonical_items (config_version_id, item_code, item_name) VALUES (?, ?, ?)",
            (100, "FG1", "Acceptance FG"),
        )
        cur.execute(
            "INSERT INTO canonical_nodes (config_version_id, node_code, node_type) VALUES (?, ?, ?)",
            (100, "STORE1", "store"),
        )
        cur.execute(
            "INSERT INTO canonical_demands (config_version_id, node_code, item_code, bucket, mean) VALUES (?, ?, ?, ?, ?)",
            (100, "STORE1", "FG1", "2025-W01", 10),
        )
        conn.commit()
        print("[INFO] Test data seeded successfully.")
    except Exception as e:
        print(f"[WARN] Failed to seed test data: {e}", file=sys.stderr)
    finally:
        if conn:
            conn.close()


def get_json(session: requests.Session, url: str) -> Dict[str, Any]:
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def post_form(
    session: requests.Session, url: str, data: Dict[str, Any]
) -> requests.Response:
    return session.post(url, data=data, timeout=60, allow_redirects=False)


def post_json(
    session: requests.Session, url: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    r = session.post(url, json=data, timeout=120)
    r.raise_for_status()
    return r.json()


def fetch_metrics(session: requests.Session, url: str) -> Dict[str, int]:
    r = session.get(url, timeout=15)
    r.raise_for_status()
    text = r.text
    out: Dict[str, int] = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        parts = line.strip().split()
        if len(parts) >= 2:
            name = parts[0].split("{")[0]
            if name.endswith("_total"):
                try:
                    current_value = out.get(name, 0)
                    out[name] = current_value + int(float(parts[-1]))
                except (ValueError, IndexError):
                    pass
    return out


def latest_plan_id(session: requests.Session, base: str) -> Optional[str]:
    try:
        data = get_json(session, f"{base}/plans")
        plans = data.get("plans") or []
        if not isinstance(plans, list) or not plans:
            return None
        # created_at があれば最大を選ぶ。なければ末尾。
        plans2 = [p for p in plans if isinstance(p, dict)]
        plans2.sort(key=lambda p: (p.get("created_at") or 0), reverse=True)
        return (plans2[0] or {}).get("version_id")
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--db-path", default="scpln.db")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    s = requests.Session()

    db_path = Path(args.db_path).resolve()
    os.environ["SCPLN_DB"] = str(db_path)

    # Alembicマイグレーションを実行
    try:
        alembic_ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
        if not alembic_ini_path.exists():
            raise RuntimeError(f"alembic.ini not found at {alembic_ini_path}")

        print(f"[INFO] Running Alembic migrations on {db_path}...")
        proc = subprocess.run(
            ["alembic", "-c", str(alembic_ini_path), "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        print("[INFO] Alembic migration completed.")
    except FileNotFoundError:
        print("[WARN] 'alembic' command not found. Skipping migration.", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        # 既に適用済みの場合も stderr にログが出ることがあるので WARN に留める
        print(f"[WARN] Alembic migration may have failed (exit code {e.returncode}): {e.stderr}", file=sys.stderr)

    # DBにテストデータを投入
    seed_test_data(str(db_path))

    failures: list[str] = []

    def ok(name: str):
        print(f"[OK] {name}")

    def ng(name: str, msg: str):
        failures.append(f"{name}: {msg}")
        print(f"[NG] {name}: {msg}")

    # Metrics before
    metrics_before = {}
    try:
        metrics_before = fetch_metrics(s, f"{base}/metrics")
        ok("AT-07 preload metrics")
    except Exception as e:
        ng("AT-07 preload metrics", str(e))

    # AT-02: Home リダイレクト
    try:
        r = s.get(f"{base}/", allow_redirects=False, timeout=10)
        if r.status_code in (301, 302, 307, 308) and (
            r.headers.get("Location", "").startswith("/ui/plans")
        ):
            ok("AT-02 Home→/ui/plans リダイレクト")
        else:
            ng(
                "AT-02 Home リダイレクト",
                f"code={r.status_code} location={r.headers.get('Location')}",
            )
    except Exception as e:
        ng("AT-02 Home リダイレクト", str(e))

    # AT-01: Plan 作成（UI経由: metrics計測も狙う）
    try:
        form = {
            "config_version_id": "100",
            "weeks": 4,
            "lt_unit": "day",
            "cutover_date": "2025-01-15",
            "recon_window_days": 14,
            "anchor_policy": "blend",
            "tol_abs": "1e-6",
            "tol_rel": "1e-6",
            "calendar_mode": "iso",
            "carryover": "both",
            "carryover_split": 0.5,
            "apply_adjusted": 1,
        }
        r = post_form(s, f"{base}/ui/plans/run", form)
        if r.status_code not in (302, 303):
            ng("AT-01 Plan作成", f"unexpected status: {r.status_code}")
        # 生成・永続の少しの遅延を待機
        time.sleep(0.6)
        vid = latest_plan_id(s, base)
        if not vid:
            ng("AT-01 Plan作成", "version_id が取得できませんでした")
        else:
            # summary（必須キー）
            summ = get_json(s, f"{base}/plans/{vid}/summary")
            if "weekly_summary" in summ:
                ok("AT-01 Plan作成→summary取得")
            else:
                ng("AT-01 Plan作成→summary取得", "weekly_summary 欠落")
            plan_id = vid
            # HTML: /ui/plans 一覧
            try:
                rlist = s.get(f"{base}/ui/plans", timeout=30)
                if rlist.status_code == 200 and ("Plan Versions" in rlist.text):
                    if "aria-label=" in rlist.text:
                        ok("HTML: /ui/plans: code=200, title/aria-label OK")
                    else:
                        ng("HTML: /ui/plans", "aria-label not found")
                else:
                    ng("HTML: /ui/plans", f"code={rlist.status_code}")
            except Exception as e:
                ng("HTML: /ui/plans", str(e))
            # HTML: /ui/plans/{id} 詳細
            try:
                rdet = s.get(f"{base}/ui/plans/{vid}", timeout=30)
                if rdet.status_code == 200 and (
                    "Plan Detail" in rdet.text or 'data-tab="overview"' in rdet.text
                ):
                    # Representative tab aria-labels
                    labels = [
                        "Overview tab",
                        "Aggregate tab",
                        "Disaggregate tab",
                        "Schedule tab",
                        "Validate tab",
                        "PSI tab",
                        "Execute tab",
                        "Results tab",
                        "Diff tab",
                    ]
                    if any((f'aria-label="{lab}"' in rdet.text) for lab in labels):
                        ok("HTML: /ui/plans/{id}: code=200, tab aria-label OK")
                    else:
                        ng("HTML: /ui/plans/{id}", "tab aria-label not found")
                else:
                    ng("HTML: /ui/plans/{id}", f"code={rdet.status_code}")
            except Exception as e:
                ng("HTML: /ui/plans/{id}", str(e))
    except Exception as e:
        ng("AT-01 Plan作成", str(e))
        plan_id = None  # type: ignore

    # AT-03: /runs 非同期（ジョブ投入→location）
    try:
        payload = {
            "pipeline": "integrated",
            "async": True,
            "options": {
                "config_version_id": 100,
                "weeks": 1,
                "lt_unit": "day",
            },
        }
        res = post_json(s, f"{base}/runs", payload)
        loc = (res or {}).get("location") or ""
        if (res.get("status") == "queued") and loc.startswith("/ui/jobs/"):
            # location が開ける（200系）ことを確認
            rj = s.get(f"{base}{loc}", timeout=30)
            if rj.status_code // 100 == 2:
                ok("AT-03 /runs 非同期→/ui/jobs へ誘導")
            else:
                ng("AT-03 /runs 非同期", f"jobs page code={rj.status_code}")
        else:
            ng("AT-03 /runs 非同期", f"unexpected response: {res}")
    except Exception as e:
        ng("AT-03 /runs 非同期", str(e))

    # AT-04: Plan & Run（自動補完）
    new_plan_id: Optional[str] = None
    try:
        if plan_id:
            form = {
                "weeks": 4,
                "lt_unit": "day",
                "cutover_date": "2025-02-01",
                "recon_window_days": 7,
                "anchor_policy": "blend",
                "tol_abs": "1e-6",
                "tol_rel": "1e-6",
                "calendar_mode": "iso",
                "carryover": "both",
                "carryover_split": 0.5,
                "apply_adjusted": 1,
                # queue_job は未指定（同期）
            }
            r2 = post_form(s, f"{base}/ui/plans/{plan_id}/plan_run_auto", form)
            if r2.status_code not in (302, 303):
                ng("AT-04 Plan&Run", f"unexpected status: {r2.status_code}")
            time.sleep(0.6)
            new_plan_id = latest_plan_id(s, base)
            if new_plan_id and new_plan_id != plan_id:
                ok("AT-04 Plan&Run（自動補完）で新規Plan作成")
            else:
                ng("AT-04 Plan&Run", "新規Planが検出できませんでした")
        else:
            ng("AT-04 Plan&Run", "前提のPlanがありません")
    except Exception as e:
        ng("AT-04 Plan&Run", str(e))

    # AT-05: Validate相当の情報（summaryにreconciliation/weekly_summary）
    try:
        if plan_id:
            summ = get_json(s, f"{base}/plans/{plan_id}/summary")
            if (summ.get("reconciliation") is not None) and (
                summ.get("weekly_summary") is not None
            ):
                ok("AT-05 Validate 情報の存在（reconciliation/weekly_summary）")
            else:
                ng("AT-05 Validate 情報", "必要キーが見つかりません")
        else:
            ng("AT-05 Validate 情報", "前提のPlanがありません")
    except Exception as e:
        ng("AT-05 Validate 情報", str(e))

    # AT-06: Compare に Plan 紐づき（limit/violations_only 整合）
    try:
        if plan_id:
            limit = 50
            j = get_json(
                s,
                f"{base}/plans/{plan_id}/compare?violations_only=true&sort=rel_desc&limit={limit}",
            )
            rows = j.get("rows") if isinstance(j, dict) else None
            if isinstance(rows, list) and len(rows) <= limit:
                viol_ok = all((not bool(r.get("ok"))) for r in rows)
                if viol_ok or len(rows) == 0:
                    ok("AT-06 Compare JSON 取得（limit/violations_only整合）")
                else:
                    ng("AT-06 Compare JSON", "violations_only で ok=true を含む")
            else:
                ng("AT-06 Compare JSON", "rows 欠落/型不正")
            r = s.get(
                f"{base}/plans/{plan_id}/compare.csv?violations_only=true&sort=abs_desc&limit=100",
                timeout=30,
            )
            lines = r.text.splitlines() if r.status_code == 200 else []
            if (
                r.status_code == 200
                and len(lines) >= 1
                and lines[0].startswith("family,period")
            ):
                # ヘッダ以外の行数が上限内
                if len(lines) - 1 <= 100:
                    ok("AT-06 Compare CSV 取得（ヘッダ/件数上限）")
                else:
                    ng("AT-06 Compare CSV", f"件数超過: {len(lines)-1}")
            else:
                ng("AT-06 Compare CSV", f"code={r.status_code}")
        else:
            ng("AT-06 Compare", "前提のPlanがありません")
    except Exception as e:
        ng("AT-06 Compare", str(e))

    # Export（schedule/carryover）でメトリクスも動かす（件数・数値性の軽検証）
    try:
        if plan_id:
            r = s.get(f"{base}/plans/{plan_id}/schedule.csv", timeout=30)
            lines = r.text.splitlines() if r.status_code == 200 else []
            if (
                r.status_code == 200
                and len(lines) >= 2
                and lines[0].startswith("week,sku")
            ):
                try:
                    import csv
                    from io import StringIO

                    rows = list(csv.DictReader(StringIO(r.text)))
                    data_rows = len(rows)
                    if data_rows < 1:
                        ng("Export schedule.csv", "データ行が0件")
                    else:
                        # 数値性: scheduled_receipts と on_hand_start
                        for rr in rows[:10]:
                            float(rr.get("scheduled_receipts"))
                            float(rr.get("on_hand_start"))
                        ok("Export schedule.csv（下限/数値性OK）")
                except Exception as e:
                    ng("Export schedule.csv", f"CSV parse/数値性: {e}")
            else:
                ng("Export schedule.csv", f"code={r.status_code}")
            # carryover（adjustedなしでも空CSVが返る場合あり）
            r = s.get(f"{base}/plans/{plan_id}/carryover.csv", timeout=30)
            if r.status_code == 200:
                ok("Export carryover.csv")
            else:
                ng("Export carryover.csv", f"code={r.status_code}")
        else:
            ng("Export CSV", "前提のPlanがありません")
    except Exception as e:
        ng("Export CSV", str(e))

    # Metrics after
    try:
        metrics_after = fetch_metrics(s, f"{base}/metrics")
        # 期待するメトリクス（存在）
        expected = [
            "plans_created_total",
            "plans_viewed_total",
            "runs_queued_total",
            "plan_schedule_export_total",
            "plan_compare_export_total",
            "plan_carryover_export_total",
        ]
        missing = [k for k in expected if k not in metrics_after]
        if missing:
            ng("AT-07 metrics 存在チェック", f"missing: {missing}")
        # 増分（最低限: created/viewed/schedule/compare のどれかが増える）
        inc_names = []
        for name in (
            "plans_created_total",
            "plans_viewed_total",
            "plan_schedule_export_total",
            "plan_compare_export_total",
        ):
            before = metrics_before.get(name, 0)
            after = metrics_after.get(name, 0)
            if after > before:
                inc_names.append(name)
        if inc_names:
            ok(f"AT-07 metrics 増分: {', '.join(inc_names)}")
        else:
            ng("AT-07 metrics 増分", "対象カウンタに増分なし")
    except Exception as e:
        ng("AT-07 metrics", str(e))

    print("\n==== Summary ====")
    if failures:
        for m in failures:
            print("- ", m)
        return 1
    print("All acceptance checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
