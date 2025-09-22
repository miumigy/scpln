
import csv
import json
import re
import subprocess
import time
from pathlib import Path

import pytest

from app import db
from app.jobs import JobManager

# 十分な長さを確保
JOB_WAIT_TIMEOUT = 120


def _get_seeded_config_id() -> int:
    """seedスクリプトを実行し、生成されたCanonical設定のIDを返す"""
    # CI環境では.venvが存在しないため、python3を直接呼び出す
    cmd = [
        "python3",
        "scripts/seed_canonical.py",
        "--save-db",
        "--name",
        "regression-test-base",
    ]
    # PYTHONPATHを設定して、プロジェクトのモジュールをインポート可能にする
    env = {"PYTHONPATH": "."}
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True, encoding="utf-8", env=env
    )
    # 出力からIDを正規表現で抽出 (例: "[info] DBへ保存しました: canonical_config_versions.id=1")
    match = re.search(r"canonical_config_versions.id=(\d+)", result.stdout)
    if not match:
        raise RuntimeError(
            f"seedスクリプトの出力からconfig_version_idを取得できませんでした: {result.stdout}"
        )
    return int(match.group(1))


@pytest.fixture(scope="module")
def job_manager():
    """テスト用のJobManagerをセットアップ"""
    # テスト実行前に一時ディレクトリをクリーンアップ
    base_dir = Path(__file__).resolve().parents[1]
    tmp_root = base_dir / "tmp" / "regression_tests"
    if tmp_root.exists():
        import shutil

        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True)

    manager = JobManager(workers=1)
    manager.start()
    yield manager
    manager.stop()


@pytest.fixture(scope="module")
def seeded_config_id() -> int:
    """テストの開始前に一度だけDBに設定をシードし、そのIDを返す"""
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
    旧来のCSV入力とCanonical設定入力による計画実行の結果が一致することを検証する。
    """
    base_dir = Path(__file__).resolve().parents[1]
    tmp_root = base_dir / "tmp" / "regression_tests"

    version_legacy = "regression-legacy"
    version_canonical = "regression-canonical"

    # 1. 旧来の方法（CSV）で計画を実行
    out_dir_legacy = tmp_root / version_legacy
    params_legacy = {
        "version_id": version_legacy,
        "input_dir": str(base_dir / "samples" / "planning"),
        "out_dir": str(out_dir_legacy),
        "weeks": 8,
    }
    job_id_legacy = job_manager.submit_planning(params_legacy)
    result_legacy = _wait_for_job(job_manager, job_id_legacy)
    assert result_legacy["version_id"] == version_legacy

    # 2. Canonical設定で計画を実行
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

    # 3. 結果を比較
    report_legacy = _read_report_csv(out_dir_legacy)
    report_canonical = _read_report_csv(out_dir_canonical)

    assert len(report_legacy) == len(
        report_canonical
    ), "レポートの行数が一致しません"
    assert report_legacy, "旧来方法のレポートが空です"

    # 各行・各列の値がほぼ等しいことを確認
    for row_leg, row_can in zip(report_legacy, report_canonical):
        assert row_leg.keys() == row_can.keys(), "レポートの列名が一致しません"
        for key in row_leg:
            val_leg = row_leg[key]
            val_can = row_can[key]
            if isinstance(val_leg, float):
                assert pytest.approx(val_leg) == val_can, f"キー '{key}' の値が一致しません"
            else:
                assert val_leg == val_can, f"キー '{key}' の値が一致しません"

    print("リグレッションテスト成功: 旧来CSVとCanonical設定の実行結果が一致しました。")
