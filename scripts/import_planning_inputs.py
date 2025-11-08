#!/usr/bin/env python3
"""
samples/planning 互換CSV/JSONから PlanningInputSet を生成し DB に登録するCLI。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config.importer import import_planning_inputs

def run() -> int:
    args = parse_args()
    directory = Path(args.input_dir).resolve()
    label = args.label or f"import_{directory.name}"
    config_version_id = args.version_id or args.new_version_id

    if not config_version_id:
        print("--version-id or --new-version-id is required", file=sys.stderr)
        return 1

    result = import_planning_inputs(
        directory=directory,
        config_version_id=config_version_id,
        label=label,
        apply_mode=args.apply_mode,
        validate_only=args.validate_only,
    )

    if result["status"] == "error":
        print(f"Failed to import planning inputs: {result['message']}", file=sys.stderr)
        return 2

    _emit_result(result, args)
    return 0


def _emit_result(result: Dict[str, Any], args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(result))
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(run())
