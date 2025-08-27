#!/usr/bin/env bash
set -euo pipefail

# 目的: 強固なAPIキーを生成し、カレントの .env に反映（存在しない場合は手順表示）
# 使い方: bash scripts/rotate_api_key.sh

generate_key() {
  python - << 'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
print(''.join(secrets.choice(alphabet) for _ in range(48)))
PY
}

NEW_KEY=$(generate_key)
echo "[info] 生成したAPIキー: ${NEW_KEY}"

if [ -f .env ]; then
  echo "[info] .env を検出しました。API_KEY_VALUE を更新します。"
  if grep -q '^API_KEY_VALUE=' .env; then
    # 既存の行を置換
    sed -i.bak -E "s/^API_KEY_VALUE=.*/API_KEY_VALUE=${NEW_KEY}/" .env
  else
    # 末尾に追記
    printf "\nAPI_KEY_VALUE=%s\n" "$NEW_KEY" >> .env
  fi
  echo "[done] .env を更新しました（バックアップ: .env.bak）。"
else
  cat <<EOF
[warn] カレントディレクトリに .env が存在しません。
- 初期化例: cp configs/env.example .env
- その後、以下を .env に設定してください:
  API_KEY_VALUE=${NEW_KEY}
EOF
fi

echo "[next] 運用環境のシークレットストアも同一値で更新してください。"

