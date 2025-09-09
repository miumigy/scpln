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
- AT-03: /ui/planning が 302→/ui/plans または 404(ガイド)
- AT-04: Plan & Run（自動補完）で新規Planが作成される
- AT-05: /plans/{id}/summary に recon/weekly_summary が出力される
- AT-06: /plans/{id}/compare(.csv) 取得（limit/violations_only 整合）
- AT-07: /metrics 主要カウンタの存在と増分
"""

from __future__ import annotations

import sys
import time
import argparse
from typing import Dict, Any, Optional

try:
    import requests  # type: ignore
except Exception:
    print("[ERROR] requests が必要です: pip install requests", file=sys.stderr)
    sys.exit(2)


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
        if len(parts) == 2 and parts[0].endswith("_total"):
            name = parts[0]
            try:
                out[name] = int(float(parts[1]))
            except Exception:
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
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    s = requests.Session()

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
            "input_dir": "samples/planning",
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
                if rlist.status_code == 200 and ("プランバージョン一覧" in rlist.text):
                    if "aria-label=" in rlist.text:
                        ok("HTML: /ui/plans が200で見出し/aria-labelを含む")
                    else:
                        ng("HTML: /ui/plans", "aria-label が見つかりません")
                else:
                    ng("HTML: /ui/plans", f"code={rlist.status_code}")
            except Exception as e:
                ng("HTML: /ui/plans", str(e))
            # HTML: /ui/plans/{id} 詳細
            try:
                rdet = s.get(f"{base}/ui/plans/{vid}", timeout=30)
                if rdet.status_code == 200 and (
                    "プラン詳細" in rdet.text or 'data-tab="overview"' in rdet.text
                ):
                    # 代表的なタブ aria-label を確認
                    labels = [
                        "概要タブ",
                        "集約タブ",
                        "詳細展開タブ",
                        "予定オーダタブ",
                        "検証タブ",
                        "実行タブ",
                        "結果タブ",
                        "差分タブ",
                    ]
                    if any((f'aria-label="{lab}"' in rdet.text) for lab in labels):
                        ok("HTML: /ui/plans/{id} が200でタブ aria-label を含む")
                    else:
                        ng("HTML: /ui/plans/{id}", "タブ aria-label が見つかりません")
                else:
                    ng("HTML: /ui/plans/{id}", f"code={rdet.status_code}")
            except Exception as e:
                ng("HTML: /ui/plans/{id}", str(e))
    except Exception as e:
        ng("AT-01 Plan作成", str(e))
        plan_id = None  # type: ignore

    # AT-03: 旧UI誘導
    try:
        r = s.get(f"{base}/ui/planning", allow_redirects=False, timeout=10)
        if r.status_code in (301, 302) and r.headers.get("Location", "").startswith(
            "/ui/plans"
        ):
            ok("AT-03 /ui/planning → /ui/plans (302)")
        elif r.status_code == 404:
            ok("AT-03 /ui/planning 404 ガイド表示")
        else:
            ng(
                "AT-03 旧UI誘導",
                f"code={r.status_code} location={r.headers.get('Location')}",
            )
    except Exception as e:
        ng("AT-03 旧UI誘導", str(e))

    # AT-04: Plan & Run（自動補完）
    new_plan_id: Optional[str] = None
    try:
        if plan_id:
            form = {
                "input_dir": "samples/planning",
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
