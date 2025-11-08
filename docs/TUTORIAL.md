# Hands-on: Planning Hub tutorial

Purpose and scope:

- Experience the basic workflow of the Planning Hub (`/ui/plans`).
- For algorithmic details see `docs/AGG_DET_RECONCILIATION.md`.
- The README’s “Planning Hub” section aggregates UI design notes and roadmaps.

Use this walkthrough to learn the flow and vocabulary, then navigate to other documents via the README’s documentation map as needed.

## Prerequisites
- Server is running (e.g., `uvicorn main:app --reload`).
- Browser access to `http://localhost:8000`.

## 0. Prepare configurations

Load predefined sample configurations into the database before starting.

1. **Load sample configuration**

   Run the following command at the project root to seed the default dataset:

   ```bash
   PYTHONPATH=. python3 scripts/seed_canonical.py --save-db
   ```

2. **Verify the configuration**

   - Open `/ui/configs` in the browser.
   - Confirm the seeded configuration (e.g., `canonical-seed`) appears in the list.
   - Use this view to inspect configuration details or compare versions.

### Optional: manage planning inputs via CLI
You can register or export planning inputs without going through the UI:

```bash
# Import CSV/JSON into the planning_input_sets table (validate only)
PYTHONPATH=. python scripts/import_planning_inputs.py \
  -i samples/planning \
  --version-id 14 \
  --label tutorial_input --validate-only

# Perform the actual import (stores rows in the DB)
PYTHONPATH=. python scripts/import_planning_inputs.py \
  -i samples/planning \
  --version-id 14 \
  --label tutorial_input

# Export an existing input set back to CSV
PYTHONPATH=. python scripts/export_planning_inputs.py \
  --label tutorial_input --include-meta --zip
```

The run you create later can reference `tutorial_input` so that plans and runs share the same managed dataset.
When calling `/plans/create_and_execute` (or `/runs`), include `"input_set_label": "tutorial_input"` in the JSON body so the pipeline uses this managed dataset instead of `samples/planning`.

## 1. Create a new plan

1. Open `/ui/plans`.
2. Click “Create plan (integrated run)” to open the form.
3. Fill in the fields:
   - **Canonical configuration version**: select the ID you just loaded (typically at the top of the list).
   - **Planning calendar**: when the canonical configuration includes `planning_calendar.json`, week boundaries and periods are applied automatically. Only provide fallback weeks (`weeks`) when the calendar is absent.
   - Optionally specify `cutover_date`, `anchor_policy`, etc.
4. Click “Create & Execute”.
5. The UI redirects to the plan detail page (`/ui/plans/{version_id}`). Plan data is stored directly in the database with version control rather than legacy files.

Tip: once execution finishes, the bottom panel shows logs and KPI summaries. Start with the “Overview” tab to grasp the plan.

## 2. Preview (Aggregate / Disaggregate / Validate)
- **Aggregate**: inspect results aggregated by family × period.
- **Disaggregate**: view SKU × week detail with quick filters (first 200 rows).
- **Validate**: review automated checks for tolerance breaches, negative inventory, fractional receipts, and capacity overruns.

Tip: download the planned-order CSV (`schedule.csv`) from the Schedule tab.

## 3. Reconcile (optional)
- From the Execute tab, choose “Reconcile (custom parameters)”.
  - Adjust `cutover_date`, `recon_window_days`, `anchor_policy`, etc.
  - Click “Run reconciliation”.
- Inspect deltas via the Diff tab or exports (`compare.csv`, `violations_only.csv`).

## 4. Plan & Execute (auto-complete)
- In the Execute tab, use “Plan & Execute (auto)” for the one-click flow.
  - Parameters mirror the reconciliation step; the UI fills reasonable defaults.
  - Trigger execution and confirm results.
- Again, review differences through the Diff tab or CSV exports.

## 5. Review runs and PSI simulations

### 5.1 Concepts: plan vs. run

In the Planning Hub, plans and runs describe complementary aspects of the supply-chain simulation:

- **Plan**: defines what to simulate—settings and data such as demand forecasts, inventory policies, capacity, BOM. Plans are versioned, linked to `config_version_id`, and managed at `/ui/plans`.
- **Run**: captures the outcome of executing a simulation based on a plan. Runs contain summaries, KPIs, daily P&L, cost traces, and more. A single plan can yield multiple runs with different parameters or scenarios for comparison.

In short, a plan defines the scenario; a run records the outcome.

### 5.2 Inspect `/ui/runs`

`/ui/runs` lists every executed run.

1. **Open `/ui/runs`**: browse to `http://localhost:8000/ui/runs`.
2. **Review the table**: each run displays
   - `run_id`
   - `started_at`
   - `duration_ms`
   - `config_id`, `scenario_id`, `plan_version_id`
   - `summary` with KPIs such as fill rate and profit
3. **Open details**: click a `run_id` to view `/ui/runs/{run_id}`.
   - The detail page shows run summaries, KPIs, daily P&L charts, cost traces, and the execution configuration (`config_json`).
   - When a related plan exists, its KPI summary is also displayed.

### 5.3 PSI simulation overview

Simulations revolve around PSI (Production, Sales, Inventory), balancing these three dimensions to maximize supply-chain performance.

Options exposed via `app/runs_api.py`—such as `weeks`, `round_mode`, `lt_unit`, `config_version_id`—serve as key PSI parameters:

- `calendar_path`: manually supply an external calendar (rarely needed).
- `weeks`: fallback equal-split weeks when no calendar is available.
- `round_mode`: rounding strategy for plan quantities (e.g., integer).
- `lt_unit`: lead-time unit (day, week, etc.).
- `config_version_id`: configuration version to use.

Tuning these options allows you to evaluate alternative PSI scenarios and select the supply-chain strategy that best meets business goals.

## 6. Results tab
- Share the latest run list or copy comparisons (`metrics`, `diffs`).
- Switch tabs to examine KPIs, deltas, and visualizations (Chart.js).

## 7. API examples

- **Integrated plan run (synchronous)**

  ```bash
  CONFIG_VERSION_ID=14  # choose a version seeded earlier

  curl -sS http://localhost:8000/plans/create_and_execute \
    -H 'content-type: application/json' \
    -d "{
          \"config_version_id\":${CONFIG_VERSION_ID},
          \"round_mode\":\"int\",
          \"lt_unit\":\"day\",
          \"cutover_date\":\"2025-09-01\",
          \"anchor_policy\":\"blend\",
          \"storage_mode\":\"db\"
        }" | jq .
  ```

- **Download planned-order CSV**

  ```bash
  curl -sS http://localhost:8000/plans/{version_id}/schedule.csv -o schedule.csv
  ```

- **Execute via Run API**

  ```bash
  CONFIG_VERSION_ID=14

  curl -sS http://localhost:8000/runs -H 'content-type: application/json' -d "{
    \"pipeline\":\"integrated\",
    \"async\":false,
    \"options\":{
      \"config_version_id\":${CONFIG_VERSION_ID},
      \"lt_unit\":\"day\"
    }
  }" | jq .
  ```

## 8. Glossary and references
- Glossary: `docs/TERMS.md`
- API overview: `docs/API-OVERVIEW.md`
