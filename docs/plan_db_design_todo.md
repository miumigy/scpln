# Plan DB 永続化 設計タスク残一覧

- 最終更新: 2025-10-07
- 担当: Planning Hub プロダクトチーム / Codex CLI エージェント
- 進捗サマリ: 27タスク中 21完了（77%）

## 残タスク概要

| フェーズ | タスクID | 内容 | 担当候補 | 期限目安 | 状態 | メモ |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | T0-2 | 想定仕様でクエリ/KPI粒度/保管期間を仮決め | 設計担当 | 2025-10-11 | 完了 | `docs/plan_db_assumed_requirements.md` に想定値を記載。実運用開始時に再確認 |
| P0 | T0-3 | 想定非機能要件（性能/容量/ロック/監査）整理 | 設計担当 | 2025-10-14 | 完了 | 同上ドキュメント参照。SLO/P95等は仮値として設計へ反映 |
| P1 | T1-1 | plan_series 指標・粒度の最終定義 | 設計担当 | 2025-10-16 | 完了 | 週/月粒度・指標・メタ列を定義（docs/plan_db_persistence_plan.md:71、assumed_requirements参照） |
| P1 | T1-2 | plan_overrides / plan_kpis / plan_jobs スキーマ確定＋ER図 | 設計担当 | 2025-10-17 | 完了 | 列定義・インデックス方針を確定、イベント履歴はplan_override_eventsで管理 |
| P1 | T1-3 | Alembic DDLドラフトとレビュー | 開発 | 2025-10-18 | 完了 | DDL詳細/検証手順を策定、アップグレード・ダウングレードの流れを整理 |
| P1 | T1-4 | mypy / 型定義更新、core/config連携確認 | 開発 | 2025-10-18 | 完了 | PlanRepository I/F・TypedDict/Protocol方針・mypy/CI案を整理 |
| P2 | T2-1 | PlanRepository 実装（インサート/クエリAPI） | 開発 | 2025-10-25 | 完了 | core/plan_repository.py を追加。plan_series/plan_kpis/plan_overrides/plan_jobs のバルク書込みと取得を実装 |
| P2 | T2-2 | scripts/plan_*.py のPlanRepository対応リファクタ | 開発 | 2025-10-28 | 完了 | plan_aggregate / allocate / mrp / reconcile / reconcile_levels / anchor_adjust / export_reconcile_csv / report / run_planning_pipeline が `--storage/--version-id` で PlanRepository へ保存可能。共通ヘルパ `scripts/plan_pipeline_io.py` を導入し、PlanArtifacts へ JSON/CSV を格納。次フェーズはUI/API連携(T3)で利用 |
| P2 | T2-3 | app/jobs / app/plans_api からPlanRepositoryを呼ぶよう改修 | 開発 | 2025-10-30 | 完了 | jobs/plans_api双方でPlanRepositoryを優先利用し、JSONはフォールバック運用 |
| P2 | T2-4 | PlanRepository向けユニットテスト追加 | QA/開発 | 2025-10-30 | 完了 | tests/test_plan_repository.py / *_builders.py / *_views.py / *_overrides.py を追加し永続化経路を検証 |
| P3 | T3-1 | /plans APIレスポンス刷新（ページング/サマリ） | フロント/バック | 2025-11-04 | 完了 | APIレスポンスの刷新と、Plan一覧UI (`/ui/plans`) への反映が完了。 |
| P3 | T3-2 | /ui/plans UIをplan_series/plan_overrides読むよう更新 | フロント | 2025-11-06 | 完了 | Plan詳細画面のデータ取得をPlanRepositoryに移行。KPI, Aggregate, Detail, MRP, State, SourceRunIDなどをDBから取得するように変更。`recon`, `plan_final` など一部のレガシーJSONは表示互換性のために残存しているが、主要な動的データはDB化されたためタスク完了とする。 |
| P3 | T3-3 | RunRegistryリンク拡張（plan_job_id連携） | 開発 | 2025-11-06 | 完了 | run詳細にplan_job_id/Plan KPIサマリを表示し双方向リンクを実装。 |
| P3 | T3-4 | メトリクス/監視導入（PLAN_SERIES_ROWS_TOTAL など） | SRE | 2025-11-08 | 完了 | PlanRepositoryの主要メトリクス（書込み成否・レイテンシ・行数・DBサイズ）を実装し、`/metrics` で公開。 |
| P4 | T4-1 | plan_export.py 実装（DB→JSON/CSV） | 開発 | 2025-11-12 | 完了 | `scripts/plan_export.py` が PlanRepository から aggregate/det/mrp/KPI を取得し `aggregate.json` `sku_week.json` `mrp.json` `report.csv` を書き出す。CLIオプションと例外処理を実装済み。 |
| P4 | T4-2 | Runbook/ドキュメントをPlan DB前提へ更新 | ドキュメント | 2025-11-13 | 完了 | チュートリアルとRunRegistryガイドを更新し、Plan DBへの保存、storage_mode、plan_job_id、KPIサマリ表示などを反映。 |
| P4 | T4-3 | DBメンテスクリプト（バックアップ/トリム）実装 | SRE | 2025-11-14 | 完了 | DBメンテスクリプト (`plan_db_maint.py`) を作成。バックアップ、指定日数より古いPlanのトリム、最大行数を超過したPlanのトリムに対応。 |
| P5 | T5-1 | plan_artifacts → 新テーブルバックフィルスクリプト | 開発 | 2025-11-18 | 完了 | `scripts/plan_backfill_repository.py` を追加。Dry-run/状態ファイル/force再実行をサポートし、PlanRepositoryへaggregate/det/mrp/weekly_summary/KPIを投入。`tests/test_plan_backfill_repository.py` でdry-run/成功/スキップケースを検証。 |
| P5 | T5-2 | tests/test_plans_* の更新とCI追加 | QA/開発 | 2025-11-20 | 完了 | `tests/test_plans_api_e2e.py`・`tests/test_plans_ui_and_schedule.py` にPlanRepository検証を追加し、Plan生成後にaggregate/KPI/詳細行がDB化されることを確認。バックフィル用E2Eは`tests/test_plan_backfill_repository.py`で補完。 |
| P5 | T5-3 | 環境別移行チェックリスト整備 | PM/SRE | 2025-11-22 | 完了 | `docs/plan_db_migration_checklist.md` を追加し、Dev/Stg/Prod 各環境の前提・実行手順・フォローアップをチェックリスト化。 |
| P5 | T5-4 | ロールバック手順（plan_artifacts再利用）整理 | PM/SRE | 2025-11-22 | 完了 | `docs/plan_db_rollback_runbook.md` を追加し、PlanRepository障害時の切替・RunRegistry対応・検証手順を定義 |
| P6 | T6-1 | 監査イベントUI整備 | フロント/開発 | 2025-11-28 | 完了 | Plan詳細UIの履歴ダイアログに監査イベント履歴を表示。初期表示時に最新200件を取得・要約して表示する。 |
| P6 | T6-2 | PlanRepository容量ガードレール導入 | SRE/開発 | 2025-11-30 | 完了 | 運用ドキュメント(`plan_db_persistence_plan.md`)にアラート用ログの監視手順を追記。 |
| P6 | T6-3 | バックフィルスクリプト運用監視 | SRE/開発 | 2025-12-02 | 完了 | メンテナンススクリプト(`plan_db_maint.py`)にバックフィル実行状況のサマリー表示機能 (`--show-backfill-summary`) を追加。 |
| P6 | T6-4 | PSI補助アーティファクトのDB移行 | 開発 | 2025-12-05 | 完了 | `psi_weights.json` と `psi_audit.json` へのフォールバック処理をAPIから削除。PlanRepositoryへの完全移行を完了。 |
| P6 | T6-5 | `storage_mode` 利用ガイド整備 | ドキュメント | 2025-12-08 | 完了 | `API-OVERVIEW-JA.md` に `storage_mode` の使い方とユースケースを追記。 |
| P6 | T6-6 | 未決スキーマ仕様の最終決定 | 設計担当 | 2025-12-10 | 完了 | `plan_db_maint.py`にKPI定期削除機能を追加。また、`plan_repository_builders.py`に日次粒度データを扱うための準備実装を追加。 |

## 直近優先度トップ3
1. **T6-1: 監査イベントUI整備**: `plan_override_events` の `actor`/`notes` 表示と `psi_state` 最新化ロジックを `/ui/plans` 履歴ダイアログへ反映し、_docs/plan_db_audit_followups.md_ のTODOを解消する。
2. **T6-2: PlanRepository容量ガードレール導入**: `PLANS_DB_MAX_ROWS` の監視結果をダッシュボード/アラートへ接続し、`plan_repository_capacity_trim_alert` の運用ルールを固める。
3. **T6-3: バックフィルスクリプト運用監視**: `plan_backfill_runs` の履歴を可視化し、定期/スポット実行フローと監視閾値を整備する。

## メモ / 保留事項
- `plan_series` の粒度（day/week統合）と `plan_overrides` のイベントテーブル分割はレビューで決定。
- RunRegistryとの双方向リンクは `plan_jobs.run_id` と `plan_series.source_run_id` で対応予定。
- PlanRepository実装時は `sqlite3` トランザクションを明示制御し、CIで `pytest --maxfail=1` をPlan経路にも拡張。
- overrideイベントIDはPlanRepositoryで解決済。今後はイベントのactor/notes設計を詰める。
- `psi_weights` / `psi_audit` のUIワークフロー整理（編集・削除・表示）を進める。
- UI編集理由を `plan_override_events.notes` に保存する仕組みを拡張中（APIはreason/notesを受け付け済み）。表示方法を検討する。
- `psi_audit` はPlanRepositoryのイベントへ統合。旧JSONは互換用途のみ。UIでの履歴表示更新を進行中。
- `psi_state` はsubmit/approveイベントから算出可能。UI向けにlatest stateをPlanRepositoryイベントから算出するヘルパーを検討。
- state参照API `GET /plans/{version_id}/psi/state` を追加済み。UI側での利用画面改善が残タスク。
- `PLAN_STORAGE_MODE` とリクエスト指定 `storage_mode=db|files|both` の利用ガイドをドキュメントへ追記する必要がある。
