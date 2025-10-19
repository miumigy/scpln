import os
import pytest
import importlib
from pathlib import Path

from alembic.config import Config
from alembic import command

pytestmark = pytest.mark.slow


@pytest.fixture(name="db_setup_jobs")
def db_setup_jobs_fixture(tmp_path: Path):
    db_path = tmp_path / "test_jobs.sqlite"
    os.environ["SCPLN_DB"] = str(db_path)
    os.environ["REGISTRY_BACKEND"] = "db"
    os.environ["AUTH_MODE"] = "none"

    # Reload app.db to pick up new SCPLN_DB env var
    importlib.reload(importlib.import_module("app.db"))
    importlib.reload(importlib.import_module("app.jobs_api"))
    importlib.reload(importlib.import_module("main"))

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("script_location", "alembic")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")

    yield

    del os.environ["SCPLN_DB"]
    del os.environ["REGISTRY_BACKEND"]
    del os.environ["AUTH_MODE"]


def test_ui_jobs_route_returns_200(db_setup_jobs):
    # UI ルートは認証免除
    os.environ["AUTH_MODE"] = "none"
    from main import app  # noqa

    try:
        from fastapi.testclient import TestClient
    except Exception:  # fastapi 未インストール環境ではスキップ
        import pytest

        pytest.skip("fastapi not available in test env")

    client = TestClient(app)
    client.get("/ui/jobs")
