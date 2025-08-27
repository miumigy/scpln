#!/usr/bin/env bash
set -euo pipefail

# 目的: リポジトリ同梱の .githooks を Git の hooksPath として有効化

if [ ! -f .githooks/pre-commit ]; then
  echo "[abort] .githooks/pre-commit が見つかりません。" >&2
  exit 2
fi

chmod +x .githooks/pre-commit
git config core.hooksPath .githooks

echo "[done] pre-commit フックを有効化しました（core.hooksPath=.githooks）。"

