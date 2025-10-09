# Plan DB ロールバック Runbook（PlanRepository障害時）

## 1. 目的とスコープ
- PlanRepository 経路が利用不能・整合性崩壊した際に、旧 `plan_artifacts` ベース運用へ安全に戻すための手順を定義する。
- 対象: Planning Hub API/UI、ジョブワーカー、RunRegistry。SRE/PM/開発が即応できるよう、判断基準・準備物・検証方法を明文化する。

## 2. トリガー判定
- `plan_series` / `plan_kpis` の書込みエラーが継続し、復旧 ETA が4時間を超えると判断したとき。
- PlanRepository データ破損（整合チェック失敗、missing level）が複数版で確認され、UIが主要画面を表示できないとき。
- PlanRepository リードレプリカ遅延により `/plans` API がタイムアウトし、業務継続が困難なとき。
- SRE が P1 インシデントを宣言し、経営判断として Legacy ルートへ切り戻す決定が下ったとき。

## 3. 事前準備・前提
- `PLAN_STORAGE_MODE=both`（または最低でも `files`）を本番で維持し、最新版 `plan_artifacts` が並行保存されていること。
- `data/scpln.db` の直近バックアップが `backup/plan_db_*.db` に存在し、SRE が取得手順を把握していること。
- `release/plan-artifacts-stable`（PlanRepository導入前最終リリース）タグが Git に存在し、デプロイ手順がRunbook化されていること。
- FastAPI サービスとジョブワーカーで `JOBS_ENABLED` や `PLAN_STORAGE_MODE` を環境変数で制御できるデプロイ基盤があること。

## 4. ロールバック手順（目安: 90分）

### 4.1 初動（～15分）
- Plan作成を一時停止: FastAPI とジョブワーカーに `JOBS_ENABLED=0` を設定し、キュー投入を停止する。
- 関係者へインシデント告知（SRE→プロダクト/業務）
  - 内容: 障害概要、想定影響、ロールバック開始予定時刻、PlanRepository再開メド。
- 監視抑止: PlanRepository関連アラートを「メンテナンス中」へ切替。

### 4.2 データ保全（～20分）
- `data/scpln.db` を複製
  - `cp data/scpln.db backup/plan_db_prerollback_$(date +%Y%m%d%H%M).db`
- 直近PlanのPlanRepositoryスナップショットを取得
  - `sqlite3 data/scpln.db ".output tmp/plan_series_latest.csv" "SELECT * FROM plan_series WHERE version_id IN (SELECT version_id FROM plan_versions ORDER BY created_at DESC LIMIT 5);"`
- RunRegistry 状態をJSONで保存
  - `PYTHONPATH=. SCPLN_SKIP_SIMULATION_API=1 python - <<'PY'` で `app/run_registry.REGISTRY.list()` をdump（バックエンドがDBの場合は不要）。

### 4.3 `plan_artifacts` 再同期（～25分）
- 最新版に `aggregate.json` / `sku_week.json` / `plan_final.json` が揃っているか確認
  - `sqlite3 data/scpln.db "SELECT version_id, SUM(name='aggregate.json')>=1 AS has_agg, SUM(name='sku_week.json')>=1 AS has_det, SUM(name='plan_final.json')>=1 AS has_final FROM plan_artifacts GROUP BY version_id ORDER BY MAX(created_at) DESC LIMIT 5;"`
- 欠損がある場合
  1. PlanRepository から一時ディレクトリへエクスポート
     - `PYTHONPATH=. SCPLN_DB=$(pwd)/data/scpln.db python scripts/plan_export.py <version_id> -o tmp/restore/<version_id>`
  2. エクスポートしたJSONを `plan_artifacts` へ反映
     - `PYTHONPATH=. SCPLN_DB=$(pwd)/data/scpln.db python - <<'PY'
from pathlib import Path
from app import db
import json, sys

db.init_db()
version_id = sys.argv[1]
base = Path('tmp/restore') / version_id
artifacts = ['aggregate.json','sku_week.json','mrp.json','plan_final.json','report.csv']
for name in artifacts:
    p = base / name
    if not p.exists():
        continue
    payload = p.read_text(encoding='utf-8')
    db.upsert_plan_artifact(version_id, name, payload)
PY` `<version_id>`
- `psi_state.json` や `psi_overrides.json` が欠落している場合は UI から最新状態をCSVへダウンロードし復元、または業務合意の上で `status=draft` へ戻す。

### 4.4 アプリ切替（～15分）
- FastAPI / ジョブワーカーのデプロイを `release/plan-artifacts-stable` タグへロールバック。
  - `git fetch && git checkout release/plan-artifacts-stable`
  - デプロイCIを実行し、ロールバック版を `main` 環境へ反映。
- ロールバック版で `PLAN_STORAGE_MODE=files` を明示し、新規PlanがPlanRepositoryへ書き込まれないようにする。
- UIへ告知: `/ui/plans` を刷新前テンプレートに戻すため、CDNキャッシュをクリア。

### 4.5 RunRegistry補正（～10分）
- PlanRepository経由で記録された `runs.plan_job_id` が旧実装では参照されないため、必要に応じて `UPDATE runs SET plan_job_id=NULL WHERE created_at>=<cutover_ts>;` を実施。
- `REGISTRY_BACKEND=memory` 運用の場合、アプリ再起動で消失するため事前に保存した一覧を共有ドライブへ格納。

### 4.6 検証（～10分）
- API: `curl -X POST http://localhost:8000/plans/integrated/run?storage=files` でPlan作成が成功し、`plan_artifacts` に成果物が保存されること。
- UI: `/ui/plans` で aggregate / detail / KPI が表示できること、差分CSVがダウンロードできること。
- テスト（CI or ローカル）
  - `PYTHONPATH=. SCPLN_SKIP_SIMULATION_API=1 PLAN_STORAGE_MODE=files .venv/bin/pytest tests/test_plans_api_e2e.py -k legacy`
  - `PYTHONPATH=. .venv/bin/pytest tests/test_plan_storage_cli.py::test_plan_aggregate_storage_files_only`

### 4.7 ロールフォワード準備
- 障害原因が解消したら、PlanRepositoryへ復帰する前に
  - `scripts/plan_backfill_repository.py --force --state-file tmp/rollback_recover.json`
  - `PLAN_STORAGE_MODE=both` へ戻し、新版でPlan生成テストを実施。
- ロールバック期間のPlanを一覧化し、PlanRepositoryへ再投入済みか確認 (`SELECT version_id FROM plan_series WHERE version_id IN (...);`)。
- 監視・アラートをPlanRepository用に再有効化。

## 5. コマンドリファレンス
- 直近Plan一覧: `sqlite3 data/scpln.db "SELECT version_id,status,created_at FROM plan_versions ORDER BY created_at DESC LIMIT 10;"`
- PlanRepository行数確認: `sqlite3 data/scpln.db "SELECT level, COUNT(*) FROM plan_series GROUP BY level;"`
- PlanArtifactsダンプ: `sqlite3 data/scpln.db ".output tmp/plan_artifacts_dump.json" "SELECT version_id,name,json_text FROM plan_artifacts WHERE version_id=?;"`
- Rollbackタグ探索: `git tag --list 'release/*plan-artifacts*' --sort=-creatordate | head -5`

## 6. 連絡体制
- インシデントコマンダー: SRE当番
- 影響アプリ: Planning Hub API/UI, RunRegistry, Exportツール
- コミュニケーション: `#planning-incident` チャンネル（Slack）、業務代表へのメール通知
- ロールバック完了後は 24 時間監視を強化し、PlanRepository 再開予定を業務へ共有する。

## 7. 更新履歴
- 2025-10-06: 初版作成（Codex CLI エージェント）
