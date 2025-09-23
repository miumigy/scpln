"""Canonicalテスト用設定を生成し、DB登録やJSON出力を行うスクリプト。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import CanonicalConfig, load_canonical_config
from core.config.storage import save_canonical_config


def _build_config(
    *,
    name: str,
    psi_input_path: Path,
    planning_dir: Path,
    product_hierarchy_path: Path,
    location_hierarchy_path: Path,
) -> CanonicalConfig:
    config, validation = load_canonical_config(
        name=name,
        psi_input_path=psi_input_path,
        planning_dir=planning_dir,
        product_hierarchy_path=product_hierarchy_path,
        location_hierarchy_path=location_hierarchy_path,
        include_validation=True,
    )
    if validation and validation.has_errors:
        messages = [f"{issue.code}: {issue.message}" for issue in validation.issues]
        raise RuntimeError("canonical validation failed: " + ", ".join(messages))
    return config


def _export_json(config: CanonicalConfig, export_path: Path) -> None:
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(
        json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Canonicalサンプル設定を生成し、DB登録やJSON出力を行います。"
    )
    parser.add_argument("--name", default="canonical-sample", help="生成する設定名")
    parser.add_argument(
        "--psi-input",
        type=Path,
        default=Path("static/default_input.json"),
        help="PSI入力JSONのパス",
    )
    parser.add_argument(
        "--planning-dir",
        type=Path,
        default=Path("samples/planning"),
        help="Planning用CSVディレクトリ",
    )
    parser.add_argument(
        "--product-hierarchy",
        type=Path,
        default=Path("configs/product_hierarchy.json"),
        help="品目階層JSONのパス",
    )
    parser.add_argument(
        "--location-hierarchy",
        type=Path,
        default=Path("configs/location_hierarchy.json"),
        help="ロケーション階層JSONのパス",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite DBパス（未指定時は既定DB）",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="生成したCanonicalConfigをJSONで保存するパス",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="DBへ保存せずJSON出力のみ行う",
    )

    args = parser.parse_args()

    config = _build_config(
        name=args.name,
        psi_input_path=args.psi_input,
        planning_dir=args.planning_dir,
        product_hierarchy_path=args.product_hierarchy,
        location_hierarchy_path=args.location_hierarchy,
    )
    print(
        "canonical config generated: "
        f"items={len(config.items)}, nodes={len(config.nodes)}, demands={len(config.demands)}"
    )

    if args.export:
        _export_json(config, args.export)
        print(f"canonical config exported: {args.export}")

    if args.no_save:
        return

    db_path = str(args.db) if args.db else None
    version_id = save_canonical_config(
        config,
        db_path=db_path,
    )
    if db_path:
        print(f"canonical config saved: version_id={version_id} (db={db_path})")
    else:
        from app.db import DB_PATH  # lazy import to avoid heavy deps

        print("canonical config saved: " f"version_id={version_id} (db={DB_PATH})")


if __name__ == "__main__":
    main()
