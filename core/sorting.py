"""共通のNatural Sortキー生成ユーティリティ。"""

from __future__ import annotations

import re
from typing import Any, Tuple

_TOKEN_PATTERN = re.compile(r"(\d+)")


def natural_sort_key(value: Any) -> Tuple[Tuple[int, object], ...]:
    """文字列中の数値を数値として扱うソートキーを生成する。"""
    if value is None:
        return ((2, ""),)
    if isinstance(value, bool):
        return ((0, str(value)),)
    if isinstance(value, int):
        return ((1, value),)
    if isinstance(value, float):
        return ((1, value),)

    text = str(value)
    tokens: list[Tuple[int, object]] = []
    for part in _TOKEN_PATTERN.split(text):
        if not part:
            continue
        if part.isdigit():
            tokens.append((1, int(part)))
        else:
            tokens.append((0, part))
    if not tokens:
        tokens.append((0, text))
    return tuple(tokens)
