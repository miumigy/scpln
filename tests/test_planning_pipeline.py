import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SAMPLES = ROOT / "samples" / "planning"


def run(cmd, cwd=None, env=None):
    e = os.environ.copy()
    e.setdefault("PYTHONPATH", str(ROOT))
    if env:
        e.update(env)
    res = subprocess.run(
        cmd, cwd=cwd or ROOT, env=e, check=True, capture_output=True, text=True
    )
    return res


def test_aggregate_supply_backlog(tmp_path: Path):
    out = tmp_path
    agg = out / "aggregate.json"
    run(
        [
            sys.executable,
            str(SCRIPTS / "plan_aggregate.py"),
            "-i",
            str(SAMPLES),
            "-o",
            str(agg),
        ]
    )
    data = json.loads(agg.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    assert rows, "aggregate rows should not be empty"

    # 期間2025-01の総供給は min(需要合計, 能力) になる
    dem = sum(r["demand"] for r in rows if r["period"] == "2025-01")
    sup = sum(r["supply"] for r in rows if r["period"] == "2025-01")
    cap = max(r["capacity_total"] for r in rows if r["period"] == "2025-01")
    assert abs(sup - min(dem, cap)) < 1e-6
    # backlog は 需要-供給 のはず
    back = sum(r["backlog"] for r in rows if r["period"] == "2025-01")
    assert abs((dem - sup) - back) < 1e-6


def test_allocate_mass_balance(tmp_path: Path):
    out = tmp_path
    agg = out / "aggregate.json"
    sku = out / "sku_week.json"
    # round=none で丸め誤差を避ける
    run(
        [
            sys.executable,
            str(SCRIPTS / "plan_aggregate.py"),
            "-i",
            str(SAMPLES),
            "-o",
            str(agg),
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "allocate.py"),
            "-i",
            str(agg),
            "-I",
            str(SAMPLES),
            "-o",
            str(sku),
            "--weeks",
            "4",
            "--round",
            "none",
        ]
    )
    sdata = json.loads(sku.read_text(encoding="utf-8"))
    rows = sdata.get("rows", [])
    assert rows, "allocate rows should not be empty"

    # family×period の総量一致（需要/供給/残）
    from collections import defaultdict

    agg_dem = defaultdict(float)
    agg_sup = defaultdict(float)
    agg_bac = defaultdict(float)
    for r in rows:
        key = (r["family"], r["period"])
        agg_dem[key] += float(r["demand"])  # 週・SKU合計
        agg_sup[key] += float(r["supply"])  # 週・SKU合計
        agg_bac[key] += float(r["backlog"])  # 週・SKU合計

    # 参照: aggregate
    adata = json.loads(agg.read_text(encoding="utf-8"))
    arows = {(r["family"], r["period"]): r for r in adata.get("rows", [])}
    for key, v in agg_dem.items():
        a = arows[key]
        assert abs(v - float(a["demand"])) < 1e-6
        assert abs(agg_sup[key] - float(a["supply"])) < 1e-6
        assert abs(agg_bac[key] - float(a["backlog"])) < 1e-6


def test_mrp_basic_properties(tmp_path: Path):
    out = tmp_path
    agg = out / "aggregate.json"
    sku = out / "sku_week.json"
    mrp = out / "mrp.json"
    run(
        [
            sys.executable,
            str(SCRIPTS / "plan_aggregate.py"),
            "-i",
            str(SAMPLES),
            "-o",
            str(agg),
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "allocate.py"),
            "-i",
            str(agg),
            "-I",
            str(SAMPLES),
            "-o",
            str(sku),
            "--weeks",
            "4",
            "--round",
            "none",
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "mrp.py"),
            "-i",
            str(sku),
            "-I",
            str(SAMPLES),
            "-o",
            str(mrp),
            "--lt-unit",
            "day",
            "--weeks",
            "4",
        ]
    )
    m = json.loads(mrp.read_text(encoding="utf-8"))
    rows = m.get("rows", [])
    assert rows, "mrp rows should not be empty"

    # ロット/MOQの性質（net_req>0なら受入は切上げ、ロットの倍数）
    for r in rows:
        net = float(r["net_req"])
        por = float(r["planned_order_receipt"])
        lot = float(r.get("lot", 1.0))
        if net > 0:
            assert por >= net - 1e-6
            # 倍数チェック（誤差許容）
            if lot > 0:
                mod = (por / lot) - round(por / lot)
                assert abs(mod) < 1e-6


def test_reconcile_capacity_respected_and_report(tmp_path: Path):
    out = tmp_path
    agg = out / "aggregate.json"
    sku = out / "sku_week.json"
    mrp = out / "mrp.json"
    plan = out / "plan_final.json"
    rep = out / "report.csv"
    run(
        [
            sys.executable,
            str(SCRIPTS / "plan_aggregate.py"),
            "-i",
            str(SAMPLES),
            "-o",
            str(agg),
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "allocate.py"),
            "-i",
            str(agg),
            "-I",
            str(SAMPLES),
            "-o",
            str(sku),
            "--weeks",
            "4",
            "--round",
            "int",
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "mrp.py"),
            "-i",
            str(sku),
            "-I",
            str(SAMPLES),
            "-o",
            str(mrp),
            "--lt-unit",
            "day",
            "--weeks",
            "4",
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "reconcile.py"),
            "-i",
            str(sku),
            str(mrp),
            "-I",
            str(SAMPLES),
            "-o",
            str(plan),
            "--weeks",
            "4",
        ]
    )

    p = json.loads(plan.read_text(encoding="utf-8"))
    ws = p.get("weekly_summary", [])
    assert ws, "weekly_summary should exist"
    for r in ws:
        cap = float(r["capacity"]) or 0.0
        adj = float(r["adjusted_load"]) or 0.0
        slack_in = float(r.get("carried_slack_in", 0.0))
        # 調整後負荷は有効能力（cap+slack_in）以内
        assert adj <= cap + slack_in + 1e-6

    # KPI レポート生成と基本検証
    run(
        [
            sys.executable,
            str(SCRIPTS / "report.py"),
            "-i",
            str(plan),
            "-I",
            str(SAMPLES),
            "-o",
            str(rep),
        ]
    )
    content = rep.read_text(encoding="utf-8").splitlines()
    assert content and content[0].startswith("type,week"), "CSV header present"
    # サービス行に 2025-01-W2 の供給>0 を期待（LTシフトの受入）
    svc = [line for line in content if line.startswith("service,2025-01-W2")]
    assert svc, "service row for 2025-01-W2 present"
    # 末尾が fill_rate, >0
    last = svc[0].split(",")
    fill = float(last[-1])
    assert fill >= 0.0


def test_reconcile_spill_propagation_and_utilization(tmp_path: Path):
    out = tmp_path
    agg = out / "aggregate.json"
    sku = out / "sku_week.json"
    mrp = out / "mrp.json"
    plan = out / "plan_final.json"
    run(
        [
            sys.executable,
            str(SCRIPTS / "plan_aggregate.py"),
            "-i",
            str(SAMPLES),
            "-o",
            str(agg),
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "allocate.py"),
            "-i",
            str(agg),
            "-I",
            str(SAMPLES),
            "-o",
            str(sku),
            "--weeks",
            "4",
            "--round",
            "int",
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "mrp.py"),
            "-i",
            str(sku),
            "-I",
            str(SAMPLES),
            "-o",
            str(mrp),
            "--lt-unit",
            "day",
            "--weeks",
            "4",
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "reconcile.py"),
            "-i",
            str(sku),
            str(mrp),
            "-I",
            str(SAMPLES),
            "-o",
            str(plan),
            "--weeks",
            "4",
        ]
    )

    p = json.loads(plan.read_text(encoding="utf-8"))
    ws = p.get("weekly_summary", [])
    # spillの伝播: 次週のspill_in ≒ 当週のspill_out
    for i in range(len(ws) - 1):
        spill_out = float(ws[i].get("spill_out", 0) or 0)
        spill_in_next = float(ws[i + 1].get("spill_in", 0) or 0)
        assert abs(spill_out - spill_in_next) < 1e-6
        # 稼働率が1.0を超えない
        cap = float(ws[i].get("capacity", 0) or 0)
        adj = float(ws[i].get("adjusted_load", 0) or 0)
        util = (adj / cap) if cap > 0 else 0.0
        assert util <= 1.0 + 1e-6


def test_fill_rate_bounds(tmp_path: Path):
    out = tmp_path
    agg = out / "aggregate.json"
    sku = out / "sku_week.json"
    mrp = out / "mrp.json"
    plan = out / "plan_final.json"
    rep = out / "report.csv"
    run(
        [
            sys.executable,
            str(SCRIPTS / "plan_aggregate.py"),
            "-i",
            str(SAMPLES),
            "-o",
            str(agg),
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "allocate.py"),
            "-i",
            str(agg),
            "-I",
            str(SAMPLES),
            "-o",
            str(sku),
            "--weeks",
            "4",
            "--round",
            "none",
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "mrp.py"),
            "-i",
            str(sku),
            "-I",
            str(SAMPLES),
            "-o",
            str(mrp),
            "--lt-unit",
            "day",
            "--weeks",
            "4",
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "reconcile.py"),
            "-i",
            str(sku),
            str(mrp),
            "-I",
            str(SAMPLES),
            "-o",
            str(plan),
            "--weeks",
            "4",
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "report.py"),
            "-i",
            str(plan),
            "-I",
            str(SAMPLES),
            "-o",
            str(rep),
        ]
    )
    content = rep.read_text(encoding="utf-8").splitlines()
    # 2行目以降がデータ
    for line in content[1:]:
        parts = line.split(",")
        if not parts or parts[0] != "service":
            continue
        # service: week,,,,,,,demand,supply_plan,fill_rate
        try:
            demand = float(parts[-3])
            fill = float(parts[-1])
        except Exception:
            continue
        assert 0.0 <= fill <= 1.0 + 1e-9
        if demand == 0:
            assert abs(fill - 1.0) < 1e-9


def test_round_modes_and_weeks_variation_mass_balance(tmp_path: Path):
    out = tmp_path
    weeks_cases = [3, 4, 5]
    round_modes = ["none", "int", "dec1", "dec2"]
    agg = out / "aggregate.json"
    run(
        [
            sys.executable,
            str(SCRIPTS / "plan_aggregate.py"),
            "-i",
            str(SAMPLES),
            "-o",
            str(agg),
        ]
    )
    adata = json.loads(agg.read_text(encoding="utf-8"))
    arows = {(r["family"], r["period"]): r for r in adata.get("rows", [])}

    for w in weeks_cases:
        for rm in round_modes:
            sku = out / f"sku_week_w{w}_{rm}.json"
            run(
                [
                    sys.executable,
                    str(SCRIPTS / "allocate.py"),
                    "-i",
                    str(agg),
                    "-I",
                    str(SAMPLES),
                    "-o",
                    str(sku),
                    "--weeks",
                    str(w),
                    "--round",
                    rm,
                ]
            )
            sdata = json.loads(sku.read_text(encoding="utf-8"))
            rows = sdata.get("rows", [])
            from collections import defaultdict

            dem = defaultdict(float)
            sup = defaultdict(float)
            bac = defaultdict(float)
            for r in rows:
                key = (r["family"], r["period"])
                dem[key] += float(r["demand"])  # 週×SKU合計
                sup[key] += float(r["supply"])  # 週×SKU合計
                bac[key] += float(r["backlog"])  # 週×SKU合計
            for key, a in arows.items():
                assert abs(dem[key] - float(a["demand"])) < 1e-6
                assert abs(sup[key] - float(a["supply"])) < 1e-6
                assert abs(bac[key] - float(a["backlog"])) < 1e-6
