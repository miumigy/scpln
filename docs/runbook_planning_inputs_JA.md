# Planning Input Sets 運用Runbook

`planning_input_sets` を用いた入力データ管理・承認・監査・フォールバック対応の手順をまとめた運用ドキュメントです。Planning Hub、CLI、REST API を跨いだ実務で参照してください。

## 1. 対象と前提
- `/ui/plans/input_sets`（Planning Hub）、`scripts/` 配下のCLI、`/api/plans/input_sets` 系RESTエンドポイントが対象。
- 需要・能力・ミックス・在庫・入荷・期間指標・カレンダー・計画パラメータを正規化した `planning_input_sets` テーブルを管理。
- `.venv` を利用したCLI実行権限、Planning Hubへのアクセス権限が必要。

## 2. ライフサイクル

| ステータス | 目的 | 作成・遷移元 |
|------------|------|--------------|
| `draft` | アップロード直後・レビュー待ちの入力セット。何度でも上書き可能。 | UIアップロードフォーム、`scripts/import_planning_inputs.py`（デフォルトで `status="draft"`、イベント `upload` を記録）。 |
| `ready` | 承認済みで Plan/Run/Export から参照可能。 | `/ui/plans/input_sets/{label}/review` のフォームで承認。 |
| `archived` | 参照されなくなった履歴用。 | UIには露出しないため、`update_planning_input_set` を介して手動設定。 |

ステータス変更時には `approved_by`, `approved_at`, `review_comment` が更新され、`planning_input_set_events` に `approve/revert` などが追記されます。

## 3. 承認ワークフロー

1. **登録/更新**
   - CLI: `PYTHONPATH=. .venv/bin/python scripts/import_planning_inputs.py -i <dir> --version-id <id> --label <label>` で登録。結果は `tmp/reports/import_planning_inputs.json` に出力。
   - UI: 「Planning > Input Sets > Upload」でCSV/JSONを送信すると自動的に `draft` で保存。
2. **Diff/検証**
   - `/ui/plans/input_sets/{label}/diff` で比較。初回アクセス時に `scripts/export_planning_inputs.py --diff-against` をバックグラウンド実行し、`tmp/input_set_diffs/` にキャッシュを作成。
   - CLI出力やアップロード結果から検証エラーを解消してから承認へ進む。
3. **承認（Draft→Ready）**
   - 詳細画面の「Review」タブで以下を送信。
     - `Action`: `Approve`
     - `Reviewer`: 社員ID（未入力時は `ui_reviewer`）
     - `Comment`: `JIRA-123 approve by ops_lead` などのテンプレ推奨
   - `approved_by/approved_at` が記録され、`approve` イベントが追加される。
4. **差戻し（Ready→Draft）**
   - 同じフォームで `Action=Revert` を選択し、コメントに理由を残す。承認メタがクリアされ `revert` イベントが追加。

### UIを使えない場合
`core.config.storage.update_planning_input_set` と `log_planning_input_set_event` を呼び出す短いPythonスクリプトで `status` と `approved_*` を更新する。必ずイベントを残し、UI承認と同じ証跡を維持する。

## 4. 監査証跡の取得

1. **定期キャプチャ**
   - UI: History表（Action/Actor/Comment/JST）をスクリーンショット化。
   - CLI:
     ```bash
     PYTHONPATH=. .venv/bin/python scripts/show_planning_input_events.py \
       --label weekly_refresh --limit 100 --json \
       > tmp/audit/input-set-weekly_refresh-$(date +%Y%m%d).json
     ```
   - REST: `curl -H "Authorization: Bearer $TOKEN" "https://<host>/api/plans/input_sets/weekly_refresh/events?limit=100" | jq '.'`
2. **証跡フォルダ**
   - `evidence/input_sets/<label>/<YYYYMMDD>/events.json`（CLI/REST結果）と `history.png`（UIキャプチャ）を保存。
   - `evidence/` は git 管理外のまま、週次でS3等へアーカイブ。
3. **トラブル対応**
   - `Input set 'foo' not found.` → ラベルのタイプミス、または Draft ラベル（`foo@draft`）が原因。UIカードのコピー機能か `scripts/list_planning_input_sets.py` で確認。
   - イベント0件 → インポート時にイベント記録が無効化されていないか確認し、必要に応じて `log_planning_input_set_event` で補完。

## 5. Plan/Run 警告への対応

| 警告 | 意味 | 対処 |
|------|------|------|
| `Legacy mode` | Plan/Run に `input_set_label` が無い。 | 承認済みInputSetを指定して再実行。どうしても再実行できない場合は、使用したCSVバンドルの証跡と例外理由をRunノートへ添付。 |
| `Missing InputSet` | Plan/Runが参照するラベルがDBに存在しない。 | 過去のエクスポートを同じラベルで再インポート、またはPlanを新しいReadyセットに紐付け直す。 |

具体手順:
1. Plan/Run詳細の警告カードに表示されるコマンド例を確認。
2. `PYTHONPATH=. .venv/bin/python scripts/import_planning_inputs.py -i out/planning_inputs_<label> --version-id <id> --label <label>` でエクスポート済みファイルを再登録。
3. 解消しない場合は Run detail から `planning_input_set.json` をダウンロードし、ハッシュ確認後にSREへエスカレーション。
- 監視指標: `run_without_input_set_total{entrypoint="/runs"}` が10分で5件を超えたらLegacy強制運用としてアラート。`plan_artifact_write_error_total{artifact="planning_input_set.json"}` も通常は 0 のまま維持されるため、増加時はDB/ファイル権限を調査する。

## 6. Diffジョブ監視と復旧

- ログ確認: `rg -n "input_set_diff_job_failed" uvicorn.out datasette.out`
- キャッシュ削除: `rm tmp/input_set_diffs/<label>__<against>.json` → Diff画面を再読み込み。
- メトリクス:
  - `input_set_diff_jobs_total{result="success|failure"}` で非同期ジョブの成功/失敗を監視（5分で失敗3件以上ならアラート）。
  - `input_set_diff_cache_hits_total` / `input_set_diff_cache_stale_total` でキャッシュ健全性を把握。
  - いずれもPrometheus/Grafanaに配線し、Planning Inputs ダッシュボードへ表示する。

## 7. 参照ドキュメント
- CLIチートシート: `README.md` / `README_JA.md`
- 仕様・バックログ: `docs/temp_planning_inputs_visibility.md`
- エスカレーション: Diffジョブ → Slack `#planning-alert`、Legacy/フォールバック関連 → `#scpln-ops`
