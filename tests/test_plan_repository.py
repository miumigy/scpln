from __future__ import annotations

import time

import logging


from app import db
from core.plan_repository import PlanRepository
from core.plan_repository_builders import (
    build_plan_kpis_from_aggregate,
    build_plan_series,
)


def test_plan_repository_write_and_read(db_setup):
    repo = PlanRepository(db._conn)
    version_id = "plan-test-001"
    now = int(time.time() * 1000)

    db.create_plan_version(version_id, status="active", cutover_date="2025-01-01")

    job_id = "job-plan-001"
    db.create_job(job_id, "planning", "queued", now, None)

    series_rows = [
        {
            "version_id": version_id,
            "level": "aggregate",
            "time_bucket_type": "week",
            "time_bucket_key": "2025-W01",
            "item_key": "FAMILY-A",
            "location_key": "SITE-A",
            "demand": 120.0,
            "supply": 110.0,
            "backlog": 10.0,
            "cutover_flag": True,
            "created_at": now,
            "updated_at": now,
        }
    ]

    overrides = [
        {
            "version_id": version_id,
            "level": "aggregate",
            "key_hash": "agg:period=2025-W01,family=FAMILY-A",
            "payload_json": '{"demand": 125.0}',
            "lock_flag": True,
            "locked_by": "planner",
            "created_at": now,
            "updated_at": now,
        }
    ]

    kpi_rows = [
        {
            "version_id": version_id,
            "metric": "fill_rate",
            "bucket_type": "week",
            "bucket_key": "2025-W01",
            "value": 0.92,
            "unit": "ratio",
            "created_at": now,
            "updated_at": now,
        }
    ]

    job_row = {
        "job_id": job_id,
        "version_id": version_id,
        "status": "succeeded",
        "submitted_at": now,
        "started_at": now,
        "finished_at": now + 1000,
        "duration_ms": 1000,
        "retry_count": 0,
        "trigger": "api",
    }

    repo.write_plan(
        version_id,
        series=series_rows,
        overrides=overrides,
        kpis=kpi_rows,
        job=job_row,
    )

    fetched_series = repo.fetch_plan_series(version_id, "aggregate")
    assert len(fetched_series) == 1
    assert fetched_series[0]["demand"] == 120.0
    assert fetched_series[0]["cutover_flag"] is True

    fetched_overrides = repo.fetch_plan_overrides(version_id)
    assert len(fetched_overrides) == 1
    assert fetched_overrides[0]["lock_flag"] is True

    fetched_kpis = repo.fetch_plan_kpis(version_id)
    assert len(fetched_kpis) == 1
    assert fetched_kpis[0]["metric"] == "fill_rate"

    fetched_jobs = repo.fetch_plan_jobs(version_id=version_id)
    assert len(fetched_jobs) == 1
    assert fetched_jobs[0]["status"] == "succeeded"

    repo.delete_plan(version_id)
    assert repo.fetch_plan_series(version_id, "aggregate") == []
    assert repo.fetch_plan_overrides(version_id) == []
    assert repo.fetch_plan_kpis(version_id) == []
    assert repo.fetch_plan_jobs(version_id=version_id) == []


def test_plan_repository_write_with_builders(db_setup):
    repo = PlanRepository(db._conn)
    version_id = "plan-builders-001"
    aggregate = {
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "demand": 100,
                "supply": 90,
                "backlog": 10,
            },
            {
                "family": "F1",
                "period": "2025-02",
                "demand": 120,
                "supply": 120,
                "backlog": 0,
            },
        ]
    }
    detail = {
        "rows": [
            {
                "family": "F1",
                "period": "2025-01",
                "sku": "SKU1",
                "week": "2025-01-W1",
                "demand": 25,
                "supply": 20,
                "backlog": 5,
            }
        ]
    }

    db.create_plan_version(version_id, status="active")
    series_rows = build_plan_series(version_id, aggregate=aggregate, detail=detail)
    kpi_rows = build_plan_kpis_from_aggregate(version_id, aggregate)

    repo.write_plan(version_id, series=series_rows, kpis=kpi_rows)

    stored_series = repo.fetch_plan_series(version_id, "aggregate")
    assert stored_series
    assert stored_series[0]["time_bucket_type"] == "month"
    stored_detail = repo.fetch_plan_series(version_id, "det")
    assert stored_detail
    assert stored_detail[0]["item_key"] == "SKU1"
    stored_kpi = repo.fetch_plan_kpis(version_id, metric="fill_rate")
    assert stored_kpi


def test_fetch_plan_series_natural_sort(db_setup):
    repo = PlanRepository(db._conn)
    version_id = "plan-sort-001"
    now = int(time.time() * 1000)
    db.create_plan_version(version_id, status="active")

    buckets = ["M1", "M10", "M2"]
    series_rows = [
        {
            "version_id": version_id,
            "level": "aggregate",
            "time_bucket_type": "month",
            "time_bucket_key": bucket,
            "item_key": "FAMILY-SORT",
            "location_key": "SITE-1",
            "demand": 100.0 + idx * 10,
            "supply": 90.0 + idx * 5,
            "backlog": 5.0,
            "created_at": now,
            "updated_at": now,
        }
        for idx, bucket in enumerate(buckets)
    ]
    kpi_rows = [
        {
            "version_id": version_id,
            "metric": "fill_rate",
            "bucket_type": "month",
            "bucket_key": bucket,
            "value": 0.9,
            "unit": "ratio",
            "created_at": now,
            "updated_at": now,
        }
        for bucket in buckets
    ]

    repo.write_plan(version_id, series=series_rows, kpis=kpi_rows)

    fetched_series = repo.fetch_plan_series(version_id, "aggregate")
    assert [row["time_bucket_key"] for row in fetched_series] == ["M1", "M2", "M10"]

    fetched_kpis = repo.fetch_plan_kpis(version_id)
    assert [row["bucket_key"] for row in fetched_kpis] == ["M1", "M2", "M10"]


def test_plan_repository_capacity_guard_trims_old_versions(db_setup, monkeypatch):
    monkeypatch.setenv("PLANS_DB_MAX_ROWS", "2")
    repo = PlanRepository(db._conn)
    base_ts = int(time.time() * 1000)

    for idx in range(3):
        version_id = f"plan-guard-{idx}"
        db.create_plan_version(version_id, status="active")
        series_rows = [
            {
                "version_id": version_id,
                "level": "aggregate",
                "time_bucket_type": "week",
                "time_bucket_key": f"2025-W{idx:02d}",
                "item_key": f"F{idx}",
                "location_key": "SITE",
                "demand": 10.0,
                "supply": 10.0,
                "backlog": 0.0,
            }
        ]
        repo.write_plan(version_id, series=series_rows)
        with db._conn() as conn:
            conn.execute(
                "UPDATE plan_versions SET created_at=? WHERE version_id=?",
                (base_ts + idx, version_id),
            )

    remaining = {p["version_id"] for p in db.list_plan_versions(limit=10)}
    assert len(remaining) == 2
    assert "plan-guard-0" not in remaining
    assert "plan-guard-1" in remaining
    assert "plan-guard-2" in remaining
    assert repo.fetch_plan_series("plan-guard-0", "aggregate") == []
    assert db.get_plan_version("plan-guard-0") is None


class _DummyCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, str], float]] = []

    def labels(self, **labels):
        return _DummyCounterHandle(self, labels)

    def inc(self, value: float = 1.0):
        self.calls.append(({}, value))


class _DummyCounterHandle:
    def __init__(self, parent: _DummyCounter, labels: dict[str, str]):
        self._parent = parent
        self._labels = labels

    def inc(self, value: float = 1.0):
        self._parent.calls.append((self._labels, value))


class _DummyGauge:
    def __init__(self) -> None:
        self.value: float | None = None

    def set(self, value: float):
        self.value = value


def test_plan_repository_capacity_guard_alert(monkeypatch, db_setup, caplog):
    monkeypatch.setenv("PLANS_DB_MAX_ROWS", "1")
    monkeypatch.setenv("PLANS_DB_GUARD_ALERT_THRESHOLD", "1")
    counter = _DummyCounter()
    gauge = _DummyGauge()
    repo = PlanRepository(
        db._conn,
        plan_db_guard_trim_total=counter,
        plan_db_last_trim_timestamp=gauge,
    )

    caplog.set_level(logging.WARNING)

    for idx in range(2):
        vid = f"trim-alert-{idx}"
        db.create_plan_version(vid, status="active")
        repo.write_plan(
            vid,
            series=[
                {
                    "version_id": vid,
                    "level": "aggregate",
                    "time_bucket_type": "week",
                    "time_bucket_key": f"2025-W{idx:02d}",
                    "item_key": "F",
                    "location_key": "LOC",
                    "demand": 5.0,
                    "supply": 5.0,
                    "backlog": 0.0,
                }
            ],
        )

    assert counter.calls, "counter should record trim"
    assert counter.calls[-1][0].get("reason", "") == "max_rows"
    assert gauge.value is not None
    assert any(
        r.levelno == logging.WARNING
        and "plan_repository_capacity_trim_alert" in r.getMessage()
        for r in caplog.records
    )
