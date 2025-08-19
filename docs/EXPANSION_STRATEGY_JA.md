# SC計画/IBP 向け拡張戦略（エンタープライズ対応）

本ドキュメントは、本リポジトリ（FastAPI + エンジン + UI + テスト）を起点に、エンタープライズユースのサプライチェーン計画（S&OP/IBP）アプリへ段階的に拡張するための方針を示します。範囲は機能・非機能・運用を含みます。

## 現状サマリ
- 構成: FastAPI（API/UI）、`engine/simulator.py`（日次離散シミュレーション）、`domain/models.py`（Pydantic）、`app/*`（API/UI/CSV/RunRegistry）、`data/scpln.db`（Configs用SQLite）、Docker/CIあり
- 機能: 需要伝播、在庫補充、リードタイム、PL/コスト、コストトレース、実行履歴（メモリ）、設定マスタ永続化（SQLite）、比較UI/CSV、テスト多数
- 運用: `scripts/serve.sh`/`status.sh`/`stop.sh`、ヘルスチェック、ログ出力（ファイル/コンソール）

## 主なギャップ（IBP/エンタープライズ）
- 永続化: RunRegistryがメモリ（監査/容量に弱い）
- 多ユーザー: 認証/認可（SSO/OIDC, RBAC）、テナント分離、監査証跡
- 計画階層: 日次のみ（週次/月次の粗密バケットが必要）
- 最適化: 発注/生産/配分の最適化（MILP/CP/ヒューリスティク）
- 需要予測: 統計/MLと合意形成（Consensus）
- シナリオ管理: 親子/バージョン/承認フロー、比較の体系化
- 拡張性: ポリシー/コスト/制約のプラガブル化、後方互換の型/スキーマ管理
- 性能/スケール: 大規模データ処理、非同期/ジョブ、水平スケール
- 統合: ERP/WMS/MES/MDM/外部予測基盤との連携
- 運用: 可観測性、バックアップ/DR、構成/セキュリティ、SLA

## ロードマップ（4フェーズ）
### フェーズ1: 基盤強化（データ/運用/セキュリティ）
- Run永続化: RunRegistryをDB化（SQLite→PostgreSQL）。`app/db.py`/`app/run_registry.py`拡張、`runs`表（メタ+成果物）と索引、ページング
- スキーマ管理: `schema_version`の厳格化とマイグレーション（Alembic）、後方互換レイヤ
- 認証/認可: OIDC/OAuth2、`TenantID`/`OrgID`/`Role`（Planner/Approver/Viewer）
- ジョブ管理: 非同期実行（RQ/Celery/BackgroundTasks）、状態（queued/running/succeeded/failed）
- 観測性: 構造化ログ、OpenTelemetry、基本メトリクス（実行時間/失敗率/キュー滞留）

### フェーズ2: 層別計画とスケール
- 時間バケット: `TimeBucketStrategy`（day/week/month）で粗密可変、集計/分配ユーティリティ
- シナリオ管理: `scenarios`（親子/タグ/バージョン/ロック）、差分保存（JSON-Patch）、比較UI強化
- 性能: ベクトル化（NumPy）/差分実行/ストリーミングCSV/メモリ削減
- ジョブ分散: 複数ワーカー、優先度キュー、長時間計算の再開/中断、成果物アーカイブ

### フェーズ3: 需要予測・最適化（OR）・S&OP/IBP
- 予測: ETS/ARIMA/Prophet + ML（XGBoost/LSTM）をプラグイン。`/forecast` API、学習/評価/フリーズ
- 補充最適化: サービスレベル下の在庫最適化（安全在庫/MEIO近似、MOQ/発注倍数）
- 生産/配分: MPS/MRP/有限能力（MILP/CP/ヒューリスティク選択式）、供給配分優先順位
- IBP: 財務ブリッジ（Volume→Value）、KPI（収益/在庫投資/OTIF）、合意ワークフロー（草案→レビュー→承認）

### フェーズ4: 統合・ガバナンス・SRE
- 統合: ERP/WMS/MES/MDMコネクタ（バッチ/API/SFTP）、CDC/ETL、データ品質ルール
- セキュリティ: 行レベル制御、PII保護、監査証跡、コンプライアンス
- SRE: オートスケール、RTO/RPO、障害注入、コスト最適化（外部DWH/湖活用）

## 実装ガイド（リポジトリ対応）
- Run永続化:
  - `app/db.py`: RDB接続（SQLite/PostgreSQL切替）、セッション/DAO
  - `app/run_registry.py`: DB-backed 実装（insert/update/status, artifacts参照）、メモリ実装はフォールバック
  - `app/run_list_api.py`/`app/ui_runs.py`: ページング/フィルタ/ソート、`detail=false`既定、最大サイズガード
  - `tests/`: ページング/E2E/CSV整合
- スキーマ/互換:
  - `domain/models.py`: `schema_version`/アップグレード関数
  - `tests/test_schema_version.py`: 互換性テスト強化
- 時間バケット:
  - `engine/`: `TimeBucketStrategy`（day/week/month）層と集計関数
  - `tests/`: 週次/月次サマリの検証
- 非同期実行:
  - `app/simulation_api.py`: ジョブ起動API（job_id返却）、`/runs/{id}`でポーリング
  - `scripts/serve.sh`/`status.sh`: ワーカー起動/キュー可視化
- シナリオ管理:
  - `app/config_api.py`: `scenario` エンティティ（親子/タグ/説明/ロック）、差分保存
  - `app/ui_compare.py`: KPI差分の閾値ハイライト
- セキュリティ/RBAC:
  - `app/api.py`: OIDC保護、スコープ→Role、`TenantID`/`OrgID`コンテキスト
  - `tests/`: 認可ポリシーテスト

## 非機能（運用）
- 可観測性: OpenTelemetry導入、リクエストID/RunID相関、基本メトリクス
- 構成管理: `.env`/Vault、`SIM_LOG_LEVEL` 等のドキュメント整備
- データ運用: 古いRunのアーカイブ、オブジェクトストレージ退避、バックアップ/復元
- CI/CD: マイグレーション自動適用、スキーマ差分チェック、負荷スモーク

## OR/最適化の実装順
1. 安全在庫・補充点の再設計（MEIO近似、需要分散/サービスレベル）
2. 輸送/生産のLP定式化（容量/リードタイム制約 + コスト最小化）
3. 有限能力の段階導入（CP/ヒューリスティク）
- 切替可能なソルバ層（`PuLP`/`OR-Tools`）＋ヒューリスティクのフォールバック

## 短期アクション（M1フォーカス）
- Run永続化の土台（`runs`テーブル、DAO、ページング）
- `/runs` API堅牢化（`detail=false`既定、サイズ上限、ソート）
- 非同期化（ジョブ管理、状態/ログ分離保存）
- `schema_version`厳格化 + 互換テスト強化
- 観測性（構造化ログ、基本メトリクス）
- README更新（データ保持/互換ポリシー、サイジング、SLA初期値）

## マイルストーン
- M1（2–3週）: Run永続化、ページング、観測性、スキーマ版管理
- M2（3–4週）: 非同期実行、シナリオ管理1.0、週次バケット
- M3（4–6週）: 需要予測β、補充最適化LP、IBP KPIと比較UI強化
- M4（継続）: 多テナント/RBAC、Postgres本番、外部連携、SRE/DR

## 成功指標（抜粋）
- 機能: KPI差分検知精度、IBP指標（収益/在庫投資/OTIF）可視化カバレッジ
- 性能: 代表ケースのP95実行時間/メモリ、同時実行のスループット
- 運用: SLO達成率、障害復旧時間、データ保持/監査網羅率

## リスクと緩和
- 大規模データでの性能劣化 → ベクトル化/差分実行/分散ワーカーで緩和
- スキーマ破壊的変更 → バージョン/移行関数と互換テストで回避
- 外部統合の不確実性 → コネクタ層を抽象化し段階導入

---
本ドキュメントは継続的に更新し、READMEからリンクします。実装順は上記マイルストーンを基準に、利用現場の優先要件（規模/連携/SLA）に応じて調整します。
