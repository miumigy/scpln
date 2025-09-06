#!/usr/bin/env python3
"""
集約↔詳細の差分ログ（v1）

目的:
- DET（SKU×週）を family×period にロールアップし、AGG（family×period）との差分を算出してログ出力。
- 既存パイプラインへ非破壊に追加できる最小機能。

使い方:
  PYTHONPATH=. python3 scripts/reconcile_levels.py \
    -i out/aggregate.json out/sku_week.json \
    -o out/reconciliation_log.json \
    --version v1 --tol-abs 1e-6 --tol-rel 1e-6
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Tuple, DefaultDict


def _period_from_week(week_key: str) -> str:
    """簡易に週キーから期間キー（YYYY-MM）を推定。
    期待形式: 'YYYY-MM-WkX' または 'YYYY-MM' を想定。
    """
    s = str(week_key)
    if len(s) >= 7 and s[4] == "-":
        return s[:7]
    return s


def _load_inputs(paths: List[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if len(paths) != 2:
        raise ValueError(
            "-i/--inputs には2ファイルを指定してください（aggregate と sku_week）"
        )
    with open(paths[0], encoding="utf-8") as f:
        a0 = json.load(f)
    with open(paths[1], encoding="utf-8") as f:
        a1 = json.load(f)

    # 判定: sku/week があれば DET とみなす
    def looks_det(a: Dict[str, Any]) -> bool:
        rows = a.get("rows", [])
        if not rows:
            return False
        r0 = rows[0]
        return ("sku" in r0) or ("week" in r0)

    if looks_det(a0):
        det, agg = a0, a1
    elif looks_det(a1):
        det, agg = a1, a0
    else:
        # フォールバック: 片方に period/family、もう片方に week/sku が多い方
        c0 = sum(1 for r in a0.get("rows", []) if ("family" in r and "period" in r))
        c1 = sum(1 for r in a1.get("rows", []) if ("family" in r and "period" in r))
        if c0 >= c1:
            agg, det = a0, a1
        else:
            agg, det = a1, a0
    return agg, det


def _sum3(d: Dict[str, float]) -> float:
    return (
        float(d.get("demand", 0) or 0)
        + float(d.get("supply", 0) or 0)
        + float(d.get("backlog", 0) or 0)
    )


def _round6(x: float) -> float:
    try:
        return round(float(x), 6)
    except Exception:
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="AGG/DET ロールアップ差分ログ（v1）")
    ap.add_argument(
        "-i",
        "--inputs",
        nargs=2,
        required=True,
        help="aggregate.json と sku_week.json のパス（順不同可）",
    )
    ap.add_argument("-o", "--output", required=True, help="差分ログの出力JSON")
    ap.add_argument(
        "--version", dest="version_id", default=None, help="任意のversion_id"
    )
    ap.add_argument(
        "--tol-abs", dest="tol_abs", type=float, default=1e-6, help="絶対許容誤差"
    )
    ap.add_argument(
        "--tol-rel", dest="tol_rel", type=float, default=1e-6, help="相対許容誤差"
    )
    ap.add_argument(
        "--weeks",
        dest="weeks_per_period",
        type=int,
        default=4,
        help="月→週の週数ヒント（キー整形補助）",
    )
    # v2入口: cutover/window/anchor の受け口（ログに反映、簡易境界タグ付け）
    ap.add_argument(
        "--cutover-date",
        dest="cutover_date",
        default=None,
        help="境界日 YYYY-MM-DD（任意）",
    )
    ap.add_argument(
        "--recon-window-days",
        dest="recon_window_days",
        type=int,
        default=None,
        help="整合ウィンドウ日数（任意）",
    )
    ap.add_argument(
        "--anchor-policy",
        dest="anchor_policy",
        default=None,
        help="anchorポリシー（DET_near|AGG_far|blend 等、任意）",
    )
    args = ap.parse_args()

    agg, det = _load_inputs(args.inputs)
    agg_rows: List[Dict[str, Any]] = agg.get("rows", [])
    det_rows: List[Dict[str, Any]] = det.get("rows", [])

    # AGG: (family, period) -> 指標
    agg_map: Dict[Tuple[str, str], Dict[str, float]] = {}
    families: set[str] = set()
    periods: set[str] = set()
    for r in agg_rows:
        fam = str(r.get("family"))
        per = str(r.get("period"))
        families.add(fam)
        periods.add(per)
        agg_map[(fam, per)] = {
            "demand": float(r.get("demand", 0) or 0),
            "supply": float(r.get("supply", 0) or 0),
            "backlog": float(r.get("backlog", 0) or 0),
        }

    # DETロールアップ: (family, period) -> 指標合計
    from collections import defaultdict as _dd

    det_map: DefaultDict[Tuple[str, str], Dict[str, float]] = _dd(
        lambda: {"demand": 0.0, "supply": 0.0, "backlog": 0.0}
    )
    for r in det_rows:
        fam = str(r.get("family") or r.get("item") or "")
        if not fam:
            continue
        # period はあれば使用、無ければ week から推定
        per = r.get("period")
        if per is None:
            per = _period_from_week(str(r.get("week")))
        per = str(per)
        families.add(fam)
        periods.add(per)
        det_map[(fam, per)]["demand"] += float(r.get("demand", 0) or 0)
        det_map[(fam, per)]["supply"] += float(r.get("supply", 0) or 0)
        det_map[(fam, per)]["backlog"] += float(r.get("backlog", 0) or 0)

    # 差分算出
    metrics = ("demand", "supply", "backlog")
    deltas: List[Dict[str, Any]] = []
    tol_violations = 0
    max_abs_delta: Dict[str, float] = {m: 0.0 for m in metrics}
    # cutover 月（YYYY-MM）を抽出（簡易タグ用）
    cutover_month = None
    cutover_iso = None
    if args.cutover_date:
        try:
            s = str(args.cutover_date)
            if len(s) >= 7 and s[4] == "-":
                cutover_month = s[:7]
            # ISO週キー 'YYYY-Www'
            import datetime as _dt

            parts = s.split("-")
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            iso = _dt.date(y, m, d).isocalendar()
            cutover_iso = f"{iso.year:04d}-W{iso.week:02d}"
        except Exception:
            cutover_month = None
            cutover_iso = None

    keys = sorted({*agg_map.keys(), *det_map.keys()})
    for fam_per in keys:
        fam, per = fam_per
        a = agg_map.get(fam_per, {m: 0.0 for m in metrics})
        d = det_map.get(fam_per, {m: 0.0 for m in metrics})

        row: Dict[str, Any] = {"family": fam, "period": per}
        ok_all = True
        for m in metrics:
            av = float(a.get(m, 0) or 0)
            dv = float(d.get(m, 0) or 0)
            delta = dv - av  # DET - AGG を正の向きとする
            denom = max(abs(av), abs(dv), 1.0)
            rel = (abs(delta) / denom) if denom > 0 else 0.0
            ok_m = (abs(delta) <= args.tol_abs) or (rel <= args.tol_rel)
            if not ok_m:
                ok_all = False
                tol_violations += 1
            max_abs_delta[m] = max(max_abs_delta[m], abs(delta))
            row[f"agg_{m}"] = _round6(av)
            row[f"det_{m}"] = _round6(dv)
            row[f"delta_{m}"] = _round6(delta)
            row[f"rel_{m}"] = _round6(rel)
            row[f"ok_{m}"] = ok_m
        row["ok"] = ok_all
        if (cutover_month and per == cutover_month) or (
            cutover_iso and per == cutover_iso
        ):
            row["boundary_period"] = True
        deltas.append(row)

    # 境界違反の要約（v2ステップ1）
    boundary_rows = [r for r in deltas if r.get("boundary_period")]
    boundary_violations = [r for r in boundary_rows if not r.get("ok")]
    boundary_max_abs: Dict[str, float] = {m: 0.0 for m in metrics}
    for r in boundary_rows:
        for m in metrics:
            boundary_max_abs[m] = max(
                boundary_max_abs[m], abs(float(r.get(f"delta_{m}", 0) or 0))
            )

    # 重要差分（上位10件）: |Δ| の最大値でソート
    def _key_absmax(row: Dict[str, Any]) -> float:
        return max(
            abs(float(row.get("delta_demand", 0) or 0)),
            abs(float(row.get("delta_supply", 0) or 0)),
            abs(float(row.get("delta_backlog", 0) or 0)),
        )

    boundary_top = sorted(boundary_rows, key=_key_absmax, reverse=True)[:10]
    boundary_top_view = [
        {
            "family": r.get("family"),
            "period": r.get("period"),
            "delta_demand": r.get("delta_demand"),
            "delta_supply": r.get("delta_supply"),
            "delta_backlog": r.get("delta_backlog"),
            "ok": r.get("ok"),
        }
        for r in boundary_top
    ]

    payload = {
        "schema_version": "recon-aggdet-1.0",
        "version_id": args.version_id,
        "cutover": {
            "cutover_date": args.cutover_date,
            "recon_window_days": args.recon_window_days,
            "anchor_policy": args.anchor_policy,
        },
        "inputs_summary": {
            "aggregate_rows": len(agg_rows),
            "det_rows": len(det_rows),
            "families": len(families),
            "periods": len(periods),
        },
        "tolerance": {"abs": args.tol_abs, "rel": args.tol_rel},
        "summary": {
            "rows": len(deltas),
            "tol_violations": tol_violations,
            "max_abs_delta": {k: _round6(v) for k, v in max_abs_delta.items()},
            "boundary": {
                "period": cutover_month,
                "violations": len(boundary_violations),
                "max_abs_delta": {k: _round6(v) for k, v in boundary_max_abs.items()},
                "top": boundary_top_view,
            },
        },
        "deltas": deltas,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()
