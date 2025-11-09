import re

import pytest

from app.metrics import metrics_snapshot

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
