import re
from unittest import mock

import pytest

from app.metrics import metrics_snapshot, start_metrics_server

pytestmark = pytest.mark.slow


def test_metrics_snapshot_contains_prometheus_text():
    resp = metrics_snapshot()
    assert resp.status_code == 200
    ctype = resp.media_type or ""
    assert "text/plain" in ctype
    assert any(ver in ctype for ver in ("version=0.0.4", "version=1.0.0"))
    body = resp.body.decode("utf-8")
    assert "# HELP" in body
    assert re.search(r"\nprocess_.+?s", body) is not None


def test_start_metrics_server_runs_without_error(monkeypatch):
    monkeypatch.setenv("METRICS_PORT", "9105")
    with mock.patch("app.metrics.start_http_server") as mock_srv:
        start_metrics_server()
        mock_srv.assert_called_once()
