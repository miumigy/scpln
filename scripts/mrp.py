#!/usr/bin/env python3
"""
MRPライト（PR4）: SKU×週の要求から、LT/ロット/MOQを考慮したネット要件と手配計画を算出。

機能（v0）
- 入力: allocateの出力（SKU×週の demand/supply/backlog）
- 在庫・入荷: `inventory.csv`（on-hand初期在庫、loc無視で合算）、`open_po.csv`（期中入荷）
- アイテム属性: `item.csv`（`item, lt, lot, moq`）
- 任意: `bom.csv`（`parent, child, qty`）。親の計画オーダ解放量から子の総所要量を派生
- LT単位: 週 or 日（`--lt-unit`）。日指定時は `--week-days` で週換算
- ロジック: 先行週から on_hand を繰り越し、所要量に対して在庫/入荷を充当→不足を切上げ（MOQ/ロット）して計画受入・解放を作成

使い方:
  python scripts/mrp.py -i out/sku_week.json -I samples/planning -o out/mrp.json --lt-unit day --weeks 4
"""
from __future__ import annotations

import argparse
import json
import os
import csv
from typing import Dict, Any, List, Tuple, DefaultDict


def _read_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_items(path: str | None) -> Dict[str, Dict[str, float]]:
    d: Dict[str, Dict[str, float]] = {}
    if path and os.path.exists(path):
        for r in _read_csv(path):
            it = str(r.get("item"))
            if not it:
                continue
            try:
                lt = float(r.get("lt", 0) or 0)
                lot = float(r.get("lot", 1) or 1)
                moq = float(r.get("moq", 0) or 0)
            except Exception:
                lt, lot, moq = 0.0, 1.0, 0.0
            d[it] = {"lt": lt, "lot": max(1.0, lot), "moq": max(0.0, moq)}
    return d


def _load_inventory(path: str | None) -> Dict[str, float]:
    inv: DefaultDict[str, float] = __import__("collections").defaultdict(float)
    if path and os.path.exists(path):
        for r in _read_csv(path):
            it = str(r.get("item"))
            try:
                q = float(r.get("qty", 0) or 0)
            except Exception:
                q = 0.0
            if it:
                inv[it] += q
    return dict(inv)


def _periods_from_alloc(alloc: Dict[str, Any]) -> List[str]:
    seen = []
    for r in alloc.get("rows", []):
        w = str(r.get("week"))
        if w not in seen and w:
            seen.append(w)
    return sorted(seen)


def _load_open_po(
    path: str | None, *, weeks: List[str]
) -> Dict[Tuple[str, str], float]:
    rec: DefaultDict[Tuple[str, str], float] = __import__("collections").defaultdict(
        float
    )
    if not path or not os.path.exists(path):
        return dict(rec)

    def _to_week_key(due: str) -> str:
        s = str(due)
        if len(s) == 7 and s.count("-") == 1:
            # 'YYYY-MM' → 末尾に W4 を仮置き
            return f"{s}-W4"
        # 'YYYY-MM-DD' を簡易で 1..7=>W1, 8..14=>W2, 15..21=>W3, 22..=>W4 に割当
        try:
            y, m, d = s.split("-")
            day = int(d)
            wk = 1 if day <= 7 else 2 if day <= 14 else 3 if day <= 21 else 4
            return f"{y}-{m}-W{wk}"
        except Exception:
            # そのまま返す（合致しなければ無視される）
            return s

    for r in _read_csv(path):
        it = str(r.get("item"))
        due = _to_week_key(str(r.get("due")))
        try:
            q = float(r.get("qty", 0) or 0)
        except Exception:
            q = 0.0
        if it and due in weeks:
            rec[(it, due)] += q
    return dict(rec)


def _load_bom(path: str | None) -> List[Tuple[str, str, float]]:
    bom: List[Tuple[str, str, float]] = []
    if path and os.path.exists(path):
        for r in _read_csv(path):
            parent = str(r.get("parent"))
            child = str(r.get("child"))
            try:
                qty = float(r.get("qty", 0) or 0)
            except Exception:
                qty = 0.0
            if parent and child and qty > 0:
                bom.append((parent, child, qty))
    return bom


def _lt_weeks(lt_val: float, *, lt_unit: str, week_days: int) -> int:
    if lt_unit == "week":
        return int(max(0, round(lt_val)))
    # day → week 切上げ
    w = (float(lt_val) + max(1, week_days) - 1) // max(1, week_days)
    return int(max(0, int(w)))


def _roll_weeks(weeks: List[str], idx: int, offset: int) -> int:
    j = idx - offset  # 解放は受入よりLTだけ前
    return max(0, j)


def _ceil_lot_moq(qty: float, *, lot: float, moq: float) -> float:
    x = max(0.0, qty)
    if x <= 0:
        return 0.0
    if lot <= 0:
        lot = 1.0
    # MOQを適用 → ロットに切上げ
    x = max(x, moq)
    n = (x + lot - 1e-9) // lot
    return float(n * lot)


def main() -> None:
    ap = argparse.ArgumentParser(description="MRPライト（LT/ロット/MOQ対応、任意BOM）")
    ap.add_argument("-i", "--input", required=True, help="allocateの出力JSON（SKU×週）")
    ap.add_argument("-o", "--output", required=True, help="出力JSON（MRP計画）")
    ap.add_argument(
        "-I",
        "--input-dir",
        dest="input_dir",
        default=None,
        help="CSVフォルダ（item/inventory/open_po/bom）",
    )
    ap.add_argument("--item", dest="item", default=None, help="item.csv")
    ap.add_argument("--inventory", dest="inventory", default=None, help="inventory.csv")
    ap.add_argument("--open-po", dest="open_po", default=None, help="open_po.csv")
    ap.add_argument(
        "--bom", dest="bom", default=None, help="bom.csv（parent,child,qty）"
    )
    ap.add_argument(
        "--lt-unit",
        dest="lt_unit",
        default="day",
        choices=["day", "week"],
        help="LTの単位",
    )
    ap.add_argument(
        "--week-days",
        dest="week_days",
        type=int,
        default=7,
        help="週の日数（day→week換算）",
    )
    ap.add_argument(
        "--weeks",
        dest="weeks_per_period",
        type=int,
        default=4,
        help="1期間あたりの週数（マッピング補助）",
    )
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        alloc = json.load(f)

    base = args.input_dir
    item_path = args.item or (os.path.join(base, "item.csv") if base else None)
    inv_path = args.inventory or (os.path.join(base, "inventory.csv") if base else None)
    opo_path = args.open_po or (os.path.join(base, "open_po.csv") if base else None)
    bom_path = args.bom or (os.path.join(base, "bom.csv") if base else None)

    items = _load_items(item_path)
    inv = _load_inventory(inv_path)
    weeks = _periods_from_alloc(alloc)
    opo = _load_open_po(opo_path, weeks=weeks)
    bom = _load_bom(bom_path)

    # SKU週の要求を集約（gross: demand, backlogは無視 or 参考。ここでは demand を採用）
    gross_by_item_week: DefaultDict[Tuple[str, str], float] = __import__(
        "collections"
    ).defaultdict(float)
    for r in alloc.get("rows", []):
        it = str(r.get("sku"))
        w = str(r.get("week"))
        d = float(r.get("demand", 0) or 0)
        gross_by_item_week[(it, w)] += d

    # 親の解放から子の総所要量を加算
    # まずは親アイテムの計画オーダを計算してから子へ伝播する必要があるが、v0では親の総所要(gross)を準用
    # → v0.1: 親のgrossを起点に子grossへ qty 倍で加算（LT差異は子側のLTで吸収）
    for parent, child, qty in bom:
        for w in weeks:
            g = gross_by_item_week.get((parent, w), 0.0)
            if g > 0 and qty > 0:
                gross_by_item_week[(child, w)] += g * qty

    # アイテムごとのパラメータ
    def get(it: str, key: str, default: float) -> float:
        try:
            return float(items.get(it, {}).get(key, default))
        except Exception:
            return default

    rows_out: List[Dict[str, Any]] = []
    on_hand_by_item: Dict[str, float] = {
        it: inv.get(it, 0.0)
        for it in set(k[0] for k in gross_by_item_week.keys()) | set(inv.keys())
    }

    for it in sorted(on_hand_by_item.keys()):
        lt_w = _lt_weeks(
            get(it, "lt", 0.0), lt_unit=args.lt_unit, week_days=args.week_days
        )
        lot = max(1.0, get(it, "lot", 1.0))
        moq = max(0.0, get(it, "moq", 0.0))
        on_hand = on_hand_by_item.get(it, 0.0)
        planned_receipts: Dict[str, float] = {}
        planned_releases: Dict[str, float] = {}

        for wi, w in enumerate(weeks):
            gross = gross_by_item_week.get((it, w), 0.0)
            sched = float(opo.get((it, w), 0.0))
            on_hand_start = on_hand
            available = on_hand + sched
            net = max(0.0, gross - available)

            por = 0.0
            pol = 0.0
            if net > 0:
                por = _ceil_lot_moq(net, lot=lot, moq=moq)
                on_hand = available + por - gross
                # 解放タイミング（受入よりLT前、境界は0）
                rel_idx = _roll_weeks(weeks, wi, lt_w)
                planned_receipts[w] = planned_receipts.get(w, 0.0) + por
                planned_releases[weeks[rel_idx]] = (
                    planned_releases.get(weeks[rel_idx], 0.0) + por
                )
            else:
                # 受入なし、在庫更新
                on_hand = available - gross

            rows_out.append(
                {
                    "item": it,
                    "week": w,
                    "gross_req": round(gross, 6),
                    "scheduled_receipts": round(sched, 6),
                    "on_hand_start": round(on_hand_start, 6),
                    "net_req": round(net, 6),
                    "planned_order_receipt": round(por, 6),
                    "planned_order_release": round(planned_releases.get(w, 0.0), 6),
                    "lt_weeks": lt_w,
                    "lot": lot,
                    "moq": moq,
                }
            )

    payload = {
        "schema_version": alloc.get("schema_version", "agg-1.0"),
        "note": "PR4: MRPライト（LT/ロット/MOQ、任意BOM）",
        "inputs_summary": {
            **alloc.get("inputs_summary", {}),
            "items": len(items),
            "open_po": len(opo),
            "bom_links": len(bom),
            "weeks": len(weeks),
            "lt_unit": args.lt_unit,
        },
        "rows": rows_out,
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.output}")


if __name__ == "__main__":
    main()
