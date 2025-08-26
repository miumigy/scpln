# 変更履歴

## Unreleased

## v0.4.0 (2025-08-26)

- feat(planning): 粗密計画パイプラインを実装（aggregate→allocate→mrp→reconcile→report）
  - PR2: 粗粒度S&OPヒューリスティク（需要×能力の比例配分）
  - PR3: family→SKU, 月→週の按分（丸め/誤差吸収）
  - PR4: MRPライト（LT/ロット/MOQ、在庫/入荷、任意BOM）
  - PR5: 能力整合（CRPライト）週次能力に合わせ解放を調整
  - PR6: 受入再配分＋KPI（稼働率/Fill Rate）CSV出力
  - PR7: 一括実行スクリプト `scripts/run_planning_pipeline.sh` 追加、README整備
- chore(docs): 進捗ドキュメント/進行JSONを削除しREADMEへ集約

## v0.3.7 (2025-08-23)

- feat(scenario): シナリオに基づいたシミュレーション実行と結果比較機能を追加
  - DBに `scenario_id` カラムを追加し、シミュレーション実行結果にシナリオ情報を紐付け。
  - API (`/simulation`, `/runs`) が `scenario_id` をサポート。
  - シナリオ一覧画面から、設定を選択してシミュレーションを実行するUIを追加。
  - ベースシナリオとターゲットシナリオを指定し、最新の実行結果を比較するUIプリセット機能を追加。
  - 変更系のAPIエンドポイントにRBAC（ロールベースアクセス制御）を追加。
- （運用）Auto-merge 設定とコンフリクト検出ワークフローの整備（継続）
- fix(api): /ui/hierarchy が表示されない問題を修正（mainで app.hierarchy_api / app.ui_hierarchy を読み込み）

## v0.3.6 (2025-08-22)

- feat(ops): Alembic 初期構成を導入（`alembic.ini`/`env.py`/`versions/0001_initial.py`）。`SCPLN_DB` と連動し、CIで `alembic upgrade head` を実行
- feat(security): 簡易認証トグル `AUTH_MODE=none|apikey|basic` を追加。`API_KEY_HEADER`/`API_KEY_VALUE`、`BASIC_USER`/`BASIC_PASS` に対応
- feat(obs): OpenTelemetry 計装を追加（`OTEL_ENABLED=1` で有効化、`OTEL_EXPORTER_OTLP_ENDPOINT` に対応）
- chore(ops): DBバックアップ/復元スクリプトを追加（`scripts/backup_db.sh` / `scripts/restore_db.sh`）
- docs: README に認証/OTel/Alembic/バックアップ手順を追記、`configs/env.example` を更新

## v0.3.5 (2025-08-22)

- feat(ui/runs): ページ番号ジャンプ、First/Last 追加、列ヘッダクリックでソート切替（↑/↓表示）、行ごとの CSV 直リンク（res/pl/sum/trace）
- feat(ui/jobs): 集計フォームに `date_field`/`tz`/`calendar_mode`/`week_start_offset`/`month_len`、`product_map`/`location_map`(JSON) を追加
- feat(ui/jobs): プリセットの保存/読込に加え、Export/Import(JSON)対応、最新Runからの `group_keys`/`sum_fields` 候補自動推測と datalist 提示
- docs(readme): 上記UIの操作ガイドを追記

## v0.3.4 (2025-08-22)

- feat(aggregation): カレンダー厳密化（`date_field`/ISO週/月境界）。週開始オフセット/月長は day ベースを維持（#93）
- docs(readme): `/jobs/aggregate` に厳密カレンダー（`date_field`/`tz`/`calendar_mode`）の説明と例を追記

## 2025-08-22

- feat(api): DELETE /runs/{id} を追加（メモリ/DB両対応）
- feat(ui): ラン詳細に Delete ボタン（確認ダイアログ付き）
- feat(obs): /metrics に HTTP メトリクス（http_requests_total, http_request_duration_seconds）を追加
- perf(db): RUNS_DB_MAX_ROWS による古いRunの自動クリーンアップ（DBバックエンド時）
- docs: README に削除API・UI操作・環境変数・メトリクス一覧を追記

## 2025-08-21

- feat(api): /runs にページングを追加（`offset`/`limit`）。detail=false 既定50、detail=true 既定10（>10は400）
- feat(ui): /ui/runs にページャ（Prev/Next/Limit）とメタ表示（`total/offset/limit`）を追加
- chore(run): `REGISTRY_CAPACITY` 環境変数でメモリ保持件数を可変化（既定50）
- docs: README の API/環境変数を更新、docs/EXPANSION_STRATEGY_JA.md を参照可能に
- chore: 競合マーカー検出のCIに対応するため README の競合を解消
- chore(autofix): ruff/black による軽微な自動整形（別PR）
 - feat(obs): JSON構造化ロガー（`SIM_LOG_JSON=1`）と Request-ID 相関ログ、Uvicorn JSONロギングの`--log-config`サンプル追加
