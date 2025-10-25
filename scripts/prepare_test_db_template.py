#!/usr/bin/env python3

"""Alembicマイグレーション済みのテスト用テンプレートDBを生成するユーティリティ。

AI-CLIなど非対話環境でpytest実行前に叩くことで、各テスト起動時のマイグレーション時間を短縮する。
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic.config import main as alembic_main


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_path = repo_root / "tmp" / "alembic_template" / "template.db"
    template_path.parent.mkdir(parents=True, exist_ok=True)

    alembic_ini = repo_root / "alembic.ini"
    if not alembic_ini.exists():
        raise FileNotFoundError(f"Alembic設定ファイルが見つかりません: {alembic_ini}")

    os.environ["SCPLN_DB"] = str(template_path)
    print(f"[prepare_test_db_template] apply alembic migrations to {template_path}")
    alembic_main(["-c", str(alembic_ini), "upgrade", "head"])
    print("[prepare_test_db_template] completed")


if __name__ == "__main__":
    main()
