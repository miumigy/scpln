@router.get("/ui/plans/input_sets/{label}/diff", response_class=HTMLResponse)
def ui_plan_input_set_diff(
    label: str,
    request: Request,
    against: str | None = Query(None, description="Label of the input set to compare against. Defaults to latest ready set."),
):
    import tempfile
    import shutil
    import subprocess
    from fastapi import BackgroundTasks

    background_tasks = BackgroundTasks()

    try:
        current_set = get_planning_input_set(label=label, include_aggregates=True)
    except PlanningInputSetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Input set with label '{label}' not found.")

    other_label = against
    other_set = None
    if not other_label:
        # Find latest ready set with the same config_version_id
        summaries = list_planning_input_sets(
            config_version_id=current_set.config_version_id,
            status="ready",
            limit=10
        )
        # Find the most recent one that is not the current one
        for s in sorted(summaries, key=lambda x: x.updated_at or 0, reverse=True):
            if s.label != label:
                other_label = s.label
                break

    if other_label:
        try:
            other_set = get_planning_input_set(label=other_label, include_aggregates=True)
        except PlanningInputSetNotFoundError:
            pass # Fallback to no diff

    diff_report = None
    if other_set and other_label:
        temp_dir = tempfile.mkdtemp(prefix="plan-diff-")
        background_tasks.add_task(shutil.rmtree, temp_dir)
        script_path = str(_BASE_DIR / "scripts" / "export_planning_inputs.py")
        args = [
            sys.executable,
            script_path,
            "--label",
            label,
            "--diff-against",
            other_label,
            "--output-dir",
            str(temp_dir),
        ]
        env = os.environ.copy()
        env.setdefault("PYTHONPATH", str(_BASE_DIR))
        try:
            subprocess.run(args, cwd=str(_BASE_DIR), env=env, check=True, capture_output=True, text=True)
            diff_path = Path(temp_dir) / "diff_report.json"
            if diff_path.exists():
                diff_report = json.loads(diff_path.read_text(encoding="utf-8"))
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Failed to generate or read diff report: {e}")
            # Allow rendering the page without a diff
            pass

    return templates.TemplateResponse(
        request,
        "input_set_diff.html",
        {
            "subtitle": f"Input Set Diff: {label}",
            "current_set": current_set,
            "other_set": other_set,
            "diff_report": diff_report,
        },
    )