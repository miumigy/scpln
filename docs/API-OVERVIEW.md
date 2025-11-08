# API Overview (Planning Hub & RunRegistry)

This summary highlights the primary REST and CSV endpoints used by the Planning Hub, planning pipelines, and the RunRegistry that stores simulation runs. For terminology see `docs/TERMS.md`, for workflows refer to `docs/TUTORIAL.md`, and for authentication and secret rotation consult the README and `docs/SECRET_ROTATION.md`.

## Health and metrics
- `GET /healthz`: health check.
- `GET /metrics`: Prometheus metrics such as `plans_created_total`.

## Planning Hub UI (HTML)
- `GET /ui/plans`: plan list (includes creation form).
- `POST /ui/plans/create_and_execute`: synchronous integrated execution to create a new plan.
- `GET /ui/plans/{version_id}`: plan detail (tabs: Overview / Aggregate / Disaggregate / Schedule / Validate / Execute / Results).
- `POST /ui/plans/{version_id}/execute_auto`: “Plan & Execute” shortcut that creates a plan via `/runs` with auto-filled parameters.
- `POST /ui/plans/{version_id}/reconcile`: trigger reconciliation (optionally anchored/adjusted).
- `POST /ui/plans/{version_id}/state/advance` and `/state/invalidate`: advance or invalidate plan states.

## Planning API (JSON/CSV)
- `GET /plans`: list registered plans.
- `POST /plans/create_and_execute`: run the integrated pipeline (aggregate → allocate → mrp → reconcile) and register a new plan. Set `lightweight=true` to skip heavy MRP/reconcile steps for CI/E2E, while still writing to the PlanRepository and producing key artifacts.
- `GET /plans/{version_id}/summary`: retrieve plan summaries (reconciliation summary / weekly summary).
- `DELETE /plans/{version_id}`: delete a plan, cleaning up PlanRepository rows, artifacts, and run references.
- `GET /plans/{version_id}/compare`: list deltas (supports `violations_only`, `sort`, `limit`).
- `GET /plans/{version_id}/compare.csv`: CSV export for the above.
- `GET /plans/{version_id}/carryover.csv`: export anchor/carryover transitions.
- `GET /plans/{version_id}/schedule.csv`: export planned orders (from `mrp.json`).
- `POST /plans/{version_id}/reconcile`: evaluate aggregate × detail reconciliation (before/adjusted).

## Run API (RunRegistry & execution)

These endpoints execute simulations (runs) and persist, retrieve, or compare the results stored in the RunRegistry.

- **`GET /runs`**: fetch run history.
  - `detail=true`: return full payloads including detailed metrics.
  - `limit`, `offset`: pagination.
  - `sort`, `order`: sort by keys such as `started_at`.
  - Filter by `config_version_id`, `scenario_id`, `plan_version_id`, etc.

- **`POST /runs`**: execute a new run synchronously or asynchronously, typically with the integrated pipeline (`pipeline: "integrated"`).
  - `async=true`: enqueue a background job and return a `job_id`.
  - `async=false` (default): run synchronously and return the plan `version_id` once complete.
  - `options`: pass pipeline parameters such as required `config_version_id` or optional `cutover_date`. When the canonical configuration contains `planning_calendar.json`, the UI/API automatically adds `--calendar`. Without a calendar, provide `weeks` (equal-weight weeks) as a fallback.
  - (Legacy request-body examples remain unchanged.)

- **`GET /runs/{run_id}`**: retrieve details for a specific run.
  - `detail=true` includes both KPI summaries and day-level outputs.

- **`DELETE /runs/{run_id}`**: delete a run. When RBAC is enabled, roles such as `planner` or `admin` are required.

- **`POST /compare`**: compare multiple runs (`run_ids`).
  - Specify `base_id` to compute absolute and percentage deltas relative to the base.

- **`GET /runs/{run_id}/meta`**: fetch run metadata (approval state, baseline flags, notes, etc.).

- **`POST /runs/{run_id}/approve`**: mark a run as approved.

- **`POST /runs/{run_id}/promote-baseline`**: set the run as the baseline for its scenario.

- **`POST /runs/{run_id}/archive`**: archive (soft-delete) the run.

- **`POST /runs/{run_id}/unarchive`**: restore an archived run.

- **`POST /runs/{run_id}/note`**: add or update free-form notes.

- **`GET /runs/baseline?scenario_id={id}`**: return the current baseline run ID for a scenario.

## Data persistence modes (`storage_mode`)

The `POST /plans/integrated/run` API and related CLI commands control how plan data is stored via the `storage_mode` parameter.

### Modes

| Mode | Description | Primary use case |
| :--- | :--- | :--- |
| `db` | Save plan data exclusively to the database (PlanRepository); no JSON files are emitted. | Standard production usage where durability and consistency are required. |
| `files` | Legacy behavior—persist plan data only as JSON files under `out/`; nothing is written to the database. | Debugging, local ad-hoc analysis, or backwards compatibility with older flows. |
| `both` | Write plan data to both the database and JSON files. | Transitional periods during migrations, or when both storage methods are needed. |

### How to specify

- **API**: include `"storage_mode": "db"` (for example) in the request body for `POST /plans/integrated/run`.
- **Environment variable**: set `PLAN_STORAGE_MODE` to `db`, `files`, or `both` to define the default for all executions. An explicit API request value takes precedence.
- **Default**: when neither the parameter nor the environment variable is set, the default behavior is `both`.

## Comparison (CSV)
- `GET /ui/compare/metrics.csv?run_ids={id1},{id2}`: export KPI comparisons.
- `GET /ui/compare/diffs.csv?run_ids={id1},{id2}&threshold=5`: export difference tables with a threshold filter.

Notes:
- All JSON and CSV responses are UTF-8. CSV responses use the `text/csv; charset=utf-8` content type.
- Authentication mode switches via the `AUTH_MODE` environment variable (`none`, `apikey`, `basic`).
