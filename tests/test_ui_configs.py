import importlib
import os

import pytest
from fastapi.testclient import TestClient

from app.api import app

importlib.import_module("app.ui_configs")

pytestmark = pytest.mark.slow


def test_ui_canonical_import_without_parent_id(db_setup):
    os.environ.setdefault("SCPLN_SKIP_STARTUP_SEED", "1")
    client = TestClient(app)
    response = client.get("/ui/configs/canonical/import")
    assert response.status_code == 200
    assert "Import Canonical Configuration" in response.text
