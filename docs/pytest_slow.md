# pytest slow tests

The `slow` marker is defined in `pytest.ini` and groups integration/E2E scenarios.

- Standard local cycle: `PYTHONPATH=. .venv/bin/pytest -m "not slow"`
- Run only the heavy suite: `PYTHONPATH=. .venv/bin/pytest -m slow`
- Inspect durations: `PYTHONPATH=. .venv/bin/pytest -m slow --durations=20`

CI is expected to include the `slow` suite. Keep local iteration fast by defaulting to `not slow`.
