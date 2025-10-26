import csv
import json
import os
import re
import subprocess
import time
from pathlib import Path
import sys

import pytest

from app import db, jobs
from app.jobs import JobManager
from core.plan_repository import PlanRepository

pytestmark = pytest.mark.slow

# 十分な長さを確保
JOB_WAIT_TIMEOUT = 120


def _get_seeded_config_id() -> int:
    """seedスクリプトを実行し、生成されたCanonical設定のIDを返す"""
    # CI環境では.venvが存在しないため、python3を直接呼び出す
    cmd = [
        sys.executable,
        "scripts/seed_canonical.py",
        "--save-db",
        "--name",
        "regression-test-base",
    ]
    # 現在の環境変数を引き継ぎ、PYTHONPATHを追加する
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", env=env
    )

    if result.returncode != 0:
        pytest.fail(
            f"seed_canonical.py の実行に失敗しました。\n"
            f"Exit Code: {result.returncode}\n"
            f"Stderr: {result.stderr}\n"
            f"Stdout: {result.stdout}"
        )

    # 出力からIDを正規表現で抽出 (例: "[info] DBへ保存しました: canonical_config_versions.id=1")
    match = re.search(r"canonical_config_versions.id=(\d+)", result.stdout)
    if not match:
        raise RuntimeError(
            f"seedスクリプトの出力からconfig_version_idを取得できませんでした: {result.stdout}"
        )
    return int(match.group(1))


@pytest.fixture(scope="function")
def job_manager(tmp_path, monkeypatch):
    """テスト関数ごとにDBを初期化し、JobManagerをセットアップ"""
    db_path = tmp_path / "scpln.db"
    monkeypatch.setenv("SCPLN_DB", str(db_path))

    # app.db モジュールをリロードして、新しい環境変数を反映させる
    import importlib

    importlib.reload(db)

    # Alembicでマイグレーションを実行
    alembic_ini_path = Path(__file__).parent.parent / "alembic.ini"
    temp_alembic_ini_path = tmp_path / "alembic.ini"

    with open(alembic_ini_path, "r") as src, open(temp_alembic_ini_path, "w") as dst:
        for line in src:
            if line.strip().startswith("sqlalchemy.url"):
                dst.write(f"sqlalchemy.url = sqlite:///{db_path}\n")
            else:
                dst.write(line)

    import sys

    old_sys_argv = sys.argv
    try:
        sys.argv = ["alembic", "-c", str(temp_alembic_ini_path), "upgrade", "head"]
        from alembic.config import main as alembic_main
        import sys

        alembic_main()
    finally:
        sys.argv = old_sys_argv

    # 一時ディレクトリをクリーンアップ
    tmp_root = Path(__file__).resolve().parents[1] / "tmp" / "regression_tests"
    if tmp_root.exists():
        import shutil

        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True)

    # リロードされたモジュールからJobManagerインスタンスを生成
    manager = jobs.JobManager(workers=1)
    manager.start()
    yield manager
    manager.stop()


@pytest.fixture(scope="function")
def seeded_config_id() -> int:
    """テスト関数ごとにDBへ設定をシードし、そのIDを返す"""
    return _get_seeded_config_id()


def _wait_for_job(job_manager: JobManager, job_id: str) -> dict:
    """ジョブの完了を待機し、結果を返す"""
    started = time.monotonic()
    while time.monotonic() - started < JOB_WAIT_TIMEOUT:
        rec = db.get_job(job_id)
        if rec and rec.get("status") in ("succeeded", "failed"):
            if rec.get("status") == "failed":
                pytest.fail(f"ジョブ {job_id} が失敗しました: {rec.get('error')}")
            return json.loads(rec.get("result_json") or "{}")
        time.sleep(0.5)
    pytest.fail(f"ジョブ {job_id} がタイムアウトしました")


def _read_report_csv(out_dir: Path) -> list[dict]:
    """report.csvを読み込んでソート済みの辞書のリストとして返す"""
    report_path = out_dir / "report.csv"
    if not report_path.exists():
        pytest.fail(f"{report_path} が見つかりません")

    with report_path.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        # 数値項目をfloatに変換
        rows = []
        for row in reader:
            for key, val in row.items():
                try:
                    row[key] = float(val)
                except (ValueError, TypeError):
                    pass
            rows.append(row)

    # SKUとPeriodでソートして順序を安定させる
    return sorted(rows, key=lambda r: (r.get("sku", ""), r.get("period", 0)))


def test_planning_regression(job_manager: JobManager, seeded_config_id: int):
    """
    Canonical設定を用いた計画実行が成功し、成果物が期待どおり生成されることを検証する。
    """
    base_dir = Path(__file__).resolve().parents[1]
    tmp_root = base_dir / "tmp" / "regression_tests"

    version_canonical = "regression-canonical"

    # Canonical設定で計画を実行
    out_dir_canonical = tmp_root / version_canonical
    params_canonical = {
        "version_id": version_canonical,
        "config_version_id": seeded_config_id,
        "out_dir": str(out_dir_canonical),
        "weeks": 8,
    }
    job_id_canonical = job_manager.submit_planning(params_canonical)
    result_canonical = _wait_for_job(job_manager, job_id_canonical)
    assert result_canonical["version_id"] == version_canonical
    assert result_canonical["config_version_id"] == seeded_config_id

    report_canonical = _read_report_csv(out_dir_canonical)

    assert report_canonical, "レポートが生成されていません"

    expected_columns = {
        "type",
        "week",
        "capacity",
        "original_load",
        "adjusted_load",
        "utilization",
        "spill_in",
        "spill_out",
        "demand",
        "supply_plan",
        "fill_rate",
    }
    for row in report_canonical:
        assert (
            set(row.keys()) >= expected_columns
        ), "レポート列ヘッダーが想定と異なります"

    capacity_rows = [r for r in report_canonical if r.get("type") == "capacity"]
    assert capacity_rows, "capacity 行が存在しません"
    for row in capacity_rows:
        assert isinstance(
            row.get("capacity"), float
        ), "capacity が数値に変換されていません"
        assert row.get("capacity", 0.0) >= 0.0, "capacity が負の値です"

    service_rows = [r for r in report_canonical if r.get("type") == "service"]
    assert service_rows, "service 行が存在しません"
    for row in service_rows:
        assert isinstance(row.get("demand"), float), "demand が数値に変換されていません"
        assert isinstance(
            row.get("supply_plan"), float
        ), "supply_plan が数値に変換されていません"
        assert 0.0 <= row.get("fill_rate", 0.0) <= 1.0, "fill_rate の範囲が不正です"

    plan_version = db.get_plan_version(version_canonical)
    assert plan_version, "plan_versions に登録されていません"
    plan_final = db.get_plan_artifact(version_canonical, "plan_final.json")
    assert plan_final and plan_final.get("weekly_summary"), "plan_final.json がDBに保存されていません"
    repo = PlanRepository(db._conn)
    weekly_rows = repo.fetch_plan_series(version_canonical, "weekly_summary")
    assert weekly_rows, "PlanRepository に weekly_summary が保存されていません"

    print("リグレッションテスト成功: Canonical設定の計画実行が正常に完了しました。")
