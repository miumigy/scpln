# tests/test_dockerfile.py
import os
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"

pytestmark = pytest.mark.slow


def test_dockerfile_exists_and_has_expected_content():
    assert (
        DOCKERFILE.exists()
    ), "Dockerfile が存在しません（リポジトリ直下に作成してください）"
    content = DOCKERFILE.read_text(encoding="utf-8")
    # 主要キーワードの存在チェック
    for kw in [
        "FROM python:3.11-slim",
        "WORKDIR /app",
        "COPY requirements.txt",
        "pip install",
        "COPY . .",
        "EXPOSE 8080",
        'CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8080"',
    ]:
        assert kw in content, f"Dockerfile に必要な要素が欠けています: {kw}"


@pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker コマンドが見つからないためスキップ"
)
@pytest.mark.skipif(
    os.getenv("ALLOW_DOCKER_BUILD") != "1",
    reason="skip heavy docker build unless ALLOW_DOCKER_BUILD=1",
)
def test_docker_image_builds(tmp_path):
    # unittest 経由でも早期スキップ（pytest でない実行器向け）
    if os.getenv("ALLOW_DOCKER_BUILD") != "1":
        try:
            pytest.skip("skip heavy docker build unless ALLOW_DOCKER_BUILD=1")
        except Exception:
            return
    # 変更中の作業ツリーを誤ってビルドに含めないよう、ワークツリー全体でビルド
    # ただしタグ名は一時的なものにする
    tag = "scpln:test"
    try:
        # --no-cache なしでOK（CI時間短縮）
        res = subprocess.run(
            ["docker", "build", "-t", tag, str(ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        # ビルド成功（0終了）
        assert res.returncode == 0, f"Docker build 失敗:\n{res.stdout}"
    finally:
        subprocess.run(
            ["docker", "rmi", "-f", tag],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
