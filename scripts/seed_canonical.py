#!/usr/bin/env python3
"""既存設定ソースをCanonical設定へ移行するシードスクリプト。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import CanonicalLoaderError, load_canonical_config
from core.config.storage import save_canonical_config

# app/db.py と同じロジックでデフォルトパスを構築
_BASE_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _BASE_DIR / "data" / "scpln.db"
_DEFAULT_DB_PATH = os.getenv("SCPLN_DB", str(_DEFAULT_DB))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Canonical設定のシード生成")
    ap.add_argument("--name", default="canonical-seed", help="設定名")
    ap.add_argument(
        "--psi-json",
        default="static/default_input.json",
        help="PSI入力JSON（既定: static/default_input.json）",
    )
    ap.add_argument(
        "--planning-dir",
        default="samples/planning",
        help="Planning用CSVディレクトリ",
    )
    ap.add_argument(
        "--product-hierarchy",
        default="configs/product_hierarchy.json",
        help="製品階層JSON",
    )
    ap.add_argument(
        "--location-hierarchy",
        default="configs/location_hierarchy.json",
        help="ロケーション階層JSON",
    )
    ap.add_argument(
        "--output",
        default=None,
        help="Canonical設定を保存するJSONファイルパス",
    )
    ap.add_argument(
        "--save-db",
        action="store_true",
        help="canonical_config_versions* テーブルへ書き込み",
    )
    ap.add_argument(
        "--db-path",
        default=_DEFAULT_DB_PATH,  # <- ここを修正
        help="SQLite DBパス（既定: SCPLN_DB or data/scpln.db）",
    )
    ap.add_argument(
        "--allow-errors",
        action="store_true",
        help="検証エラーがあっても処理を続行",
    )
    ap.add_argument(
        "--skip-validation",
        action="store_true",
        help="整合チェックを省略",
    )
    return ap.parse_args()


def _summary(config) -> str:
    return (
        f"items={len(config.items)}, nodes={len(config.nodes)}, arcs={len(config.arcs)}, "
        f"bom={len(config.bom)}, demands={len(config.demands)}, capacities={len(config.capacities)}"
    )


def main() -> int:
    args = parse_args()

    psi_path = Path(args.psi_json).resolve()
    planning_dir = Path(args.planning_dir).resolve()
    prod_hierarchy = Path(args.product_hierarchy).resolve()
    loc_hierarchy = Path(args.location_hierarchy).resolve()

    try:
        config, validation = load_canonical_config(
            name=args.name,
            psi_input_path=psi_path,
            planning_dir=planning_dir,
            product_hierarchy_path=prod_hierarchy,
            location_hierarchy_path=loc_hierarchy,
            include_validation=not args.skip_validation,
        )
    except CanonicalLoaderError as exc:
        print(f"[error] ロード失敗: {exc}", file=sys.stderr)
        return 2

    if validation and validation.has_errors and not args.allow_errors:
        for issue in validation.issues:
            print(
                f"[{issue.severity}] {issue.code}: {issue.message} {issue.context}",
                file=sys.stderr,
            )
        print(
            "検証エラーが発生したため中断しました (--allow-errorsで継続可能)",
            file=sys.stderr,
        )
        return 3

    print(f"[info] Canonical設定生成完了: {_summary(config)}")
    if validation:
        warn_cnt = sum(1 for i in validation.issues if i.severity == "warning")
        err_cnt = sum(1 for i in validation.issues if i.severity == "error")
        print(f"[info] validation: errors={err_cnt}, warnings={warn_cnt}")

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fp:
            json.dump(config.model_dump(mode="json"), fp, ensure_ascii=False, indent=2)
        print(f"[info] JSONを書き出しました: {output_path}")

    if args.save_db:
        try:
            version_id = save_canonical_config(config, db_path=args.db_path)
        except sqlite3.OperationalError as exc:
            print(
                f"[error] DB書き込みに失敗しました: {exc}. Alembicマイグレーションを適用してください。",
                file=sys.stderr,
            )
            return 4
        print(f"[info] DBへ保存しました: canonical_config_versions.id={version_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
