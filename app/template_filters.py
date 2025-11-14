from __future__ import annotations

from fastapi.templating import Jinja2Templates

from app.utils import (
    format_datetime,
    format_metric,
    format_number,
    format_percent,
    to_json,
)


def register_format_filters(templates: Jinja2Templates) -> None:
    """Jinja2テンプレートへ標準フォーマッタを登録。"""
    env = templates.env
    env.filters.setdefault("fmt_number", format_number)
    env.filters.setdefault("fmt_percent", format_percent)
    env.filters.setdefault("fmt_metric", format_metric)
    env.filters.setdefault("format_datetime", format_datetime)
    env.filters.setdefault("to_json", to_json)
