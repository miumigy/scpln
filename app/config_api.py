"""Legacy /configs API へのリクエストに 410 Gone を返すガードモジュール。"""

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
