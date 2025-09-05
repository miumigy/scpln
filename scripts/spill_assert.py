#!/usr/bin/env python3
"""
Spill分布の簡易アサート

条件:
- zoneごとに spill_in>eps の週数が 1 以下（セグメント先頭のみ流入があり得る）。
- 重大違反があれば非0終了。

使い方:
  PYTHONPATH=. python3 scripts/spill_assert.py -i out/plan_final.json
"""
from __future__ import annotations

import argparse
import json


def main() -> None:
    ap = argparse.ArgumentParser(description="Spill分布の簡易アサート")
    ap.add_argument("-i", "--input", required=True, help="plan_final.json")
    ap.add_argument("--eps", type=float, default=1e-9, help="しきい値")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        plan = json.load(f)
    ws = list(plan.get("weekly_summary") or [])
    if not ws:
        print("[skip] no weekly_summary")
        return
    counts = {"pre": 0, "at": 0, "post": 0}
    for r in ws:
        z = str(r.get("zone") or "").lower()
        if z not in counts:
            continue
        try:
            if abs(float(r.get("spill_in", 0) or 0.0)) > args.eps:
                counts[z] += 1
        except Exception:
            pass
    failures = [z for z, c in counts.items() if c > 1]
    if failures:
        print("[fail] too many spill_in weeks:", counts)
        raise SystemExit(1)
    print("[ok] spill_in counts:", counts)


if __name__ == "__main__":
    main()

