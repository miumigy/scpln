#!/usr/bin/env bash
set -euo pipefail

# 目的: Git履歴から誤コミットされた .env を抹消する補助スクリプト
# 注意: 履歴書き換えは破壊的です。実行前に周知・バックアップ・クリーンな作業ツリーを確認してください。
# 使い方: bash scripts/purge_env_history.sh --confirm

if [ "${1-}" != "--confirm" ]; then
  echo "[abort] 確認フラグが必要です: --confirm"
  echo "例: bash scripts/purge_env_history.sh --confirm"
  exit 2
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "[abort] 作業ツリーに未コミット変更があります。コミット/スタッシュしてください。"
  exit 2
fi

if command -v git-filter-repo >/dev/null 2>&1; then
  echo "[info] git-filter-repo を使用して .env を履歴から抹消します。"
  git filter-repo --invert-paths --path .env
else
  echo "[warn] git-filter-repo が見つかりません。代替として git filter-branch を使用します。時間がかかる場合があります。"
  git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch .env' --prune-empty --tag-name-filter cat -- --all
  # 参照のクリーンアップ
  git for-each-ref --format='delete %(refname)' refs/original | git update-ref --stdin || true
  git reflog expire --expire-unreachable=now --all || true
  git gc --prune=now --aggressive || true
fi

cat <<'EOT'
[next]
- リモートへ強制更新（要注意）:
    git push --force-with-lease --all
    git push --force-with-lease --tags
- 各開発者は再クローンまたは履歴再書き換え後の同期が必要です。
- 既に取得済みのクローンには古い履歴が残る可能性があるため、シークレットは必ずローテーション済みであることを確認してください。
EOT

