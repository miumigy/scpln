from __future__ import annotations

import time
from fastapi.testclient import TestClient
from app.api import app


def test_plan_run_auto_redirects_to_new_plan():
    client = TestClient(app)
    base = f"base-{int(time.time())}"
    # まずベースのPlanを作って詳細画面を有効化
    r = client.post(
        "/plans/integrated/run",
        json={
            "version_id": base,
            "input_dir": "samples/planning",
            "weeks": 4,
            "round_mode": "int",
            "lt_unit": "day",
        },
        timeout=120,
    )
    assert r.status_code == 200
    # Plan & Run（自動補完）を叩く（anchor/tol付き）
    r2 = client.post(
        f"/ui/plans/{base}/plan_run_auto",
        data={
            "input_dir": "samples/planning",
            "weeks": 4,
            "lt_unit": "day",
            "cutover_date": "2025-01-15",
            "anchor_policy": "blend",
            "tol_abs": 1e-6,
            "tol_rel": 1e-6,
        },
        allow_redirects=False,
    )
    assert r2.status_code in (303, 302)
    loc = r2.headers.get("location", "")
    assert loc.startswith("/ui/plans/")
    # 遷移先が開ける
    r3 = client.get(loc)
    assert r3.status_code == 200

