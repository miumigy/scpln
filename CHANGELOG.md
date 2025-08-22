# 変更履歴

## Unreleased

- （運用）Auto-merge 設定とコンフリクト検出ワークフローの整備（継続）

## 2025-08-21

- feat(api): /runs にページングを追加（`offset`/`limit`）。detail=false 既定50、detail=true 既定10（>10は400）
- feat(ui): /ui/runs にページャ（Prev/Next/Limit）とメタ表示（`total/offset/limit`）を追加
- chore(run): `REGISTRY_CAPACITY` 環境変数でメモリ保持件数を可変化（既定50）
- docs: README の API/環境変数を更新、docs/EXPANSION_STRATEGY_JA.md を参照可能に
- chore: 競合マーカー検出のCIに対応するため README の競合を解消
- chore(autofix): ruff/black による軽微な自動整形（別PR）
 - feat(obs): JSON構造化ロガー（`SIM_LOG_JSON=1`）と Request-ID 相関ログ、Uvicorn JSONロギングの`--log-config`サンプル追加
