# Plan DB 移行チェックリスト

PlanRepository への本格移行に向け、Dev → Staging → Production の段階で実施すべき作業をチェックリスト化する。各ステップは順序を守り、完了時には証跡（ログ・スクリーンショット・PR）を残すこと。

## 共通準備
- [ ] Alembicを`head`まで適用できることを確認（`PYTHONPATH=. alembic upgrade head`）。
- [ ] `scripts/plan_backfill_repository.py --dry-run` を対象環境のDBで実行し、対象行数とKPI件数を把握。
- [ ] Prometheusメトリクスが取得可能か確認（`/metrics` で `plan_db_*` 系指標が露出していること）。
- [ ] `docs/plan_db_rollback_runbook.md` を通読し、旧 `plan_artifacts` への切り戻し手段と役割分担を担当者全員が把握。

## Dev 環境
- [ ] `git status` をクリーンにし、PlanRepository関連の最新変更を `main` へ追従。
- [ ] `scripts/plan_backfill_repository.py --force --state-file tmp/dev-backfill.json` を実行し、PlanRepositoryへ全versionを書き込み。
- [ ] `PYTHONPATH=. pytest tests/test_plan_backfill_repository.py` を実行し、バックフィルおよびPlanRepository検証テストが緑であることを確認。
- [ ] `/plans` API と `/ui/plans` UI を目視で確認し、Summary/KPIがPlanRepository経由で表示されることを確認。
- [ ] `data/scpln.db` のバックアップを取得（例: `cp data/scpln.db backup/plan_db_dev_YYYYMMDD.db`）。

## Staging 環境
- [ ] Alembic適用とPlanRepositoryテーブルの存在を確認（`sqlite3 data/scpln.db ".tables"`）。
- [ ] `scripts/plan_backfill_repository.py --state-file tmp/stg-backfill.json --limit 5 --dry-run` でサンプル件を検証後、`--force` なしで全件バックフィル。
- [ ] 代表的なPlan（三件以上）について `/plans` API・UIでAggregate/Detailが表示されること、CSVエクスポートが機能することを確認。
- [ ] `/metrics` に `plan_db_write_total` `plan_db_write_latency_seconds` が出力され、Alertmanagerの設定が正しいことをSREが承認。
- [ ] バックフィル後の `plan_series` 行数を記録し、容量見積り（PLANS_DB_MAX_ROWS）を更新。

## Production 環境
- [ ] 実施ウィンドウ（低負荷帯）に合わせて通知。Plan作成APIをメンテナンスモードに切替。
- [ ] `data/scpln.db` を停止前にバックアップし、S3または安全な保管先へアップロード。
- [ ] `scripts/plan_backfill_repository.py --state-file /var/log/plan_backfill_state.json --resume-from <previous-version>` を実行し、完了ログとstateファイルを保存。
- [ ] バックフィル完了後に `/plans` API・UI を運用チームと共にスポット確認（KPI値・履歴イベント・Runリンク）。
- [ ] Plan作成APIのメンテナンス解除、および利用者告知。
- [ ] 24時間以内にメトリクスとログを確認し、`plan_db_write_error_total` が増えていないことを監視。

## フォローアップ
- [ ] バックフィルstateファイルと実行ログをリポジトリ/Runbookに添付し、トレーサビリティを確保。
- [ ] 残存する旧 `plan_artifacts` 依存コードを洗い出し、段階的に削除するPR計画を整理。
- [ ] `PlanRepository` データボリュームの定期モニタリングと、自動トリミング（T4-3）のスケジュールをCronに組み込む。
- [ ] ロールバックRunbookを四半期ごとにドリルし、環境変数やリリースタグの更新漏れがないか確認。
- [ ] `PLANS_DB_MAX_ROWS` 設定時は `plan_db_capacity_trim_total` を監視し、ガードレール発火状況と通知連携を確認。
- [ ] `PLANS_DB_GUARD_ALERT_THRESHOLD` を本番想定値へ設定し、`plan_repository_capacity_trim_alert` ログおよび `plan_db_last_trim_timestamp` が Alertmanager/ログ基盤に取り込まれることを確認。
- [ ] バックフィル後に `plan_backfill_runs` テーブルへ実行履歴が保存されていることを確認し、`status`/`errors` の推移を監視対象へ追加。
