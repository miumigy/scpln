"""
互換用の薄いモジュール。
既定の /runs 系エンドポイントは app.run_compare_api に統合しました。
このモジュールの import は app.run_compare_api を副作用 import します。
"""

from app import run_compare_api as _run_compare_api  # noqa: F401
