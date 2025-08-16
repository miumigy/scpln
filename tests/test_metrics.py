import re
import importlib

# 副作用 import で /metrics を登録
importlib.import_module("app.metrics")

from fastapi.testclient import TestClient
from app.api import app


def test_metrics_endpoint_works():
    client = TestClient(app)
    r = client.get("/metrics")
    assert r.status_code == 200
    # Content-Type は Prometheus テキストフォーマット
    ctype = r.headers.get("content-type", "")
    assert "text/plain" in ctype
    assert "version=0.0.4" in ctype  # Prometheus exposition format version
    # 代表的な行が含まれていること（# HELP と process_ 系）
    body = r.text
    assert "# HELP" in body
    assert re.search(r"\nprocess_.+?s", body) is not None
