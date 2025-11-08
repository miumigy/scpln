# --- Legacy Mode監視メトリクス ---
LEGACY_MODE_RUNS_TOTAL = Counter(
    "scpln_legacy_mode_runs_total",
    "Total number of runs executed in legacy mode (without input_set_label)",
    labelnames=("entrypoint",),
)