# Planning Input Sets Runbook

Codifies the operational flow for managing, approving, and auditing `planning_input_sets`. Use this when onboarding new input data, promoting it to production, or responding to warnings in Planning Hub.

## 1. Scope and prerequisites
- Covers Planning Hub (`/ui/plans/input_sets`), CLI utilities under `scripts/`, and REST endpoints exposed from `/api/plans/input_sets`.
- Applies to the normalized inputs stored in `planning_input_sets` (demand, capacity, mix, inventory, inbound, metrics, calendar, params).
- Operators need shell access to run the CLI via `.venv`, plus sufficient UI/API permissions.

## 2. Lifecycle and statuses

| Status  | Purpose | Entry point / transition |
|---------|---------|--------------------------|
| `draft` | Fresh uploads awaiting review. Multiple iterations allowed. | Created by the UI upload form or `scripts/import_planning_inputs.py`, which defaults to `status="draft"` and logs an `upload` event. |
| `ready` | Approved set available to plan creation, runs, and exports. | Promoted via the UI review form (`/ui/plans/input_sets/{label}/review`) after validation. |
| `archived` | Retired set kept for traceability only. | Assigned manually through `update_planning_input_set` (not exposed in UI) once no plan/run references remain. |

Each status transition records an event in `planning_input_set_events` alongside `approved_by`, `approved_at`, and `review_comment`.

## 3. Approval workflow

1. **Upload / update**
   - Run `PYTHONPATH=. .venv/bin/python scripts/import_planning_inputs.py -i <dir> --version-id <id> --label <label>` to register or replace data. The CLI writes `tmp/reports/import_planning_inputs.json` with row counts and validation notes.
   - Alternatively, upload CSV/JSON bundles under “Planning > Input Sets > Upload”. Files are staged to a temp directory and stored as a draft InputSet.
2. **Diff + validation**
   - Navigate to `/ui/plans/input_sets/{label}/diff` to compare against a reference set. The first access spawns an async job and caches the JSON report under `tmp/input_set_diffs/`.
   - Resolve validation errors in the upload summary or CLI output before proceeding.
3. **Approval (Draft → Ready)**
   - Open the InputSet detail page, switch to the “Review” tab, and submit the Approve form:
     - `Action`: `Approve`.
     - `Reviewer`: corporate ID (defaults to `ui_reviewer` if left blank).
     - `Comment`: recommended format `JIRA-123 approve by ops_lead`.
   - The UI stamps `approved_by/approved_at`, logs an `approve` event, and updates the status to `ready`.
4. **Revert (Ready → Draft)**
   - Use the same form with `Action=Revert` to demote the set when issues are discovered. This clears the approval metadata and logs a `revert` event.

### CLI-only approval
If the UI is unreachable, issue a short Python snippet that calls `core.config.storage.update_planning_input_set(...)` with `status="ready"` and the appropriate metadata. Always follow up with `log_planning_input_set_event` so the audit trail remains consistent with UI-driven actions.

## 4. Audit evidence collection

1. **Daily/weekly capture**
   - UI: Take a screenshot of the History table (Action/Actor/Comment/JST) and store it alongside the JSON dump.
   - CLI: execute
     ```bash
     PYTHONPATH=. .venv/bin/python scripts/show_planning_input_events.py \
       --label weekly_refresh --limit 100 --json \
       > tmp/audit/input-set-weekly_refresh-$(date +%Y%m%d).json
     ```
   - REST: `curl -H "Authorization: Bearer $TOKEN" "https://<host>/api/plans/input_sets/weekly_refresh/events?limit=100" | jq '.'` when automation is preferred.
2. **Evidence repository**
   - Move artifacts into `evidence/input_sets/<label>/<YYYYMMDD>/`:
     - `events.json` → CLI/REST output.
     - `history.png` → UI capture.
   - Keep the `evidence/` tree outside git (already ignored) and sync it to secure storage (e.g., weekly S3 upload).
3. **Troubleshooting**
   - `Input set 'foo' not found.` indicates a typo or a draft label (e.g., `foo@draft`). Use `scripts/list_planning_input_sets.py` or copy the label from the UI card.
   - Empty event lists imply missing logging. Re-run the importer with event logging enabled or append a manual event via `log_planning_input_set_event`.

## 5. Handling plan/run warnings

| Warning | Meaning | Remediation |
|---------|---------|-------------|
| `Legacy mode` | Plan/Run lacks `input_set_label`. | Re-run the plan referencing an approved InputSet. If rerun is impossible, attach the exported CSV bundle plus a note explaining why Legacy mode was allowed. |
| `Missing InputSet` | Label recorded on the plan/run no longer resolves in storage. | Re-import the archived files (exported earlier) with the same label, or update affected plans to a new ready set. |

Steps:
1. Inspect the warning card on Plan or Run detail pages for suggested commands.
2. Re-import the last known CSV bundle: `PYTHONPATH=. .venv/bin/python scripts/import_planning_inputs.py -i out/planning_inputs_<label> --version-id <id> --label <label>`.
3. If the warning persists, download the plan artifact `planning_input_set.json` from the Run detail page, verify hashes, and coordinate with SRE before overriding protections.
- Monitoring: alert on `run_without_input_set_total{entrypoint="/runs"}` spikes (e.g., >5 in 10 minutes) and `plan_artifact_write_error_total{artifact="planning_input_set.json"}` increments; both should stay at 0 during steady-state operations.

## 6. Diff job monitoring & remediation

- Logs: `rg -n "input_set_diff_job_failed" uvicorn.out datasette.out` to spot failures. Include `diff_job_id` when filing incidents.
- Cache health: remove stale cache pairs via `rm tmp/input_set_diffs/<label>__<against>.json` and reopen the diff page to trigger regeneration.
- Metrics:
  - `input_set_diff_jobs_total{result="success|failure"}` to monitor async job outcomes (alert on `result="failure"` ≥3 within 5 minutes).
  - `input_set_diff_cache_hits_total` / `input_set_diff_cache_stale_total` to watch cache efficiency.
  - Publish both series to Prometheus/Grafana and include them on the Planning Inputs dashboard.

## 7. References
- CLI cheatsheet in `README.md` / `README_JA.md`.
- Design + backlog: `docs/temp_planning_inputs_visibility.md`.
- Alert escalation: Slack `#planning-alert` for diff jobs, `#scpln-ops` for legacy/fallback incidents.
