import os


def test_ui_jobs_route_returns_200():
    # UI ルートは認証免除
    os.environ["AUTH_MODE"] = "none"
    from main import app  # noqa
    try:
        from fastapi.testclient import TestClient
    except Exception:  # fastapi 未インストール環境ではスキップ
        import pytest
        pytest.skip("fastapi not available in test env")

    client = TestClient(app)
    res = client.get("/ui/jobs")
    assert res.status_code == 200
