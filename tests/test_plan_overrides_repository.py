import json

from app import db
from app.plans_api import (
    _get_locks,
    _get_overlay,
    _get_weights,
    _psi_overlay_key_agg,
    _save_weights,
    _save_locks,
    _save_overlay,
    get_plan_psi_events,
    get_plan_psi_weights,
    get_plan_psi_audit,
    get_plan_psi_state,
    _record_audit_event,
)
from core.plan_repository import PlanRepository
from app.metrics import (
    PLAN_DB_WRITE_LATENCY,
    PLAN_SERIES_ROWS_TOTAL,
    PLAN_DB_LAST_SUCCESS_TIMESTAMP,
)
from core.plan_repository_views import fetch_override_events


def test_overlay_and_lock_persisted_via_repository(db_setup):
    version_id = "plan-overrides-001"
    db.create_plan_version(version_id, status="active")

    overlay_data = {
        "aggregate": [
            {
                "period": "2025-01",
                "family": "F1",
                "demand": 120.0,
                "supply": 110.0,
                "backlog": 10.0,
            }
        ],
        "det": [],
    }

    actor = "test_user"
    note = "manual adjustment"
    _save_overlay(version_id, overlay_data, actor=actor, note=note)

    repo = PlanRepository(
        db._conn,
        PLAN_DB_WRITE_LATENCY,
        PLAN_SERIES_ROWS_TOTAL,
        PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    )
    overrides = repo.fetch_plan_overrides(version_id, "aggregate")
    assert overrides
    payload = overrides[0].get("payload_json")
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload["family"] == "F1"

    events = fetch_override_events(repo, version_id)
    assert events
    assert events[0]["event_type"] == "edit"
    assert events[0]["actor"] == actor
    assert events[0]["notes"] == note

    overlay = _get_overlay(version_id)
    assert overlay["aggregate"]
    assert overlay["aggregate"][0]["period"] == "2025-01"

    lock_key = _psi_overlay_key_agg("2025-01", "F1")
    _save_locks(version_id, {lock_key}, actor=actor, note=note)
    locks = _get_locks(version_id)
    assert lock_key in locks

    overrides_after = repo.fetch_plan_overrides(version_id, "aggregate")
    assert overrides_after
    assert bool(overrides_after[0].get("lock_flag")) is True

    events_after = fetch_override_events(repo, version_id)
    lock_events = [e for e in events_after if e["event_type"] in {"lock", "unlock"}]
    assert lock_events

    resp = get_plan_psi_events(version_id, level="aggregate", limit=10, offset=0)
    assert resp["total"] >= 1
    assert resp["events"][0]["actor"] == actor

    agg_audit = get_plan_psi_audit(version_id, level="aggregate", limit=5)
    assert agg_audit["events"], "expected aggregate audit events"
    agg_event = agg_audit["events"][0]
    assert agg_event["actor"] == actor
    assert agg_event["notes"] == note
    assert agg_event["display_event"] in {"edit", "lock"}
    assert "key_display" in agg_event
    assert "payload_preview" in agg_event

    # cleanup
    conn = db._conn()
    try:
        conn.execute(
            "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
        )
        conn.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_versions WHERE version_id=?", (version_id,))
        conn.commit()
    finally:
        conn.close()


def test_weights_persisted_via_repository(db_setup):
    version_id = "plan-weights-001"
    db.create_plan_version(version_id, status="active")
    actor = "weights_user"
    note = "weights update"
    weights = {
        "det:week=2025-01-W1,sku=SKU1": 0.4,
        "det:week=2025-01-W2,sku=SKU1": 0.6,
    }

    _save_weights(version_id, weights, actor=actor, note=note)

    repo = PlanRepository(
        db._conn,
        PLAN_DB_WRITE_LATENCY,
        PLAN_SERIES_ROWS_TOTAL,
        PLAN_DB_LAST_SUCCESS_TIMESTAMP,
    )
    overrides = repo.fetch_plan_overrides(version_id, "det")
    assert overrides
    stored_weights = _get_weights(version_id)
    assert stored_weights == weights

    events = fetch_override_events(repo, version_id, "det")
    weight_events = [e for e in events if e["event_type"] == "weight"]
    assert weight_events
    assert weight_events[0]["actor"] == actor
    assert weight_events[0]["notes"] == note

    resp = get_plan_psi_weights(version_id)
    keys = {row["key"] for row in resp["rows"]}
    assert keys == set(weights.keys())

    _record_audit_event(
        version_id,
        "submit",
        actor=actor,
        note=note,
        payload={"submitted_at": 1234567890},
    )
    det_audit = get_plan_psi_audit(version_id, level="det", limit=5)
    assert det_audit["events"], "expected detail audit events"
    det_event = det_audit["events"][0]
    assert det_event["display_event"] in {"weight", "lock", "edit"}
    assert det_event["actor"] == actor
    assert det_event["notes"] == note

    audit_resp = get_plan_psi_audit(version_id, level="audit", limit=5)
    assert audit_resp["events"], "expected audit-level events"
    audit_event = audit_resp["events"][0]
    assert audit_event["event_type"] == "submit"
    assert audit_event["actor"] == actor
    assert audit_event["display_event"] == "submit"
    state_resp = get_plan_psi_state(version_id)
    assert state_resp["source"] == "plan_repository"
    assert state_resp["state"]["status"] in {"pending", "approved"}
    assert state_resp["state"]["state"] == state_resp["state"]["status"]
    assert "display_status" in state_resp["state"]
    assert state_resp["state"].get("display_time")

    # cleanup
    conn = db._conn()
    try:
        conn.execute(
            "DELETE FROM plan_override_events WHERE version_id=?", (version_id,)
        )
        conn.execute("DELETE FROM plan_overrides WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_artifacts WHERE version_id=?", (version_id,))
        conn.execute("DELETE FROM plan_versions WHERE version_id=?", (version_id,))
        conn.commit()
    finally:
        conn.close()
