"""Legacy /configs API へのリクエストに 410 Gone を返すガードモジュール。"""


def _list_canonical_options(limit: int = 50):
    """Canonical Config を選択するためのドロップダウン用リストを返す。"""
    from core.config import list_canonical_version_summaries

    summaries = list_canonical_version_summaries(limit=limit, include_deleted=False)
    options = []
    for summary in summaries:
        meta = summary.meta
        version_id = meta.version_id
        if version_id is None:
            continue
        label = meta.name
        if meta.version_tag:
            label = f"{label} ({meta.version_tag})"
        calendar_count = summary.counts.get("calendars", 0)
        options.append(
            {
                "id": version_id,
                "version_id": version_id,
                "label": label,
                "num_calendars": calendar_count,
            }
        )
    return options


from fastapi import HTTPException

from app.api import app


def _gone(detail: str = "Legacy /configs API は廃止されました。"):  # pragma: no cover
    raise HTTPException(status_code=410, detail=detail)


@app.get("/configs")
def legacy_configs_list():
    _gone()


@app.get("/configs/{cfg_id}")
def legacy_configs_get(cfg_id: int):  # noqa: ARG001 - 互換性保持のため引数は維持
    _gone()


@app.post("/configs")
def legacy_configs_create():
    _gone()


@app.put("/configs/{cfg_id}")
def legacy_configs_update(cfg_id: int):  # noqa: ARG001
    _gone()


@app.delete("/configs/{cfg_id}")
def legacy_configs_delete(cfg_id: int):  # noqa: ARG001
    _gone()
