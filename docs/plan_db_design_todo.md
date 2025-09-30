# Plan DB 永続化 設計タスク残一覧

- 最終更新: 2025-10-05
- 担当: Planning Hub プロダクトチーム / Codex CLI エージェント
- 進捗サマリ: 22タスク中 7完了（31.8%）

## 残タスク概要

| フェーズ | タスクID | 内容 | 担当候補 | 期限目安 | 状態 | メモ |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | T0-2 | 想定仕様でクエリ/KPI粒度/保管期間を仮決め | 設計担当 | 2025-10-11 | 完了 | `docs/plan_db_assumed_requirements.md` に想定値を記載。実運用開始時に再確認 |
| P0 | T0-3 | 想定非機能要件（性能/容量/ロック/監査）整理 | 設計担当 | 2025-10-14 | 完了 | 同上ドキュメント参照。SLO/P95等は仮値として設計へ反映 |
| P1 | T1-1 | plan_series 指標・粒度の最終定義 | 設計担当 | 2025-10-16 | 完了 | 週/月粒度・指標・メタ列を定義（docs/plan_db_persistence_plan.md:71、assumed_requirements参照） |
| P1 | T1-2 | plan_overrides / plan_kpis / plan_jobs スキーマ確定＋ER図 | 設計担当 | 2025-10-17 | 完了 | 列定義・インデックス方針を確定、イベント履歴はplan_override_eventsで管理 |
| P1 | T1-3 | Alembic DDLドラフトとレビュー | 開発 | 2025-10-18 | 完了 | DDL詳細/検証手順を策定、アップグレード・ダウングレードの流れを整理 |
| P1 | T1-4 | mypy / 型定義更新、core/config連携確認 | 開発 | 2025-10-18 | 完了 | PlanRepository I/F・TypedDict/Protocol方針・mypy/CI案を整理 |
| P2 | T2-1 | PlanRepository 実装（インサート/クエリAPI） | 開発 | 2025-10-25 | 実装メモ有 | トランザクション/バルク挿入/エラー処理案を docs/plan_db_persistence_plan.md に記載 |
| P2 | T2-2 | scripts/plan_*.py のPlanRepository対応リファクタ | 開発 | 2025-10-28 | 実装メモ有 | storage切替（db/files/both）と共通I/Oモジュール化方針を整理 |
| P2 | T2-3 | app/jobs / app/plans_api からPlanRepositoryを呼ぶよう改修 | 開発 | 2025-10-30 | 実装メモ有 | storage_mode切替とPlanRepository呼び出しフローを整理 |
| P2 | T2-4 | PlanRepository向けユニットテスト追加 | QA/開発 | 2025-10-30 | 実装メモ有 | CRUD/再実行/ロールバック/大量挿入テスト案を整理 |
| P3 | T3-1 | /plans APIレスポンス刷新（ページング/サマリ） | フロント/バック | 2025-11-04 | 実装メモ有 | includeパラメータとPlanRepository要約を追加予定 |
| P3 | T3-2 | /ui/plans UIをplan_series/plan_overrides読むよう更新 | フロント | 2025-11-06 | 実装メモ有 | Overview/DetailタブをPlanRepositoryデータで描画する方針を整理 |
| P3 | T3-3 | RunRegistryリンク拡張（plan_job_id連携） | 開発 | 2025-11-06 | 実装メモ有 | run詳細にplan_job_id/Planサマリを表示し双方向リンクを追加予定 |
| P3 | T3-4 | メトリクス/監視導入（PLAN_SERIES_ROWS_TOTAL など） | SRE | 2025-11-08 | 実装メモ有 | Prometheusメトリクス案とアラート方針を記載 |
| P4 | T4-1 | plan_export.py 実装（DB→JSON/CSV） | 開発 | 2025-11-12 | 未着手 | CLI互換の標準ツール |
| P4 | T4-2 | Runbook/ドキュメントをPlan DB前提へ更新 | ドキュメント | 2025-11-13 | 未着手 | Tutorial/RunRegistryガイド改訂 |
| P4 | T4-3 | DBメンテスクリプト（バックアップ/トリム）実装 | SRE | 2025-11-14 | 未着手 | `scripts/plan_db_maint.py` 追加 |
| P5 | T5-1 | plan_artifacts → 新テーブルバックフィルスクリプト | 開発 | 2025-11-18 | 未着手 | Dry-run/ログ/リジューム実装 |
| P5 | T5-2 | tests/test_plans_* の更新とCI追加 | QA/開発 | 2025-11-20 | 未着手 | PlanRepository経路の統合テスト |
| P5 | T5-3 | 環境別移行チェックリスト整備 | PM/SRE | 2025-11-22 | 未着手 | Dev→Stg→Prod 手順書 |
| P5 | T5-4 | ロールバック手順（plan_artifacts再利用）整理 | PM/SRE | 2025-11-22 | 未着手 | 旧構造とRunRegistry影響を文書化 |

## 直近優先度トップ3
1. T0-2 ヒアリング実施：業務側の粒度・保持期間を確定させないとP1以降のスキーマがFIXできない。
2. T1-1/T1-2 スキーマレビュー：DDL化前に粒度／監査イベント設計を確定。
3. T1-3 Alembicドラフト：P1レビューの結果を反映し、早期にDDLレビューを回す。

## メモ / 保留事項
- `plan_series` の粒度（day/week統合）と `plan_overrides` のイベントテーブル分割はレビューで決定。
- RunRegistryとの双方向リンクは `plan_jobs.run_id` と `plan_series.source_run_id` で対応予定。
- 容量増対策として `PLANS_DB_MAX_ROWS`（環境変数）の導入が必要。実装はT2以降で検討。
- PlanRepository実装時は `sqlite3` トランザクションを明示制御し、CIで `pytest --maxfail=1` をPlan経路にも拡張。
