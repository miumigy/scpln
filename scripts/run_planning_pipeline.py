#!/usr/bin/env python3
"""Planningパイプライン統合CLI（Python版）。

plan_aggregate → allocate → mrp → reconcile → reconcile_levels → report の順で
既存スクリプトを呼び出し、主要オプションと storage 設定を一括で制御する。

従来の `run_planning_pipeline.sh` を置き換える用途を想定する。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List

from scripts.plan_pipeline_io import _calendar_cli_args


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent


def _script(name: str) -> str:
    return str(SCRIPTS_DIR / name)


def _extend_storage(
    cmd: List[str], storage: str | None, version_id: str | None
) -> None:
    if storage:
        cmd.extend(["--storage", storage])
    if version_id:
        cmd.extend(["--version-id", version_id])


def _run_stage(step: int, total: int, label: str, cmd: List[str], env: dict) -> None:
    print(f"[{step}/{total}] {label}")
    subprocess.run(cmd, check=True, env=env)


def _apply_preset(args: argparse.Namespace) -> None:
    preset = args.preset
    if not preset:
        return
    if preset == "det_near":
        if not args.anchor_policy:
            args.anchor_policy = "DET_near"
        if args.recon_window_days is None:
            args.recon_window_days = 7
    elif preset == "agg_far":
        if not args.anchor_policy:
            args.anchor_policy = "AGG_far"
        if args.recon_window_days is None:
            args.recon_window_days = 7
    elif preset == "blend":
        if not args.anchor_policy:
            args.anchor_policy = "blend"
        if args.recon_window_days is None:
            args.recon_window_days = 14
        if args.blend_weight_mode is None:
            args.blend_weight_mode = "tri"


def main() -> None:
    ap = argparse.ArgumentParser(description="Planningパイプライン統合CLI")
    ap.add_argument(
        "-I", "--input-dir", default="samples/planning", help="入力ディレクトリ"
    )
    ap.add_argument("-o", "--output-dir", default="out", help="出力ディレクトリ")
    ap.add_argument(
        "--weeks", type=int, default=4, help="カレンダーがない場合のフォールバック週数"
    )
    ap.add_argument(
        "--round",
        dest="round_mode",
        default="int",
        choices=["none", "int", "dec1", "dec2"],
        help="allocateの丸めモード",
    )
    ap.add_argument(
        "--lt-unit",
        dest="lt_unit",
        default="day",
        choices=["day", "week"],
        help="mrpのLT単位",
    )
    ap.add_argument("--week-days", dest="week_days", type=int, default=7)
    ap.add_argument("--cutover-date", dest="cutover_date", default=None)
    ap.add_argument(
        "--recon-window-days", dest="recon_window_days", type=int, default=None
    )
    ap.add_argument("--anchor-policy", dest="anchor_policy", default=None)
    ap.add_argument(
        "--blend-split-next", dest="blend_split_next", type=float, default=None
    )
    ap.add_argument(
        "--blend-weight-mode",
        dest="blend_weight_mode",
        choices=["tri", "lin", "quad"],
        default="tri",
    )
    ap.add_argument("--storage", choices=["db", "files", "both"], default=None)
    ap.add_argument("--version-id", dest="version_id", default=None)
    ap.add_argument("--apply-adjusted", dest="apply_adjusted", action="store_true")
    ap.add_argument(
        "--preset",
        choices=["det_near", "agg_far", "blend"],
        default=None,
        help="anchor関連オプションのプリセット",
    )
    ap.add_argument(
        "--max-adjust-ratio", dest="max_adjust_ratio", type=float, default=None
    )
    ap.add_argument("--carryover", dest="carryover", default="none")
    ap.add_argument(
        "--carryover-split", dest="carryover_split", type=float, default=None
    )
    ap.add_argument("--tol-abs", dest="tol_abs", type=float, default=1e-6)
    ap.add_argument("--tol-rel", dest="tol_rel", type=float, default=1e-6)
    args = ap.parse_args()

    _apply_preset(args)

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(REPO_ROOT))

    calendar_args = _calendar_cli_args(input_dir=input_dir, fallback_weeks=args.weeks)

    steps: List[tuple[str, List[str]]] = []

    agg_json = output_dir / "aggregate.json"
    sku_json = output_dir / "sku_week.json"
    mrp_json = output_dir / "mrp.json"
    plan_final_json = output_dir / "plan_final.json"
    recon_log_json = output_dir / "reconciliation_log.json"
    recon_log_adj_json = output_dir / "reconciliation_log_adjusted.json"
    sku_adj_json = output_dir / "sku_week_adjusted.json"
    mrp_adj_json = output_dir / "mrp_adjusted.json"
    plan_final_adj_json = output_dir / "plan_final_adjusted.json"

    # aggregate
    cmd = [
        sys.executable,
        _script("plan_aggregate.py"),
        "-i",
        str(input_dir),
        "-o",
        str(agg_json),
        "--round",
        args.round_mode,
    ]
    _extend_storage(cmd, args.storage, args.version_id)
    steps.append(("aggregate", cmd))

    # allocate
    cmd = [
        sys.executable,
        _script("allocate.py"),
        "-i",
        str(agg_json),
        "-I",
        str(input_dir),
        "-o",
        str(sku_json),
        "--round",
        args.round_mode,
        *calendar_args,
    ]
    _extend_storage(cmd, args.storage, args.version_id)
    steps.append(("allocate", cmd))

    # mrp
    cmd = [
        sys.executable,
        _script("mrp.py"),
        "-i",
        str(sku_json),
        "-I",
        str(input_dir),
        "-o",
        str(mrp_json),
        "--lt-unit",
        args.lt_unit,
        "--week-days",
        str(args.week_days),
        *calendar_args,
    ]
    _extend_storage(cmd, args.storage, args.version_id)
    steps.append(("mrp", cmd))

    # reconcile
    cmd = [
        sys.executable,
        _script("reconcile.py"),
        "-i",
        str(sku_json),
        str(mrp_json),
        "-I",
        str(input_dir),
        "-o",
        str(plan_final_json),
        "--round",
        args.round_mode,
        *calendar_args,
    ]
    if args.cutover_date:
        cmd.extend(["--cutover-date", args.cutover_date])
    if args.recon_window_days is not None:
        cmd.extend(["--recon-window-days", str(args.recon_window_days)])
    if args.anchor_policy:
        cmd.extend(["--anchor-policy", args.anchor_policy])
    if args.blend_split_next is not None:
        cmd.extend(["--blend-split-next", str(args.blend_split_next)])
    if args.blend_weight_mode:
        cmd.extend(["--blend-weight-mode", args.blend_weight_mode])
    _extend_storage(cmd, args.storage, args.version_id)
    steps.append(("reconcile", cmd))

    # reconcile_levels
    cmd = [
        sys.executable,
        _script("reconcile_levels.py"),
        "-i",
        str(agg_json),
        str(sku_json),
        "-o",
        str(recon_log_json),
        "--version",
        "pipeline",
        "--tol-abs",
        str(args.tol_abs),
        "--tol-rel",
        str(args.tol_rel),
        *calendar_args,
    ]
    if args.cutover_date:
        cmd.extend(["--cutover-date", args.cutover_date])
    if args.recon_window_days is not None:
        cmd.extend(["--recon-window-days", str(args.recon_window_days)])
    if args.anchor_policy:
        cmd.extend(["--anchor-policy", args.anchor_policy])
    _extend_storage(cmd, args.storage, args.version_id)
    steps.append(("reconcile_levels", cmd))

    # export CSVs (before)
    cmd = [
        sys.executable,
        _script("export_reconcile_csv.py"),
        "-i",
        str(recon_log_json),
        "-o",
        str(output_dir / "reconciliation_before.csv"),
        "--label",
        "before",
    ]
    _extend_storage(cmd, args.storage, args.version_id)
    steps.append(("export_reconcile_csv", cmd))

    cmd = [
        sys.executable,
        _script("export_reconcile_csv.py"),
        "-i",
        str(recon_log_json),
        "-o",
        str(output_dir / "reconciliation_violations_before.csv"),
        "--label",
        "before",
        "--only-violations",
    ]
    _extend_storage(cmd, args.storage, args.version_id)
    steps.append(("export_reconcile_violations", cmd))

    run_adjust_section = bool(args.anchor_policy and args.cutover_date)

    if run_adjust_section:
        # anchor_adjust
        cmd = [
            sys.executable,
            _script("anchor_adjust.py"),
            "-i",
            str(agg_json),
            str(sku_json),
            "-o",
            str(sku_adj_json),
            "--cutover-date",
            args.cutover_date,
            "--anchor-policy",
            args.anchor_policy,
            *calendar_args,
        ]
        if args.recon_window_days is not None:
            cmd.extend(["--recon-window-days", str(args.recon_window_days)])
        if args.max_adjust_ratio is not None:
            cmd.extend(["--max-adjust-ratio", str(args.max_adjust_ratio)])
        if args.carryover:
            cmd.extend(["--carryover", args.carryover])
        if args.tol_abs is not None:
            cmd.extend(["--tol-abs", str(args.tol_abs)])
        if args.tol_rel is not None:
            cmd.extend(["--tol-rel", str(args.tol_rel)])
        if args.carryover_split is not None:
            cmd.extend(["--carryover-split", str(args.carryover_split)])
        _extend_storage(cmd, args.storage, args.version_id)
        steps.append(("anchor_adjust", cmd))

        # reconcile_levels (adjusted)
        cmd = [
            sys.executable,
            _script("reconcile_levels.py"),
            "-i",
            str(agg_json),
            str(sku_adj_json),
            "-o",
            str(recon_log_adj_json),
            "--version",
            "pipeline-adjusted",
            "--tol-abs",
            str(args.tol_abs),
            "--tol-rel",
            str(args.tol_rel),
            *calendar_args,
        ]
        if args.cutover_date:
            cmd.extend(["--cutover-date", args.cutover_date])
        if args.recon_window_days is not None:
            cmd.extend(["--recon-window-days", str(args.recon_window_days)])
        if args.anchor_policy:
            cmd.extend(["--anchor-policy", args.anchor_policy])
        _extend_storage(cmd, args.storage, args.version_id)
        steps.append(("reconcile_levels_adjusted", cmd))

        # export compare CSVs
        cmd = [
            sys.executable,
            _script("export_reconcile_csv.py"),
            "-i",
            str(recon_log_json),
            "-j",
            str(recon_log_adj_json),
            "-o",
            str(output_dir / "reconciliation_compare.csv"),
            "--label",
            "before",
            "--label2",
            "after",
        ]
        _extend_storage(cmd, args.storage, args.version_id)
        steps.append(("export_reconcile_compare", cmd))

        cmd = [
            sys.executable,
            _script("export_reconcile_csv.py"),
            "-i",
            str(recon_log_json),
            "-j",
            str(recon_log_adj_json),
            "-o",
            str(output_dir / "reconciliation_violations_compare.csv"),
            "--label",
            "before",
            "--label2",
            "after",
            "--only-violations",
        ]
        _extend_storage(cmd, args.storage, args.version_id)
        steps.append(("export_reconcile_violations_compare", cmd))

        cmd = [
            sys.executable,
            _script("export_carryover_csv.py"),
            "-i",
            str(sku_adj_json),
            "-o",
            str(output_dir / "carryover.csv"),
        ]
        steps.append(("export_carryover", cmd))

        if args.apply_adjusted:
            # mrp adjusted
            cmd = [
                sys.executable,
                _script("mrp.py"),
                "-i",
                str(sku_adj_json),
                "-I",
                str(input_dir),
                "-o",
                str(mrp_adj_json),
                "--lt-unit",
                args.lt_unit,
                "--week-days",
                str(args.week_days),
                *calendar_args,
            ]
            _extend_storage(cmd, args.storage, args.version_id)
            steps.append(("mrp_adjusted", cmd))

            cmd = [
                sys.executable,
                _script("reconcile.py"),
                "-i",
                str(sku_adj_json),
                str(mrp_adj_json),
                "-I",
                str(input_dir),
                "-o",
                str(plan_final_adj_json),
                "--round",
                args.round_mode,
                *calendar_args,
            ]
            if args.cutover_date:
                cmd.extend(["--cutover-date", args.cutover_date])
            if args.recon_window_days is not None:
                cmd.extend(["--recon-window-days", str(args.recon_window_days)])
        if args.anchor_policy:
            cmd.extend(["--anchor-policy", args.anchor_policy])
        if args.blend_split_next is not None:
            cmd.extend(["--blend-split-next", str(args.blend_split_next)])
        if args.blend_weight_mode:
            cmd.extend(["--blend-weight-mode", args.blend_weight_mode])
        _extend_storage(cmd, args.storage, args.version_id)
        steps.append(("reconcile_adjusted", cmd))

        cmd = [
            sys.executable,
            _script("report.py"),
            "-i",
            str(plan_final_adj_json),
            "-I",
            str(input_dir),
            "-o",
            str(output_dir / "report_adjusted.csv"),
        ]
        _extend_storage(cmd, args.storage, args.version_id)
        steps.append(("report_adjusted", cmd))

    # report (baseline)
    cmd = [
        sys.executable,
        _script("report.py"),
        "-i",
        str(plan_final_json),
        "-I",
        str(input_dir),
        "-o",
        str(output_dir / "report.csv"),
    ]
    _extend_storage(cmd, args.storage, args.version_id)
    steps.append(("report", cmd))

    total_steps = len(steps)
    for idx, (label, cmd) in enumerate(steps, start=1):
        _run_stage(idx, total_steps, label, cmd, env)

    print(f"[ok] pipeline completed. outputs in {output_dir}")


if __name__ == "__main__":
    main()
