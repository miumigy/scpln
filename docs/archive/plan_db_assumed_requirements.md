# Plan DB 永続化 想定仕様（ヒアリング代替）

- 最終更新: 2025-10-05
- 前提: 本プロジェクトは実運用前段階につき、業務ヒアリングを行わず想定仕様で設計を進める。
- 目的: P0タスク（T0-2/T0-3）の入力値として、粒度・KPI・保管期間・非機能要件を仮定し、後続設計の判断材料とする。

## 1. 粒度・スコープ想定
- 時間粒度: 週次（ISO週）を中心とし、cutover以降は月次集計も提供。日次粒度は当面対象外。
- 品目粒度: `family`（需要計画）・`sku`（供給計画）の双方を保持。ロケーションは `site`（工場/倉庫）と `region` を保持し、ネットワーク分析用に `network` カラムを追加。
- Cutover境界: `cutover_flag`（当週）、`boundary_zone`（pre/at/post）を付与。`window_index`（cutoverからのオフセット）で整合ウィンドウ分析を可能にする。
- 利用想定: Planning Hub UI での閲覧・差分比較、S&OP資料、シミュレーション結果との比較。

## 2. KPI・レポート想定
- 必須KPI: `fill_rate`, `backlog_days`, `inventory_turns`, `capacity_util`, `cost_variance`, `service_level`, `on_time_rate`。
- 集計単位: `total`（Plan全体）, `week`, `month`, `family`, `sku`, `site`。Plan確定毎に計算し、`plan_kpis` に格納。
- 更新タイミング: Plan確定時（`status=active`）と RunRegistry連携時に計算。再整合/再実行時は同一versionで上書き。
- レポート: CSVエクスポート（週次/Family/Site別）と将来のBI接続を想定。CSVは `plan_export.py` で生成。

## 3. 保管期間・ライフサイクル想定
- Planバージョン保持: 最低18か月（S&OPレビュー用）。
- KPI・差分ログ保持: 24か月。監査イベントは36か月。
- 自動削除: `PLANS_DB_MAX_ROWS`（既定600）で古いPlanをアーカイブテーブルへ移動。削除前にCSVエクスポートを取得。
- 凍結ポリシー: `status=approved` 以降はUI編集を禁止。再実行は `duplicate` 作成で対応。

## 4. 連携・クエリ想定
- RunRegistry連携: `plan_jobs.run_id` と `plan_kpis.run_id` で双方向トレース。Run詳細からPlan集計へ遷移できるリンクを提供。
- Canonical設定: `config_version_id` を全テーブルに保持し、Canonicalスナップショットの復元を容易にする。
- BI/DWH: 週次バッチで `plan_series` を Parquet出力し、外部DWH（例: BigQuery）へ取り込み。
- クエリ負荷: 同時アクセスは10ユーザ以内。重い集計は `plan_kpis` で先に算出し、`plan_series` は詳細分析時のみ利用。

## 5. ロック・監査・通知想定
- ロック戦略: 行ロック（family×period, sku×week）を採用。`lock_flag` と `locked_by` を `plan_overrides` に保持。悲観ロックは導入せず最終書き込み優先。
- 監査イベント: `edit`, `lock`, `unlock`, `submit`, `approve`, `reconcile`, `rollback`, `export`。最新10,000件まで保持。
- 通知: `approve` 成功時と `PlanRepository` での書き込み失敗時に Slack Webhook 通知（想定）。
- 権限: APIキーによる認証。閲覧/編集の役割分離は将来対応とする。

## 6. 非機能要件想定
- 性能: `POST /plans/integrated/run` のP95 3分以内（weeks<=12, SKU<=5k）。集計APIはP95 1.5秒以内。
- 容量: `plan_series` 1 Planあたり最大 5M 行を想定。SQLite→PostgreSQL移行を前提にインデックス方針を検討。
- 可用性: RPO 1日、RTO 4時間。バックアップは日次（RunRegistryと同タイミング）。
- 監査: 重要イベントを `plan_overrides` と `plan_jobs` で保持し、Log出力にも残す。

## 7. 想定に基づくTODO更新
- T0-2/T0-3 は本ドキュメントの想定を前提に「仮完了」とする。実運用時に再ヒアリングが必要になった場合はタスクを再オープン。
- 想定値は P1レビューで検証し、矛盾があればここを更新すること。

## 8. 実装フェーズ準備メモ
- ブランチ戦略: `feature/plan-repo` ブランチでT2-1〜T2-4 を実装し、設計完了後に `main` へマージ。必要に応じ `feature/plan-ui`（P3）を派生。
- スプリント案:
  1. Sprint1: T2-1 + T2-4（PlanRepository実装とユニットテスト）。
  2. Sprint2: T2-2（計画スクリプトリファクタ）。
  3. Sprint3: T2-3（API/ジョブ切替）＋ T3-1（APIサマリ）。
- コードレビュー: 主要変更ごとにPRを分割し、CI（pytest + mypy + alembic smoke）を必須チェック化。
