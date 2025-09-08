from __future__ import annotations

from fastapi.testclient import TestClient
from app.api import app


def test_planning_legacy_close_404(monkeypatch):
    monkeypatch.setenv("HUB_LEGACY_CLOSE", "1")
    client = TestClient(app)
    r = client.get("/ui/planning")
    # legacy close → 404 with guide page
    assert r.status_code == 404
    body = r.text
    assert "/ui/plans" in body
    # allow_legacy=1 overrides 404
    r2 = client.get("/ui/planning?allow_legacy=1")
    # either redirect to /ui/plans (Phase 2) or legacy rendered; but not 404
    assert r2.status_code != 404
