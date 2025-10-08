#!/usr/bin/env python3
"""
Anchor調整（v2最小）: anchor=DET_near 用の簡易再配分

目的:
- cutover月(YYYY-MM)の family×period 合計が AGG と一致するよう、DET(SKU×週)の
  demand/supply/backlog を微調整（総量保存の補正）。
- 近接のDETを保護する意図で、同period内の後半週に重みを置いて調整量を吸収（最小の実装）。

入出力:
- 入力: aggregate.json, sku_week.json
- 出力: sku_week_adjusted.json（雛形は元DETと同スキーマ、noteに調整情報を付与）

注意:
- 本スクリプトはv2ステップ2のオフライン検証用。MRP/reconcileは再計算しない。
- 期待形式の週キー: "YYYY-MM-WkX"。cutover月は '--cutover-date YYYY-MM-DD' から月部分を抽出する。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, DefaultDict

from core.plan_repository import PlanRepositoryError
from scripts.plan_pipeline_io import (
    resolve_storage_config,
    store_anchor_adjust_payload,
)


def _period_from_week(week_key: str) -> str:
    s = str(week_key)
    if len(s) >= 7 and s[4] == "-":
        return s[:7]
    return s


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _round6(x: float) -> float:
    try:
        return round(float(x), 6)
    except Exception:
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="anchor=DET_near の簡易再配分（v2最小）")
    ap.add_argument(
        "-i", "--inputs", nargs=2, required=True, help="aggregate.json と sku_week.json"
    )
    ap.add_argument("-o", "--output", required=True, help="調整後のDET JSON 出力パス")
    ap.add_argument(
        "--cutover-date",
        dest="cutover_date",
        required=True,
        help="境界日 YYYY-MM-DD（必須）",
    )
    ap.add_argument(
        "--anchor-policy",
        dest="anchor_policy",
        default="DET_near",
        help="anchorポリシー（既定: DET_near）",
    )
    ap.add_argument(
        "--recon-window-days",
        dest="recon_window_days",
        type=int,
        default=None,
        help="整合ウィンドウ日数（任意）",
    )
    ap.add_argument(
        "--weeks",
        dest="weeks_per_period",
        type=int,
        default=None,
        help="1期間の週数ヒント（任意）",
    )
    ap.add_argument(
        "--calendar-mode",
        dest="calendar_mode",
        default="simple",
        choices=["simple", "iso"],
        help="cutover週の推定モード",
    )
    ap.add_argument(
        "--max-adjust-ratio",
        dest="max_adjust_ratio",
        type=float,
        default=None,
        help="1行あたりの最大相対調整率（例: 0.2=±20%）。未指定で制限なし",
    )
    ap.add_argument(
        "--tol-abs",
        dest="tol_abs",
        type=float,
        default=0.0,
        help="(family,period)単位の調整スキップ閾値（絶対）。max(|Δ|)≤tolなら調整しない",
    )
    ap.add_argument(
        "--tol-rel",
        dest="tol_rel",
        type=float,
        default=0.0,
        help="(family,period)単位の調整スキップ閾値（相対）。|Δ|/max(|AGG|,|DET|,1)≤tolなら調整しない",
    )
    ap.add_argument(
        "--carryover",
        dest="carryover",
        default="none",
        choices=["none", "prev", "next", "auto", "both"],
        help="残差の隣接periodへの持ち越し方向",
    )
    ap.add_argument(
        "--carryover-split",
        dest="carryover_split",
        type=float,
        default=None,
        help="both/auto時のnext配分率（0..1）。未指定時はpolicy依存の既定(DET_near/blend=0.8, AGG_far=0.2)",
    )
    ap.add_argument(
        "-I",
        "--input-dir",
        dest="input_dir",
        default=None,
        help="入力CSVディレクトリ（capacity.csvを参照）",
    )
    ap.add_argument(
        "--capacity",
        dest="capacity_csv",
        default=None,
        help="capacity.csv のパス（任意）",
    )
    ap.add_argument(
        "--open-po", dest="open_po_csv", default=None, help="open_po.csv のパス（任意）"
    )
    ap.add_argument(
        "--headroom-inbound-weight",
        dest="headroom_inbound_weight",
        type=float,
        default=0.0,
        help="隣接period余地の入荷バイアス（0..1推奨）",
    )
    ap.add_argument(
        "--headroom-capacity-weight",
        dest="headroom_capacity_weight",
        type=float,
        default=0.5,
        help="隣接period余地の容量バイアス（0..1推奨）",
    )
    ap.add_argument(
        "--period-score",
        dest="period_score_csv",
        default=None,
        help="period別の追加スコアCSV（period,score）",
    )
    ap.add_argument(
        "--headroom-score-weight",
        dest="headroom_score_weight",
        type=float,
        default=0.0,
        help="追加スコアのバイアス係数（0..1推奨）",
    )
    ap.add_argument(
        "--pl-cost",
        dest="pl_cost_csv",
        default=None,
        help="period別のコストCSV（period,cost）",
    )
    ap.add_argument(
        "--headroom-cost-weight",
        dest="headroom_cost_weight",
        type=float,
        default=0.0,
        help="コストに対する抑制係数（0..1推奨）",
    )
    ap.add_argument(
        "--storage",
        dest="storage",
        choices=["db", "files", "both"],
        default=None,
        help="保存先: db/files/both（未指定は環境変数 PLAN_STORAGE_MODE）",
    )
    ap.add_argument(
        "--version-id",
        dest="version_id",
        default=None,
        help="PlanRepositoryへ書き込む版ID（storageにdbを含む場合は必須）",
    )
    args = ap.parse_args()

    storage_config, warning = resolve_storage_config(
        args.storage, args.version_id, cli_label="anchor_adjust"
    )
    if warning:
        print(warning, file=sys.stderr)

    agg = _load_json(args.inputs[0])
    det = _load_json(args.inputs[1])
    agg_rows: List[Dict[str, Any]] = agg.get("rows", [])
    det_rows: List[Dict[str, Any]] = det.get("rows", [])

    if not det_rows:
        # no-op
        wrote_db = store_anchor_adjust_payload(
            storage_config,
            adjusted_data=det,
            output_path=Path(args.output),
        )
        if storage_config.use_files:
            print(f"[ok] wrote {args.output} (no-op)")
        if wrote_db:
            print(
                "[ok] stored adjusted det rows in PlanRepository "
                f"version={storage_config.version_id}"
            )
        return

    # cutover month
    s = str(args.cutover_date)
    cutover_month = s[:7] if len(s) >= 7 and s[4] == "-" else s

    # AGG map: (family, period) -> metrics
    agg_map: Dict[Tuple[str, str], Dict[str, float]] = {}
    for r in agg_rows:
        fam = str(r.get("family"))
        per = str(r.get("period"))
        agg_map[(fam, per)] = {
            "demand": float(r.get("demand", 0) or 0),
            "supply": float(r.get("supply", 0) or 0),
            "backlog": float(r.get("backlog", 0) or 0),
        }

    # DET grouping for target/all periods
    from collections import defaultdict as _dd

    by_fp_weeks: DefaultDict[Tuple[str, str], List[Dict[str, Any]]] = _dd(list)
    by_fp_all: DefaultDict[Tuple[str, str], List[Dict[str, Any]]] = _dd(list)
    for r in det_rows:
        fam = str(r.get("family") or r.get("item") or "")
        wk = str(r.get("week") or "")
        if not fam or not wk:
            continue
        per = (
            str(r.get("period"))
            if r.get("period") is not None
            else _period_from_week(wk)
        )
        if per == cutover_month:
            by_fp_weeks[(fam, per)].append(r)
        by_fp_all[(fam, per)].append(r)

    import re as _re

    def _period_add_generic(per: str, step: int) -> str | None:
        try:
            # ISO週 'YYYY-Www'
            if _re.match(r"^\d{4}-W\d{1,2}$", per):
                import datetime as _dt

                y = int(per[:4])
                w = int(per.split("W")[-1])
                d0 = _dt.date.fromisocalendar(y, w, 1)
                d1 = d0 + _dt.timedelta(weeks=step)
                iso = d1.isocalendar()
                return f"{iso.year:04d}-W{iso.week:02d}"
            # 月 'YYYY-MM'
            y, m = int(per[:4]), int(per[5:7])
            m2 = m + step
            y2 = y + (m2 - 1) // 12
            m2 = (m2 - 1) % 12 + 1
            return f"{y2:04d}-{m2:02d}"
        except Exception:
            return None

    def _indices_for_rows(rows_in: List[Dict[str, Any]]) -> List[int]:
        idxs: List[int] = []
        for rr in rows_in:
            try:
                i = det_rows_out.index(rr)
            except ValueError:
                fam = rr.get("family") or rr.get("item")
                sku = rr.get("sku")
                wk = rr.get("week")
                i = next(
                    (
                        k
                        for k, rec in enumerate(det_rows_out)
                        if (
                            (rec.get("family") or rec.get("item")) == fam
                            and rec.get("sku") == sku
                            and rec.get("week") == wk
                        )
                    ),
                    -1,
                )
            if i >= 0:
                idxs.append(i)
        return idxs

    def _sum_metrics(rows_in: List[Dict[str, Any]]) -> Dict[str, float]:
        s = {"demand": 0.0, "supply": 0.0, "backlog": 0.0}
        for r in rows_in:
            for m in s.keys():
                try:
                    s[m] += float(r.get(m, 0) or 0)
                except Exception:
                    pass
        return s

    # capacity.csv のperiod容量（総量）を取得（任意）
    def _load_capacity_map(
        input_dir: str | None, path: str | None
    ) -> Tuple[Dict[str, float], float]:
        cap: Dict[str, float] = {}
        maxcap = 0.0
        p = path or (f"{input_dir}/capacity.csv" if input_dir else None)
        if p:
            try:
                with open(p, newline="", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    for row in r:
                        per = str(row.get("period"))
                        try:
                            v = float(row.get("capacity", 0) or 0)
                        except Exception:
                            v = 0.0
                        cap[per] = cap.get(per, 0.0) + v
                if cap:
                    maxcap = max(cap.values()) if cap else 0.0
            except Exception:
                cap, maxcap = {}, 0.0
        return cap, maxcap

    cap_map, cap_max = _load_capacity_map(args.input_dir, args.capacity_csv)

    # open_po.csv 入荷量（期別合算）をロード
    def _load_inbound_map(
        input_dir: str | None, path: str | None
    ) -> Tuple[Dict[str, float], float]:
        inbound: Dict[str, float] = {}
        maxin = 0.0
        p = path or (f"{input_dir}/open_po.csv" if input_dir else None)
        if p:
            try:
                with open(p, newline="", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    for row in r:
                        due = str(row.get("due") or "")
                        if len(due) >= 7 and due[4] == "-":
                            per = due[:7]
                        else:
                            per = due
                        try:
                            q = float(row.get("qty", 0) or 0)
                        except Exception:
                            q = 0.0
                        inbound[per] = inbound.get(per, 0.0) + q
                if inbound:
                    maxin = max(inbound.values())
            except Exception:
                inbound, maxin = {}, 0.0
        return inbound, maxin

    inb_map, inb_max = _load_inbound_map(args.input_dir, args.open_po_csv)

    # periodスコア/コストの読み込み（任意）
    def _load_period_value_map(
        path: str | None, input_dir: str | None, fname: str, col: str
    ) -> Tuple[Dict[str, float], float]:
        m: Dict[str, float] = {}
        mx = 0.0
        p = path or (f"{input_dir}/{fname}" if input_dir else None)
        if p:
            try:
                with open(p, newline="", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    for row in r:
                        per = str(row.get("period") or "")
                        try:
                            v = float(row.get(col, 0) or 0)
                        except Exception:
                            v = 0.0
                        m[per] = v
                if m:
                    mx = max(abs(v) for v in m.values())
            except Exception:
                m, mx = {}, 0.0
        return m, mx

    ps_map, ps_max = _load_period_value_map(
        args.period_score_csv, args.input_dir, "period_score.csv", "score"
    )
    cost_map, cost_max = _load_period_value_map(
        args.pl_cost_csv, args.input_dir, "period_cost.csv", "cost"
    )

    def _cap_norm(per: str) -> float:
        try:
            if cap_map and per in cap_map and cap_max > 0:
                return max(0.0, cap_map.get(per, 0.0) / cap_max)
        except Exception:
            pass
        return 0.0

    def _headroom_for_period(fam: str, per: str, resid_map: Dict[str, float]) -> float:
        # 近傍periodの(目標-target vs 現状-cur)から、residの符号に沿った吸収余地の総量を推定
        try:
            target = agg_map.get((fam, per)) or {
                "demand": 0.0,
                "supply": 0.0,
                "backlog": 0.0,
            }
            cur = _sum_metrics(by_fp_all.get((fam, per)) or [])
            total = 0.0
            for m, resid in resid_map.items():
                try:
                    diff = float(target.get(m, 0) or 0) - float(cur.get(m, 0) or 0)
                    # resid>0: 増やしたい → diff>0 が余地、 resid<0: 減らしたい → (-diff)>0 が余地
                    cap = diff if resid > 0 else (-diff)
                    if cap > 0:
                        total += cap
                except Exception:
                    continue
            # capacityバイアス（0..1の比重で余地に加点）
            try:
                if (
                    cap_map
                    and per in cap_map
                    and cap_max > 0
                    and args.headroom_capacity_weight
                ):
                    norm = _cap_norm(per)
                    total *= 1.0 + max(0.0, float(args.headroom_capacity_weight)) * norm
                if (
                    inb_map
                    and per in inb_map
                    and inb_max > 0
                    and args.headroom_inbound_weight
                ):
                    inb_norm = max(0.0, inb_map.get(per, 0.0) / inb_max)
                    total *= (
                        1.0 + max(0.0, float(args.headroom_inbound_weight)) * inb_norm
                    )
                if (
                    ps_map
                    and per in ps_map
                    and ps_max > 0
                    and args.headroom_score_weight
                ):
                    sc_norm = max(0.0, ps_map.get(per, 0.0) / ps_max)
                    total *= 1.0 + max(0.0, float(args.headroom_score_weight)) * sc_norm
                if (
                    cost_map
                    and per in cost_map
                    and cost_max > 0
                    and args.headroom_cost_weight
                ):
                    # コストが高いほど抑制（1/(1+k*norm)）
                    c_norm = max(0.0, cost_map.get(per, 0.0) / cost_max)
                    total /= 1.0 + max(0.0, float(args.headroom_cost_weight)) * c_norm
            except Exception:
                pass
            return total
        except Exception:
            return 0.0

    # Adjust per (family, period)
    adjusted_rows: List[Dict[str, Any]] = []
    det_rows_out: List[Dict[str, Any]] = []
    carryover_logs: List[Dict[str, Any]] = []
    metrics = ("demand", "supply", "backlog")
    for r in det_rows:
        det_rows_out.append(dict(r))

    for (fam, per), rows in by_fp_weeks.items():
        target = agg_map.get((fam, per))
        if not target:
            continue
        # current sums
        cur = {m: 0.0 for m in metrics}
        for rr in rows:
            for m in metrics:
                cur[m] += float(rr.get(m, 0) or 0)
        # deltas to apply to DET (so that DET == AGG)
        delta = {m: target[m] - cur[m] for m in metrics}
        # スキップ判定（abs/relのいずれかを満たす指標が全て）。
        # 相対判定の分母は demand/supply の代表値を使用（backlogが小さい場合の過大判定を避ける）。
        if args.tol_abs or args.tol_rel:
            base_denom = max(
                abs(float(target.get("demand", 0) or 0)),
                abs(float(cur.get("demand", 0) or 0)),
                abs(float(target.get("supply", 0) or 0)),
                abs(float(cur.get("supply", 0) or 0)),
                1.0,
            )
            all_ok = True
            for m in metrics:
                av = float(target[m])
                dv = float(cur[m])
                d = float(delta[m])
                # backlog などの小さな値に引きずられないよう、共通の base_denom を使用
                ok = (abs(d) <= float(args.tol_abs or 0.0)) or (
                    (abs(d) / base_denom) <= float(args.tol_rel or 0.0)
                )
                if not ok:
                    all_ok = False
                    break
            if all_ok:
                continue
        # Weights: later weeks get higher weights to protect near-boundary DET (簡易)
        # Extract rows indices in OUT list to update in-place
        idxs = []
        for rr in rows:
            try:
                i = det_rows_out.index(
                    rr
                )  # rely on object identity; fallback if needed
            except ValueError:
                # find by matching a few keys
                i = next(
                    (
                        k
                        for k, rec in enumerate(det_rows_out)
                        if rec is rr
                        or (
                            rec.get("family") == rr.get("family")
                            and rec.get("sku") == rr.get("sku")
                            and rec.get("week") == rr.get("week")
                        )
                    ),
                    -1,
                )
            if i >= 0:
                idxs.append(i)
        # sort rows by week increasing -> assign larger weight depending on policy
        idxs_sorted = sorted(idxs, key=lambda i: str(det_rows_out[i].get("week")))
        weeks_labels = [str(det_rows_out[i].get("week")) for i in idxs_sorted]

        # 推定: cutover週インデックス（0..n-1）
        # 1) ラベル '...-WkX' を優先
        def _parse_wk(s: str) -> int | None:
            try:
                if "Wk" in s:
                    p = s.split("Wk")[-1]
                    return int("".join([ch for ch in p if ch.isdigit()]))
            except Exception:
                return None
            return None

        label_wk_nums = [(_parse_wk(s) or (i + 1)) for i, s in enumerate(weeks_labels)]
        # 2) cutover日から週番号推定
        cutover_week_num_est = None
        try:
            parts = str(args.cutover_date).split("-")
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            import calendar as _cal

            _, mdays = _cal.monthrange(y, m)  # mdays in month
            if args.calendar_mode == "iso":
                # 月内の位置割合で週位置を推定（n本の離散点へ丸め）
                frac = max(0.0, min(1.0, (d - 1) / max(1, mdays - 1)))
                cutover_week_num_est = (
                    int(round(frac * max(0, len(label_wk_nums) - 1))) + 1
                )
            else:
                cutover_week_num_est = max(1, min(len(label_wk_nums), (d + 6) // 7))
        except Exception:
            cutover_week_num_est = None
        # 3) 最終的な中心位置 cpos
        if cutover_week_num_est in label_wk_nums:
            cpos = label_wk_nums.index(cutover_week_num_est)
        else:
            # 近い番号に丸め
            if cutover_week_num_est is not None:
                diffs = [abs(x - cutover_week_num_est) for x in label_wk_nums]
                cpos = int(diffs.index(min(diffs)))
            else:
                cpos = max(0, (len(idxs_sorted) - 1) // 2)
        n = len(idxs_sorted)
        if n <= 0:
            continue
        policy = (args.anchor_policy or "DET_near").upper()
        # base sequences
        asc = [i + 1 for i in range(n)]  # 1..n
        desc = list(reversed(asc))  # n..1
        tri = [min(i + 1, n - i) for i in range(n)]  # 1..2..mid..2..1

        weights: List[int]
        if policy == "DET_NEAR":
            # 後半週で吸収（近接DETを守る）
            weights = asc
            if args.recon_window_days is not None:
                nw = max(1, min(n, (args.recon_window_days + 6) // 7))
                pad = n - nw
                weights = [0] * pad + [i + 1 for i in range(nw)]
        elif policy == "AGG_FAR":
            # 前半週で吸収（先々AGGを固定、DET側を調整）
            weights = desc
            if args.recon_window_days is not None:
                nw = max(1, min(n, (args.recon_window_days + 6) // 7))
                pad = n - nw
                weights = [i + 1 for i in range(nw)] + [0] * pad
        else:  # BLEND（その他はblend扱い）
            # 中心（cutover週に近い位置）に三角重み。window指定時は中心±半径内に限定。
            if args.recon_window_days is not None:
                nw = max(1, min(n, (args.recon_window_days + 6) // 7))
                r = max(0, (nw - 1) // 2)
                weights = [max(0, r - abs(j - cpos) + 1) for j in range(n)]
            else:
                # 全域三角（中心に向けて増加、遠ざかると減少）
                weights = [max(1, (n - abs(j - cpos))) for j in range(n)]
        # 正規化のための合計
        wsum = float(sum(weights))
        if wsum <= 0:
            weights = [1] * n
            wsum = float(n)
        # apply per metric（2パス: 重み按分 → ガードによる不足分をヘッドルームに再配分）
        # 初回適用の加算量を記録
        applied: Dict[str, List[float]] = {m: [0.0] * n for m in metrics}
        limits: Dict[str, List[float]] = {m: [float("inf")] * n for m in metrics}
        for j, i in enumerate(idxs_sorted):
            w = weights[j] / wsum
            rec = det_rows_out[i]
            for m in metrics:
                base = float(rec.get(m, 0) or 0)
                add = w * delta[m]
                lim = float("inf")
                if args.max_adjust_ratio is not None:
                    lim = abs(base) * float(args.max_adjust_ratio)
                    if lim <= 0:
                        lim = abs(delta[m])  # 0ベースは制限緩和（総量達成優先）
                    add = max(-lim, min(lim, add))
                rec[m] = base + add
                applied[m][j] = add
                limits[m][j] = lim
            adjusted_rows.append(rec)
        # 2パス目: 残差再配分
        residual_after_period: Dict[str, float] = {}
        for m in metrics:
            # 現在の合計加算
            cur_add_sum = sum(applied[m])
            target = float(delta[m])
            resid = target - cur_add_sum
            eps = 1e-9
            if abs(resid) <= eps:
                # 端数だけ丸め
                for j, i in enumerate(idxs_sorted):
                    rec = det_rows_out[i]
                    rec[m] = _round6(float(rec.get(m, 0) or 0))
                residual_after_period[m] = 0.0
                continue
            s = 1.0 if resid > 0 else -1.0
            # 各行のヘッドルーム（指定方向）
            head = []  # (j, cap)
            for j, i in enumerate(idxs_sorted):
                cap = float("inf")
                if args.max_adjust_ratio is not None:
                    net = applied[m][j]
                    lim = limits[m][j]
                    if lim != float("inf"):
                        cap = max(0.0, lim - s * net)
                else:
                    cap = float("inf")
                head.append((j, cap))
            # 有限capのみ対象
            finite = [(j, c) for j, c in head if c != float("inf") and c > eps]
            infs = [j for j, c in head if c == float("inf")]
            if finite:
                total_cap = sum(c for _, c in finite)
                for j, cap in finite:
                    share = cap / total_cap if total_cap > eps else 0.0
                    add_extra = share * resid
                    applied[m][j] += add_extra
                    # 反映
                    i = idxs_sorted[j]
                    rec = det_rows_out[i]
                    rec[m] = float(rec.get(m, 0) or 0) + add_extra
            elif infs:
                # 制限なしの行があれば均等配分
                k = len(infs)
                for j in infs:
                    add_extra = resid / k
                    applied[m][j] += add_extra
                    i = idxs_sorted[j]
                    rec = det_rows_out[i]
                    rec[m] = float(rec.get(m, 0) or 0) + add_extra
            else:
                # 全く余地がない
                residual_after_period[m] = resid
            # 丸め
            for j, i in enumerate(idxs_sorted):
                rec = det_rows_out[i]
                rec[m] = _round6(float(rec.get(m, 0) or 0))
            if m not in residual_after_period:
                # 再計算した残差
                cur_sum2 = sum(applied[m])
                residual_after_period[m] = float(delta[m]) - cur_sum2

        # 残差の隣接periodへの持ち越し
        if args.carryover and args.carryover.lower() != "none":
            dir_choice = args.carryover.lower()

            def apply_to_neighbor(
                per2: str | None, resid_map: Dict[str, float]
            ) -> Dict[str, float]:
                applied_map: Dict[str, float] = {m: 0.0 for m in metrics}
                if not per2 or (fam, per2) not in by_fp_all:
                    return applied_map
                rows2 = by_fp_all[(fam, per2)]
                idxs2 = _indices_for_rows(rows2)
                if not idxs2:
                    return applied_map
                n2 = len(idxs2)
                weights2 = [1] * n2
                wsum2 = float(sum(weights2))
                for m in metrics:
                    resid2 = float((resid_map.get(m) or 0.0))
                    if abs(resid2) <= 1e-9:
                        continue
                    applied2 = [0.0] * n2
                    limits2 = [float("inf")] * n2
                    # 1パス
                    for j, i2 in enumerate(idxs2):
                        rec2 = det_rows_out[i2]
                        base2 = float(rec2.get(m, 0) or 0)
                        add2 = (weights2[j] / wsum2) * resid2
                        lim2 = float("inf")
                        if args.max_adjust_ratio is not None:
                            lim2 = abs(base2) * float(args.max_adjust_ratio)
                            if lim2 <= 0:
                                lim2 = abs(resid2)
                            add2 = max(-lim2, min(lim2, add2))
                        rec2[m] = base2 + add2
                        applied2[j] = add2
                        limits2[j] = lim2
                    # 2パス
                    cur_add2 = sum(applied2)
                    resid_left = resid2 - cur_add2
                    s2 = 1.0 if resid_left > 0 else -1.0
                    head2 = []
                    for j, i2 in enumerate(idxs2):
                        cap2 = float("inf")
                        if args.max_adjust_ratio is not None:
                            net2 = applied2[j]
                            lim2 = limits2[j]
                            if lim2 != float("inf"):
                                cap2 = max(0.0, lim2 - s2 * net2)
                        head2.append((j, cap2))
                    finite2 = [
                        (j, c) for j, c in head2 if c != float("inf") and c > 1e-9
                    ]
                    if finite2:
                        total_cap2 = sum(c for _, c in finite2)
                        for j, cap in finite2:
                            share = cap / total_cap2 if total_cap2 > 1e-9 else 0.0
                            add_extra2 = share * resid_left
                            i2 = idxs2[j]
                            rec2 = det_rows_out[i2]
                            rec2[m] = float(rec2.get(m, 0) or 0) + add_extra2
                    # 丸め
                    for j, i2 in enumerate(idxs2):
                        rec2 = det_rows_out[i2]
                        rec2[m] = _round6(float(rec2.get(m, 0) or 0))
                    applied_map[m] = _round6(resid2)
                return applied_map

            if dir_choice in ("prev", "next", "auto"):
                if dir_choice == "prev":
                    step = -1
                elif dir_choice == "next":
                    step = 1
                else:
                    # auto: 余地の大きい隣接periodを選ぶ（同等ならpolicy既定）
                    prev_per = _period_add_generic(per, -1)
                    next_per = _period_add_generic(per, 1)
                    h_prev = (
                        _headroom_for_period(fam, prev_per, residual_after_period)
                        if prev_per
                        else 0.0
                    )
                    h_next = (
                        _headroom_for_period(fam, next_per, residual_after_period)
                        if next_per
                        else 0.0
                    )
                    if h_prev == 0.0 and h_next == 0.0:
                        step = 1 if policy in ("DET_NEAR", "BLEND") else -1
                    else:
                        step = 1 if h_next >= h_prev else -1
                per2 = _period_add_generic(per, step)
                applied_map = apply_to_neighbor(per2, residual_after_period)
                if per2:
                    log = {
                        "family": fam,
                        "from_period": per,
                        "to_period": per2,
                        "metrics": applied_map,
                    }
                    # 追加ログ: 余地/容量正規化
                    try:
                        if dir_choice == "auto":
                            log.update(
                                {
                                    "headroom_prev": (
                                        round(h_prev, 6)
                                        if "h_prev" in locals()
                                        else None
                                    ),
                                    "headroom_next": (
                                        round(h_next, 6)
                                        if "h_next" in locals()
                                        else None
                                    ),
                                    "cap_norm_prev": (
                                        round(_cap_norm(prev_per), 6)
                                        if prev_per
                                        else None
                                    ),
                                    "cap_norm_next": (
                                        round(_cap_norm(next_per), 6)
                                        if next_per
                                        else None
                                    ),
                                }
                            )
                    except Exception:
                        pass
                    carryover_logs.append(log)
            elif dir_choice == "both":
                per_prev = _period_add_generic(per, -1)
                per_next = _period_add_generic(per, 1)
                # ポリシー依存の既定split or 明示split
                if args.carryover_split is not None:
                    next_ratio = max(0.0, min(1.0, float(args.carryover_split)))
                else:
                    next_ratio = 0.8 if policy in ("DET_NEAR", "BLEND") else 0.2
                prev_ratio = 1.0 - next_ratio
                prev_map = {
                    m: (residual_after_period.get(m) or 0.0) * prev_ratio
                    for m in metrics
                }
                next_map = {
                    m: (residual_after_period.get(m) or 0.0) * next_ratio
                    for m in metrics
                }
                app_prev = apply_to_neighbor(per_prev, prev_map)
                app_next = apply_to_neighbor(per_next, next_map)
                if per_prev:
                    carryover_logs.append(
                        {
                            "family": fam,
                            "from_period": per,
                            "to_period": per_prev,
                            "metrics": app_prev,
                            "cap_norm": (
                                round(_cap_norm(per_prev), 6) if per_prev else None
                            ),
                        }
                    )
                if per_next:
                    carryover_logs.append(
                        {
                            "family": fam,
                            "from_period": per,
                            "to_period": per_next,
                            "metrics": app_next,
                            "cap_norm": (
                                round(_cap_norm(per_next), 6) if per_next else None
                            ),
                        }
                    )

    # carryoverサマリ（noteへ要約文字列、詳細はcarryover_summary）
    moved_prev = sum(
        1
        for r in (carryover_logs or [])
        if str(r.get("to_period", "")) < str(r.get("from_period", ""))
    )
    moved_next = sum(
        1
        for r in (carryover_logs or [])
        if str(r.get("to_period", "")) > str(r.get("from_period", ""))
    )
    moved_total = len(carryover_logs or [])
    note_parts = [
        "v2 anchor調整: cutover月のDETを重み付けで調整",
        f"carryover={moved_total} (prev={moved_prev}, next={moved_next})",
    ]
    if args.carryover_split is not None:
        note_parts.append(f"split(next)={float(args.carryover_split):.2f}")
    if args.headroom_capacity_weight:
        note_parts.append(f"cap_w={float(args.headroom_capacity_weight):.2f}")
    payload = {
        "schema_version": det.get("schema_version", "agg-1.0"),
        "note": "; ".join(note_parts),
        "inputs_summary": det.get("inputs_summary", {}),
        "cutover": {
            "cutover_date": args.cutover_date,
            "anchor_policy": args.anchor_policy,
            "recon_window_days": args.recon_window_days,
        },
        "rows": det_rows_out,
        "carryover": carryover_logs if "carryover_logs" in locals() else [],
        "carryover_summary": {
            "count": moved_total,
            "prev": moved_prev,
            "next": moved_next,
            "carryover_split_next": args.carryover_split,
            "headroom_capacity_weight": args.headroom_capacity_weight,
        },
    }
    try:
        wrote_db = store_anchor_adjust_payload(
            storage_config,
            adjusted_data=payload,
            output_path=Path(args.output),
        )
    except PlanRepositoryError as exc:
        print(f"[error] PlanRepository書き込みに失敗しました: {exc}", file=sys.stderr)
        sys.exit(1)

    if storage_config.use_files:
        print(f"[ok] wrote {args.output}")
    if wrote_db:
        print(
            "[ok] stored adjusted det rows in PlanRepository "
            f"version={storage_config.version_id}"
        )


if __name__ == "__main__":
    main()
