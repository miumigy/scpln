#!/usr/bin/env python3
"""
製販物整合（PR5, CRPライト）: 計画解放（planned_order_release）を週次能力に合わせて調整。

機能（v0）
- 入力: allocate（SKU×週）と mrp（item×週）を受け取り、FG（mix_shareにあるSKU）を能力制約で調整
- 能力: capacity.csv（月次, workcenter）を週等分して適用（単一WCを総量として扱うv0）
- 調整: 週順に処理し、前週の余剰能力を繰越して前倒し、超過分は次週へ繰越（スピル）
- 出力: mrp行に `planned_order_release_adj` を付与。週別サマリ（load/capacity/adjusted/spill）を付加

使い方:
  python scripts/reconcile.py -i out/sku_week.json out/mrp.json -I samples/planning -o out/plan_final.json --weeks 4 --round int
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import DefaultDict, Dict, Any, List, Tuple, Optional

from core.plan_repository import PlanRepositoryError
from scripts.plan_pipeline_io import (
    resolve_storage_config,
    store_plan_final_payload,
)
from scripts.calendar_utils import (
    build_calendar_lookup,
    get_week_distribution,
    load_planning_calendar,
    ordered_weeks,
    resolve_period_for_week,
    PlanningCalendarLookup,
)


def _read_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_mix(input_dir: str | None, mix_path: str | None) -> List[str]:
    path = mix_path or (os.path.join(input_dir, "mix_share.csv") if input_dir else None)
    skus: List[str] = []
    if path and os.path.exists(path):
        rows = _read_csv(path)
        for r in rows:
            sku = str(r.get("sku"))
            if sku and sku not in skus:
                skus.append(sku)
    return skus


def _resolve_calendar_lookup(
    calendar_path: Optional[str], input_dir: Optional[str]
) -> Optional[PlanningCalendarLookup]:
    """planning_calendar.json を探索して LookUp を返す。"""

    spec = None
    err: Optional[Exception] = None
    if calendar_path:
        try:
            spec = load_planning_calendar(calendar_path)
        except Exception as exc:
            err = exc
    if spec is None and input_dir:
        candidate = os.path.join(input_dir, "planning_calendar.json")
        if os.path.exists(candidate):
            try:
                spec = load_planning_calendar(candidate)
            except Exception as exc:
                err = exc
    if err:
        print(
            f"[error] planning_calendar の読み込みに失敗しました: {err}",
            file=sys.stderr,
        )
        sys.exit(1)
    if spec is None:
        return None
    return build_calendar_lookup(spec)


def _round_quantity(value: Any, *, mode: str = "int") -> float | int:
    """数量の丸め。modeに応じて整数/小数桁を揃える。"""
    try:
        v = float(value)
    except Exception:
        v = 0.0
    if mode == "none":
        return round(v, 6)
    if mode == "int":
        return int(round(v))
    if mode.startswith("dec"):
        try:
            d = int(mode[3:])
        except Exception:
            d = 2
        return round(v, max(0, d))
    return round(v, 6)


def _weeks_from(
    alloc: Dict[str, Any],
    mrp: Dict[str, Any],
    lookup: Optional[PlanningCalendarLookup],
) -> List[str]:
    seen = []
    for rec in alloc.get("rows", []):
        w = str(rec.get("week"))
        if w and w not in seen:
            seen.append(w)
    for rec in mrp.get("rows", []):
        w = str(rec.get("week"))
        if w and w not in seen:
            seen.append(w)
    return ordered_weeks(seen, lookup)


def _weekly_capacity(
    input_dir: str | None,
    capacity_path: str | None,
    *,
    weeks_per_period: int,
    weeks: List[str],
    lookup: Optional[PlanningCalendarLookup],
) -> Dict[str, float]:
    path = capacity_path or (
        os.path.join(input_dir, "capacity.csv") if input_dir else None
    )
    cap_by_period: DefaultDict[str, float] = __import__("collections").defaultdict(
        float
    )
    if path and os.path.exists(path):
        for r in _read_csv(path):
            per = str(r.get("period"))
            try:
                c = float(r.get("capacity", 0) or 0)
            except Exception:
                c = 0.0
            cap_by_period[per] += c  # 複数WCは合算
    # 週へ展開（カレンダー準拠。未定義は等分）
    out: Dict[str, float] = {}
    fallback_weeks = max(1, weeks_per_period)
    for period, monthly in cap_by_period.items():
        dist = get_week_distribution(period, lookup, fallback_weeks)
        ratios = [max(0.0, entry.ratio) for entry in dist]
        total = sum(ratios)
        if total <= 0 and dist:
            ratios = [1.0 / len(dist)] * len(dist)
        elif total > 0:
            ratios = [r / total for r in ratios]
        for idx, entry in enumerate(dist):
            wk = entry.week_code
            out[wk] = out.get(wk, 0.0) + monthly * ratios[idx]
    # weeks に存在しない週は 0 扱い
    for wk in weeks:
        out.setdefault(wk, 0.0)
    return out


def _adjust_by_capacity(
    weeks: List[str], load_by_week: Dict[str, float], cap_by_week: Dict[str, float]
) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    adj: Dict[str, float] = {}
    report: List[Dict[str, Any]] = []
    slack_carry = 0.0
    spill_next = 0.0
    for w in weeks:
        cap = float(cap_by_week.get(w, 0.0))
        demand = float(load_by_week.get(w, 0.0)) + spill_next
        effective = cap + slack_carry
        if demand <= effective:
            adj[w] = demand
            slack_carry = effective - demand
            spill_made = 0.0
        else:
            adj[w] = effective
            spill_made = demand - effective
            slack_carry = 0.0
        spill_next = spill_made
        report.append(
            {
                "week": w,
                "capacity": cap,
                "original_load": float(load_by_week.get(w, 0.0)),
                "carried_slack_in": round(effective - cap, 6),
                "spill_in": round(demand - float(load_by_week.get(w, 0.0)), 6),
                "adjusted_load": adj[w],
                "spill_out": spill_made,
                "slack_carry_out": slack_carry,
            }
        )
    return adj, report


def _adjust_segment(
    weeks: List[str],
    load_by_week: Dict[str, float],
    cap_by_week: Dict[str, float],
    *,
    start_slack: float = 0.0,
    start_spill: float = 0.0,
    mode: str = "forward",
) -> Tuple[Dict[str, float], List[Dict[str, Any]], float, float]:
    """区間調整: 週リストを与えて能力調整を行う。

    mode:
      - "forward": 既存と同じ（スピルは次週へ、スラックは次週へ）。
      - "det_near": カットオーバー月の最小実装。スピルは区間外へ（次期）送り、区間内には持ち込まない。
      - "agg_far": det_near と同等に区間外へ吐き出す（呼び出し側で pre へ戻す想定）。
      - "blend": det_near と同等（吐き出し量を呼び出し側で pre/post に分割）。
    戻り値:
      (adj_by_week, report, end_slack, end_spill)
    """
    adj: Dict[str, float] = {}
    report: List[Dict[str, Any]] = []
    slack_carry = float(start_slack or 0.0)
    spill_next = float(start_spill or 0.0)
    spill_out_segment = 0.0
    for i, w in enumerate(weeks):
        cap = float(cap_by_week.get(w, 0.0))
        base = float(load_by_week.get(w, 0.0))
        # 受入スピルの取り扱い
        demand = base + spill_next
        effective = cap + slack_carry
        if demand <= effective:
            adj[w] = demand
            slack_carry = effective - demand
            spill_made = 0.0
        else:
            adj[w] = effective
            spill_made = demand - effective
            slack_carry = 0.0
        # spillの伝播
        if mode in ("det_near", "agg_far", "blend"):
            # 区間内には持ち込まず、区間外へ送る（後続セグメントへ）
            spill_out_segment += spill_made
            spill_next = 0.0
        else:
            spill_next = spill_made
        report.append(
            {
                "week": w,
                "capacity": cap,
                "original_load": base,
                "carried_slack_in": round(effective - cap, 6),
                "spill_in": round(demand - base, 6),
                "adjusted_load": adj[w],
                "spill_out": spill_made,
                "slack_carry_out": slack_carry,
            }
        )
    # forward: 区間末のspill_nextがそのまま end_spill
    # det_near: 区間末のspill_nextは常に0。spill_out_segmentが end_spill
    end_spill = spill_next if mode == "forward" else spill_out_segment
    return adj, report, slack_carry, end_spill


def main() -> None:
    ap = argparse.ArgumentParser(description="製販物整合（CRPライト）")
    ap.add_argument(
        "-i",
        "--inputs",
        nargs=2,
        required=True,
        help="allocate.json と mrp.json のパス（順不同可）",
    )
    ap.add_argument("-o", "--output", required=True, help="整合後の計画JSON")
    ap.add_argument(
        "-I",
        "--input-dir",
        dest="input_dir",
        default=None,
        help="CSVフォルダ（capacity.csv, mix_share.csv）",
    )
    ap.add_argument("--capacity", dest="capacity", default=None, help="capacity.csv")
    ap.add_argument("--mix", dest="mix", default=None, help="mix_share.csv（FG判定）")
    ap.add_argument(
        "--weeks", dest="weeks_per_period", type=int, default=4, help="1期間の週数"
    )
    ap.add_argument(
        "--round",
        dest="round_mode",
        default="int",
        choices=["none", "int", "dec1", "dec2"],
        help="FG解放調整後の丸めモード（既定:int）",
    )
    ap.add_argument(
        "--calendar",
        dest="calendar",
        default=None,
        help="PlanningカレンダーJSONのパス（未指定時は input_dir から探索）",
    )
    # v2 入口（受け口のみ。ロジックへの反映は今後のPR）
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
    ap.add_argument(
        "--blend-split-next",
        dest="blend_split_next",
        type=float,
        default=None,
        help="anchor=blend時のpost配分率(0..1)。未指定時は週別スピル×重みから動的算定",
    )
    ap.add_argument(
        "--blend-weight-mode",
        dest="blend_weight_mode",
        choices=["tri", "lin", "quad"],
        default="tri",
        help="blend時の重み関数: tri=三角, lin=線形, quad=二次（近接を強調）",
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

    # 入力を識別
    with open(args.inputs[0], encoding="utf-8") as f:
        a0 = json.load(f)
    with open(args.inputs[1], encoding="utf-8") as f:
        a1 = json.load(f)
    if "sku" in json.dumps(a0.get("rows", [])[:1]):
        alloc, mrp = a0, a1
    else:
        alloc, mrp = a1, a0

    lookup = _resolve_calendar_lookup(args.calendar, args.input_dir)
    weeks = _weeks_from(alloc, mrp, lookup)
    week_index = {w: i for i, w in enumerate(weeks)}
    calendar_mode = "fallback_weeks"
    if lookup:
        calendar_mode = lookup.spec.calendar_type or "custom"
    fg_skus = set(_load_mix(args.input_dir, args.mix))
    cap_w = _weekly_capacity(
        args.input_dir,
        args.capacity,
        weeks_per_period=args.weeks_per_period,
        weeks=weeks,
        lookup=lookup,
    )

    # 週別のFG解放ロード
    load_by_week: DefaultDict[str, float] = __import__("collections").defaultdict(float)
    for r in mrp.get("rows", []):
        it = str(r.get("item"))
        if it not in fg_skus:
            continue
        w = str(r.get("week"))
        por = float(r.get("planned_order_release", 0) or 0)
        load_by_week[w] += por

    # v2: anchor_policy DET_near の最小実装（区間分割）
    use_v2 = bool(args.anchor_policy) and str(args.anchor_policy).upper() in (
        "DET_NEAR",
        "DET-NEAR",
    )
    # 週配列を pre / at / post に分割
    adj_by_week: Dict[str, float] = {}
    week_report: List[Dict[str, Any]] = []
    cutover_month = None
    if args.cutover_date:
        s = str(args.cutover_date)
        if len(s) >= 7 and s[4] == "-":
            cutover_month = s[:7]
    period_by_week: Dict[str, str] = {}
    for w in weeks:
        per = resolve_period_for_week(w, lookup)
        if not per:
            s = str(w)
            if len(s) >= 7 and s[4] == "-":
                per = s[:7]
            elif "-W" in s:
                per = s.split("-W", 1)[0]
        period_by_week[w] = per

    if use_v2 and cutover_month:
        pre_weeks = [w for w in weeks if period_by_week.get(w) < cutover_month]
        at_weeks = [w for w in weeks if period_by_week.get(w) == cutover_month]
        post_weeks = [w for w in weeks if period_by_week.get(w) > cutover_month]
        pol = str(args.anchor_policy).upper()
        if pol in ("DET_NEAR", "DET-NEAR"):
            # 1) pre: 通常前進
            pre_adj, pre_rep, pre_slack, pre_spill = _adjust_segment(
                pre_weeks,
                load_by_week,
                cap_w,
                start_slack=0.0,
                start_spill=0.0,
                mode="forward",
            )
            # 2) at: det_near（スピルは区間外へ=postへ）
            at_adj, at_rep, at_slack, at_spill_to_post = _adjust_segment(
                at_weeks,
                load_by_week,
                cap_w,
                start_slack=pre_slack,
                start_spill=pre_spill,
                mode="det_near",
            )
            # 3) post: 通常前進（受け取るspillに at_spill を加算）
            post_adj, post_rep, _post_slack, _post_spill = _adjust_segment(
                post_weeks,
                load_by_week,
                cap_w,
                start_slack=at_slack,
                start_spill=at_spill_to_post,
                mode="forward",
            )
            # マージ
            for d in (pre_adj, at_adj, post_adj):
                adj_by_week.update(d)
            week_report.extend(pre_rep + at_rep + post_rep)
        elif pol in ("AGG_FAR", "AGG-FAR"):
            # 1) pre（一次）: 通常前進（start_spill=0）
            pre1_adj, pre1_rep, pre1_slack, pre1_spill = _adjust_segment(
                pre_weeks,
                load_by_week,
                cap_w,
                start_slack=0.0,
                start_spill=0.0,
                mode="forward",
            )
            # 2) at: agg_far（スピルは区間外へ=preへ）
            at_adj, at_rep, at_slack, at_spill_to_pre = _adjust_segment(
                at_weeks,
                load_by_week,
                cap_w,
                start_slack=pre1_slack,
                start_spill=pre1_spill,
                mode="agg_far",
            )
            # 3) pre（二次）: atからのスピルを受けて再計算
            pre2_adj, pre2_rep, _pre2_slack, _pre2_spill = _adjust_segment(
                pre_weeks,
                load_by_week,
                cap_w,
                start_slack=0.0,
                start_spill=at_spill_to_pre,
                mode="forward",
            )
            # 4) post: 通常前進（atのスラックを引継ぎ、spillは0）
            post_adj, post_rep, _post_slack, _post_spill = _adjust_segment(
                post_weeks,
                load_by_week,
                cap_w,
                start_slack=at_slack,
                start_spill=0.0,
                mode="forward",
            )
            # マージ（preは二次結果を採用）
            for d in (pre2_adj, at_adj, post_adj):
                adj_by_week.update(d)
            week_report.extend(pre2_rep + at_rep + post_rep)
        elif pol in ("BLEND",):
            # 1) pre（一次）
            pre1_adj, pre1_rep, pre1_slack, pre1_spill = _adjust_segment(
                pre_weeks,
                load_by_week,
                cap_w,
                start_slack=0.0,
                start_spill=0.0,
                mode="forward",
            )
            # 2) at（吐き出しを後でpre/post に分割）
            at_adj, at_rep, at_slack, at_spill_total = _adjust_segment(
                at_weeks,
                load_by_week,
                cap_w,
                start_slack=pre1_slack,
                start_spill=pre1_spill,
                mode="blend",
            )
            # 3) スピル分割（三角重み + ウィンドウ連動、週別spillに重みを掛けて集約比率を算定）
            n_at = len(at_weeks)
            if args.blend_split_next is not None:
                share_next = max(0.0, min(1.0, float(args.blend_split_next)))
            elif n_at > 0 and at_rep:
                win_w = (
                    int(math.ceil(float(args.recon_window_days) / 7.0))
                    if args.recon_window_days
                    else max(1, n_at // 2)
                )
                # 週キー→インデックスのマップ
                idx_map = {w: i for i, w in enumerate(at_weeks)}
                w_next_sum = 0.0
                w_prev_sum = 0.0
                for row in at_rep:
                    try:
                        w = str(row.get("week", ""))
                        spill_i = float(row.get("spill_out", 0.0) or 0.0)
                        if spill_i <= 0:
                            continue
                        i = idx_map.get(w, 0)  # 0..n_at-1
                        d_prev = i  # 境界月頭からの距離
                        d_next = n_at - 1 - i  # 境界月末までの距離
                        # 三角重み: 近いほど大、遠いほど小、window外は0
                        base_prev = max(0.0, float(win_w - d_prev))
                        base_next = max(0.0, float(win_w - d_next))
                        if args.blend_weight_mode == "quad":
                            w_prev = base_prev**2
                            w_next = base_next**2
                        else:
                            # tri/lin は同じ指数1（将来 tri を中心三角に拡張可能）
                            w_prev = base_prev
                            w_next = base_next
                        w_prev_sum += spill_i * w_prev
                        w_next_sum += spill_i * w_next
                    except Exception:
                        continue
                denom = w_prev_sum + w_next_sum
                share_next = (w_next_sum / denom) if denom > 0 else 0.5
                # 安全クリップ
                share_next = max(0.05, min(0.95, share_next))
            else:
                share_next = 0.5
            share_prev = 1.0 - share_next
            spill_prev = at_spill_total * share_prev
            spill_next = at_spill_total * share_next
            # 4) pre（二次）: spill_prev を受けて再計算
            pre2_adj, pre2_rep, _pre2_slack, _pre2_spill = _adjust_segment(
                pre_weeks,
                load_by_week,
                cap_w,
                start_slack=0.0,
                start_spill=spill_prev,
                mode="forward",
            )
            # 5) post: at のスラック + spill_next を受けて前進
            post_adj, post_rep, _post_slack, _post_spill = _adjust_segment(
                post_weeks,
                load_by_week,
                cap_w,
                start_slack=at_slack,
                start_spill=spill_next,
                mode="forward",
            )
            # マージ（preは二次結果）
            for d in (pre2_adj, at_adj, post_adj):
                adj_by_week.update(d)
            week_report.extend(pre2_rep + at_rep + post_rep)
        else:
            # safety: 未対応ポリシーは従来
            adj_by_week, week_report = _adjust_by_capacity(weeks, load_by_week, cap_w)
    else:
        # 既定（元の挙動）
        adj_by_week, week_report = _adjust_by_capacity(weeks, load_by_week, cap_w)
    # cutoverメタ（境界期間のタグ付け）
    if cutover_month:
        # cutover月内の週を抽出し、週順で並べ替え
        at_weeks = [
            r
            for r in week_report
            if period_by_week.get(str(r.get("week", ""))) == cutover_month
        ]

        def _wknum(wk: str) -> int:
            return week_index.get(wk, 0)

        at_weeks_sorted = sorted(at_weeks, key=lambda r: _wknum(str(r.get("week", ""))))
        n_at = len(at_weeks_sorted)
        win_weeks = (
            int(math.ceil(float(args.recon_window_days) / 7.0))
            if args.recon_window_days
            else 0
        )
        for idx, row in enumerate(at_weeks_sorted, start=1):
            row["boundary_period"] = True
            row["boundary_index"] = idx
            row["boundary_size"] = n_at
            if win_weeks > 0:
                row["in_window_pre"] = bool(idx <= max(1, win_weeks))
                row["in_window_post"] = bool((n_at - idx + 1) <= max(1, win_weeks))
        # 全週にゾーン（pre/at/post）を付与
        for row in week_report:
            w = str(row.get("week", ""))
            per = period_by_week.get(w)
            if not per:
                continue
            if per < cutover_month:
                row["zone"] = "pre"
            elif per == cutover_month:
                row["zone"] = "at"
            else:
                row["zone"] = "post"

    # 週別係数を用いてFGの解放をスケーリング + 受入の再配分（lt_weeksでシフト）
    rows_out: List[Dict[str, Any]] = []
    receipt_adj: DefaultDict[Tuple[str, str], float] = __import__(
        "collections"
    ).defaultdict(float)
    fg_adj_totals: DefaultDict[str, float] = __import__("collections").defaultdict(float)
    for r in mrp.get("rows", []):
        it = str(r.get("item"))
        w = str(r.get("week"))
        por = float(r.get("planned_order_release", 0) or 0)
        r2 = dict(r)
        if it in fg_skus:
            base = load_by_week.get(w, 0.0)
            target = adj_by_week.get(w, base)
            factor = (target / base) if base > 0 else 1.0
            adj_rel_raw = por * factor
            adj_rel = _round_quantity(adj_rel_raw, mode=args.round_mode)
            fg_adj_totals[w] += float(adj_rel)
            try:
                lt_w = int(r.get("lt_weeks", 0) or 0)
            except Exception:
                lt_w = 0
            idx = week_index.get(w, 0)
            rec_idx = min(len(weeks) - 1, idx + max(0, lt_w))
            receipt_adj[(it, weeks[rec_idx])] += float(adj_rel)
            r2["planned_order_release_adj"] = adj_rel
            r2["planned_order_receipt_adj"] = _round_quantity(
                receipt_adj.get((it, w), 0.0),
                mode=args.round_mode,
            )
        else:
            adj_rel = round(por, 6)
            r2["planned_order_release_adj"] = adj_rel
            r2["planned_order_receipt_adj"] = round(
                receipt_adj.get((it, w), 0.0), 6
            )
        rows_out.append(r2)

    rounded_original: Dict[str, float | int] = {}
    rounded_adjusted: Dict[str, float | int] = {}
    for w in weeks:
        rounded_original[w] = _round_quantity(
            load_by_week.get(w, 0.0), mode=args.round_mode
        )
        adj_val = fg_adj_totals.get(w)
        if w not in fg_adj_totals:
            adj_val = adj_by_week.get(w, 0.0)
        rounded_adjusted[w] = _round_quantity(adj_val, mode=args.round_mode)
    for row in week_report:
        wk = str(row.get("week", ""))
        if wk in rounded_original:
            row["original_load"] = rounded_original[wk]
        if wk in rounded_adjusted:
            row["adjusted_load"] = rounded_adjusted[wk]

    payload = {
        "schema_version": mrp.get("schema_version", "agg-1.0"),
        "note": "PR5: CRPライト（週次能力に合わせて解放を前倒し/繰越で調整）",
        "inputs_summary": {
            "allocate_rows": len(alloc.get("rows", [])),
            "mrp_rows": len(mrp.get("rows", [])),
            "weeks": len(weeks),
            "fg_skus": len(fg_skus),
            "calendar_mode": calendar_mode,
            "calendar_periods": len(lookup.distributions) if lookup else 0,
        },
        "reconcile_params": {
            "cutover_date": args.cutover_date,
            "recon_window_days": args.recon_window_days,
            "anchor_policy": args.anchor_policy,
        },
        "weekly_summary": week_report,
        "boundary_summary": (
            {
                "period": cutover_month,
                "anchor_policy": args.anchor_policy,
                "window_days": args.recon_window_days,
                "weeks": len(
                    [
                        r
                        for r in week_report
                        if period_by_week.get(str(r.get("week", ""))) == cutover_month
                    ]
                ),
                "pre_weeks": len(
                    [r for r in week_report if str(r.get("zone")) == "pre"]
                ),
                "post_weeks": len(
                    [r for r in week_report if str(r.get("zone")) == "post"]
                ),
            }
            if cutover_month
            else None
        ),
        "rows": rows_out,
    }
    storage_config, warning = resolve_storage_config(
        args.storage, args.version_id, cli_label="reconcile"
    )
    if warning:
        print(warning, file=sys.stderr)

    try:
        wrote_db = store_plan_final_payload(
            storage_config,
            plan_final=payload,
            output_path=Path(args.output),
        )
    except PlanRepositoryError as exc:
        print(f"[error] PlanRepository書き込みに失敗しました: {exc}", file=sys.stderr)
        sys.exit(1)

    if storage_config.use_files:
        print(f"[ok] wrote {args.output}")
    if wrote_db:
        print(
            "[ok] stored plan_final rows in PlanRepository "
            f"version={storage_config.version_id}"
        )


if __name__ == "__main__":
    main()
