# Weekly calendar refactor memo (to be archived)

- Created: 2025-02-14 (first draft)
- Status: completed (content migrated to formal docs; candidate for deletion)
- Purpose: temporary notes capturing the calendar refactor. The official documents now contain the final guidance, so this file is no longer required.

## Where the content now lives
- `README.md`: added behavior notes for canonical configs that include `planning_calendar.json` and an overview of `PlanningCalendarSpec`.
- `docs/AGG_DET_RECONCILIATION.md`: consolidated calendar specs, module usage, and fallback policy.
- `docs/TUTORIAL.md`: updated automatic calendar application and fallback steps across UI / Run / API flows.
- `docs/API-OVERVIEW.md`: refreshed `POST /runs` options, clarifying calendar auto-detection and the role of the `weeks` fallback.

## Implementation summary
- Added `scripts/calendar_utils.py` to centralize calendar loading, week allocation, ordering, and date-to-week mapping.
- Updated `scripts/allocate.py`, `scripts/mrp.py`, `scripts/reconcile.py`, `scripts/reconcile_levels.py`, and `scripts/anchor_adjust.py` to prioritize `--calendar`, falling back to equal-split `--weeks` only when `planning_calendar.json` is absent.
- `scripts/run_planning_pipeline.py` and UI/API executions (`app/plans_api.py`, `app/jobs.py`) now rely on `_calendar_cli_args` to auto-detect `planning_calendar.json` within the canonical configuration.
- Added sample data in `samples/planning/planning_calendar.json` and regression coverage in `tests/test_calendar_utils.py` for five-week months and ISO-week offsets.

## Task list (completed)

| No | Status | Description |
|----|--------|-------------|
| T1 | Done | Inventory UI/API parameters and define migration scope |
| T2 | Done | Extend canonical models and design validation |
| T3 | Done | Update config loaders/storage and adjust `prepare_canonical_inputs` |
| T4 | Done | Move `allocate.py` to calendar-based allocation; deprecate `--weeks` |
| T5 | Done | Align `mrp.py` week-key interpretation with the calendar |
| T6 | Done | Switch `anchor_adjust.py` cutover estimation to calendar usage |
| T7 | Done | Simplify week-related arguments in `run_planning_pipeline.py` and reference config |
| T8 | Done | Update UI displays to reference configuration values (prep for removing inputs) |
| T9 | Done | Design fallback/migration strategy and warning logs |
| T10 | Done | Expand tests for boundary cases |
| T11 | Done | Update README and formal documentation |
| T12 | Done | Evaluate migration scripts and procedures |
| T13 | Done | Plan release and stakeholder communication |
| T14 | Done | Refresh `samples/canonical` with the new spec |
| T15 | Done | Update CI/GitHub Actions and adjust compatibility checks |

## Known follow-ups
- The UI still exposes a `weeks` input for fallback scenarios; once calendars are standardized the field will auto-populate.
- For configurations with additional calendars (e.g., per production line), recommend separating the plan calendar into `planning_calendar.json` before upload.

## Deletion criteria
- Since all specs and operational guidance have moved to the documents listed above, this file can be deleted.
- If future brainstorming for calendar extensions is required, relocate this memo under `docs/archive/` for historical reference only.
