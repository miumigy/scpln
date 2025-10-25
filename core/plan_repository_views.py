"""PlanRepositoryビュー層のサポートユーティリティ。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .plan_repository import PlanRepository


def _load_extra(row: Dict[str, Any]) -> Dict[str, Any]:
    data = row.get("extra_json")
    if not data:
        return {}
    if isinstance(data, dict):
        return data
    try:
        return json.loads(data)
    except Exception:
        return {}


def fetch_aggregate_rows(repo: PlanRepository, version_id: str) -> List[Dict[str, Any]]:
    rows = repo.fetch_plan_series(version_id, "aggregate")
    result: list[Dict[str, Any]] = []
    for row in rows:
        extra = _load_extra(row)
        result.append(
            {
                "family": row.get("item_key"),
                "period": row.get("time_bucket_key"),
                "demand": row.get("demand"),
                "supply": row.get("supply"),
                "backlog": row.get("backlog"),
                "cost_total": row.get("cost_total"),
                "capacity_total": extra.get("capacity_total")
                or row.get("capacity_used"),
            }
        )
    return result


def fetch_detail_rows(repo: PlanRepository, version_id: str) -> List[Dict[str, Any]]:
    rows = repo.fetch_plan_series(version_id, "det")
    result: list[Dict[str, Any]] = []
    for row in rows:
        extra = _load_extra(row)
        result.append(
            {
                "family": extra.get("family"),
                "period": extra.get("period"),
                "sku": row.get("item_key"),
                "week": row.get("time_bucket_key"),
                "demand": row.get("demand"),
                "supply_plan": row.get("supply"),
                "backlog": row.get("backlog"),
                "on_hand_start": extra.get("on_hand_start"),
                "on_hand_end": extra.get("on_hand_end"),
            }
        )
    return result


def fetch_overrides_by_level(
    repo: PlanRepository, version_id: str, level: str
) -> List[Dict[str, Any]]:
    rows = repo.fetch_plan_overrides(version_id, level)
    result: list[Dict[str, Any]] = []
    for row in rows:
        payload_raw = row.get("payload_json")
        if isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}
        elif isinstance(payload_raw, dict):
            payload = payload_raw
        else:
            payload = {}
        result.append(
            {
                "key_hash": row.get("key_hash"),
                "payload": payload,
                "lock_flag": bool(row.get("lock_flag")),
                "locked_by": row.get("locked_by"),
                "weight": row.get("weight"),
                "author": row.get("author"),
                "source": row.get("source"),
                "updated_at": row.get("updated_at"),
                "id": row.get("id"),
            }
        )
    return result


def fetch_override_events(
    repo: PlanRepository, version_id: str, level: str | None = None
) -> List[Dict[str, Any]]:
    rows = repo.fetch_plan_override_events(version_id)
    result: list[Dict[str, Any]] = []
    for row in rows:
        if level and row.get("level") != level:
            continue
        payload_raw = row.get("payload_json")
        if isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}
        elif isinstance(payload_raw, dict):
            payload = payload_raw
        else:
            payload = {}
        result.append(
            {
                "event_id": row.get("id"),
                "override_id": row.get("override_id"),
                "version_id": row.get("version_id"),
                "level": row.get("level"),
                "key_hash": row.get("key_hash"),
                "event_type": row.get("event_type"),
                "event_ts": row.get("event_ts"),
                "payload": payload,
                "actor": row.get("actor"),
                "notes": row.get("notes"),
            }
        )
    return result


def _to_timestamp_fields(ts_raw: Any) -> tuple[Optional[int], Optional[str]]:
    if ts_raw is None:
        return None, None
    try:
        ts_int = int(ts_raw)
    except Exception:
        return None, None
    try:
        dt = datetime.fromtimestamp(ts_int / 1000, tz=timezone.utc)
        display = dt.isoformat().replace("+00:00", "Z")
    except Exception:
        display = None
    return ts_int, display


def _payload_to_dict(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
            return data if isinstance(data, dict) else {"value": data}
        except Exception:
            return {"raw": payload}
    return {}


def _payload_preview(payload: Dict[str, Any], *, limit: int = 160) -> str:
    if not payload:
        return ""
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(payload)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _derive_key(level: Optional[str], payload: Dict[str, Any], key_hash: Any) -> str:
    if level == "aggregate":
        period = payload.get("period")
        family = payload.get("family")
        if period or family:
            return f"{period or '-'} / {family or '-'}"
    elif level == "det":
        week = payload.get("week")
        sku = payload.get("sku")
        if week or sku:
            return f"{week or '-'} / {sku or '-'}"
    return str(key_hash or "")


def summarize_audit_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summarized: list[Dict[str, Any]] = []
    label_map = {
        "edit": "edit",
        "lock": "lock",
        "unlock": "unlock",
        "weight": "weight",
        "submit": "submit",
        "approve": "approve",
    }
    for ev in events:
        event_type = str(ev.get("event_type") or ev.get("event") or "unknown")
        payload = _payload_to_dict(
            ev.get("payload") or ev.get("payload_json") or ev.get("fields") or {}
        )
        if not payload and ev.get("lock") is not None:
            payload = {"lock": ev.get("lock")}
        event_ts, display_time = _to_timestamp_fields(
            ev.get("event_ts") or ev.get("timestamp") or ev.get("ts")
        )
        actor = ev.get("actor") or ev.get("author")
        notes = ev.get("notes") or ev.get("note")
        level = ev.get("level")
        key_hash = ev.get("key_hash") or ev.get("key")
        summarized.append(
            {
                "event_id": ev.get("event_id") or ev.get("id") or ev.get("override_id"),
                "event_type": event_type,
                "timestamp": event_ts,
                "display_time": display_time,
                "actor": actor,
                "notes": notes,
                "level": level,
                "key_hash": key_hash,
                "key_display": _derive_key(level, payload, key_hash),
                "payload": payload,
                "payload_preview": _payload_preview(payload),
                "display_event": label_map.get(event_type, event_type),
            }
        )
    return summarized


def latest_state_from_events(events: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    sorted_events = sorted(
        events,
        key=lambda e: (int(e.get("event_ts") or 0), e.get("event_id") or 0),
        reverse=True,
    )
    for ev in sorted_events:
        etype = ev.get("event_type")
        if etype == "approve":
            payload = _payload_to_dict(ev.get("payload"))
            event_ts, display_time = _to_timestamp_fields(ev.get("event_ts"))
            approved_at = payload.get("approved_at") or event_ts
            return {
                "status": "approved",
                "approved_at": approved_at,
                "auto_reconcile": payload.get("auto_reconcile"),
                "actor": ev.get("actor"),
                "notes": ev.get("notes"),
                "event_id": ev.get("event_id"),
                "timestamp": event_ts,
                "display_time": display_time,
                "display_status": "approved",
                "state": "approved",
            }
        if etype == "submit":
            payload = _payload_to_dict(ev.get("payload"))
            event_ts, display_time = _to_timestamp_fields(ev.get("event_ts"))
            submitted_at = payload.get("submitted_at") or event_ts
            return {
                "status": "pending",
                "submitted_at": submitted_at,
                "actor": ev.get("actor"),
                "notes": ev.get("notes"),
                "event_id": ev.get("event_id"),
                "timestamp": event_ts,
                "display_time": display_time,
                "display_status": "pending",
                "state": "pending",
            }
    return None


def build_plan_summaries(
    repo: PlanRepository,
    version_ids: Iterable[str],
    *,
    include_kpi: bool = True,
) -> dict[str, dict[str, Any]]:
    version_ids = list(dict.fromkeys(version_ids))
    if not version_ids:
        return {}

    stats_map = repo.fetch_series_stats(version_ids)
    kpi_map = repo.fetch_plan_kpi_totals(version_ids) if include_kpi else {}

    summaries: dict[str, dict[str, Any]] = {}

    for vid in version_ids:
        level_stats = stats_map.get(vid, {})
        series_summary: dict[str, dict[str, Any]] = {}
        last_updated = 0
        for level, values in level_stats.items():
            entry: dict[str, Any] = {
                "rows": values.get("row_count", 0),
                "demand_total": values.get("demand_sum", 0.0),
                "supply_total": values.get("supply_sum", 0.0),
                "backlog_total": values.get("backlog_sum", 0.0),
            }
            if values.get("capacity_sum") is not None:
                entry["capacity_total"] = values.get("capacity_sum")
            if level == "weekly_summary":
                capacity = values.get("capacity_sum") or 0.0
                adjusted = values.get("supply_sum") or 0.0
                entry["utilization_pct"] = (
                    (adjusted / capacity * 100.0) if capacity else None
                )
            if level == "aggregate":
                demand = values.get("demand_sum") or 0.0
                supply = values.get("supply_sum") or 0.0
                entry["fill_rate"] = (supply / demand) if demand else 1.0
            series_summary[level] = entry
            last_updated = max(last_updated, values.get("max_updated_at", 0))

        summary: dict[str, Any] = {"series": series_summary}
        if last_updated:
            summary["last_updated_at"] = last_updated
        if include_kpi and vid in kpi_map:
            summary["kpi"] = kpi_map[vid]

        summary["series_rows"] = int(
            sum(entry.get("rows", 0) for entry in series_summary.values())
        )
        summary["storage"] = {
            "plan_repository": bool(series_summary),
        }
        summaries[vid] = summary

    return summaries
