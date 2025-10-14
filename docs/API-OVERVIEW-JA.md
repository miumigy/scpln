# API概要（Planning Hub関連, P-23）

本書は Planning Hub / 計画パイプラインで利用する主要REST・CSVエンドポイントを俯瞰するためのサマリです。詳細な用語は `docs/TERMS-JA.md`、ワークフローは `docs/TUTORIAL-JA.md` を参照してください。認証やシークレット運用は README と `docs/SECRET_ROTATION_JA.md` に整理しています。

## ヘルス/メトリクス
- GET `/healthz` ヘルスチェック
- GET `/metrics` Prometheusメトリクス（plans_created_total ほか）

## Planning Hub UI（HTML）
- GET `/ui/plans` プラン一覧（作成フォーム含む）
- POST `/ui/plans/run` 統合Runで新規Plan作成（同期）
- GET `/ui/plans/{version_id}` プラン詳細（タブ: Overview/Aggregate/Disaggregate/Schedule/Validate/Execute/Results）
- POST `/ui/plans/{version_id}/plan_run_auto` Plan & Run（自動補完; /runs経由で新規Plan）
- POST `/ui/plans/{version_id}/reconcile` 再整合実行（必要に応じanchor/adjusted）
- POST `/ui/plans/{version_id}/state/advance` / `/state/invalidate` state遷移/無効化

## Planning API（JSON/CSV）
- GET `/plans` 登録済みPlan一覧
- POST `/plans/integrated/run` 統合パイプライン実行（aggregate→allocate→mrp→reconcile）し、新規Plan登録。`lightweight=true` を指定するとCI/E2E向けにMRP・reconcile系をスキップし、PlanRepository書込みと主要アーティファクトのみ生成。
- GET `/plans/{version_id}/summary` Plan要約（reconciliation summary / weekly_summary）
- GET `/plans/{version_id}/compare` 差分一覧（violations_only, sort, limit）
- GET `/plans/{version_id}/compare.csv` 上記のCSV出力
- GET `/plans/{version_id}/carryover.csv` anchor/carryoverの遷移CSV出力
- GET `/plans/{version_id}/schedule.csv` 予定オーダ（mrp.jsonから）CSV出力
- POST `/plans/{version_id}/reconcile` aggregate×DETの整合評価（before/adjusted）

## Run API（RunRegistry & 実行）

シミュレーションの実行（Run）と、その結果の永続化・取得・比較（RunRegistry）を担うエンドポイント群です。

- **`GET /runs`**: 実行履歴（Run）の一覧を取得します。
  - `detail=true`: 結果詳細を含む完全なデータを返します。
  - `limit`, `offset`: ページネーションを制御します。
  - `sort`, `order`: `started_at` などのキーでソートします。
  - `config_version_id`, `scenario_id`, `plan_version_id` などで結果をフィルタリングできます。

- **`POST /runs`**: 新しいRunを同期または非同期で実行します。主に統合パイプライン (`pipeline: "integrated"`) のトリガーとして使用されます。
  - `async=true`: 非同期でジョブを投入し、`job_id` を返します。
  - `async=false` (既定): 同期実行し、完了後にPlanの `version_id` を返します。
  - `options`: `config_version_id` (必須) や `weeks`, `cutover_date` などのパイプライン実行時パラメータを指定します。
  - (リクエストボディの詳細は旧版の記述を参照)

- **`GET /runs/{run_id}`**: 指定したIDのRun詳細情報を取得します。
  - `detail=true` を付けると、KPIサマリだけでなく、日次の詳細な結果も含まれます。

- **`DELETE /runs/{run_id}`**: 指定したIDのRunを削除します。RBACが有効な場合は特定のロール（`planner`, `admin`）が必要です。

- **`POST /compare`**: 複数のRun (`run_ids`で指定) のサマリ情報を比較します。
  - `base_id` を指定すると、それを基準に差分（絶対値・変化率）を計算します。

- **`GET /runs/{run_id}/meta`**: 指定したRunのメタ情報（承認状態、ベースライン設定、ノートなど）を取得します。

- **`POST /runs/{run_id}/approve`**: Runを「承認済み」としてマークします。

- **`POST /runs/{run_id}/promote-baseline`**: Runをシナリオの「ベースライン」として設定します。

- **`POST /runs/{run_id}/archive`**: Runをアーカイブ（論理削除）します。

- **`POST /runs/{run_id}/unarchive`**: アーカイブ状態を解除します。

- **`POST /runs/{run_id}/note`**: Runに自由記述のノート（メモ）を追加・更新します。

- **`GET /runs/baseline?scenario_id={id}`**: 指定したシナリオの現在有効なベースラインRunのIDを返します。

## データ保存モード (`storage_mode`)

`POST /plans/integrated/run` API や関連するCLIでは、計画データの保存方法を `storage_mode` パラメータで制御できます。

### モードの種類

| モード | 説明 | 主なユースケース |
| :--- | :--- | :--- |
| `db` | 計画データをデータベース（PlanRepository）にのみ保存します。JSONファイルは出力されません。 | 本番環境での標準的な運用。データの永続性と一貫性が保証されます。 |
| `files` | 従来通り、計画データを `out/` ディレクトリ配下にJSONファイルとしてのみ保存します。データベースには書き込まれません。 | デバッグ、ローカルでの一時的な分析、または旧バージョンとの互換性維持。 |
| `both` | データベースとJSONファイルの両方に計画データを保存します。 | データベース移行期間中の安全策や、DBとファイルの双方でデータを参照したい場合。 |

### 指定方法

- **API**: `POST /plans/integrated/run` のリクエストボディに `"storage_mode": "db"` のように含めます。
- **環境変数**: 環境変数 `PLAN_STORAGE_MODE` に `db`, `files`, `both` のいずれかを設定することで、全実行のデフォルトモードを指定できます。APIリクエストで `storage_mode` が指定された場合は、そちらが優先されます。
- **デフォルト**: `storage_mode` の指定も環境変数もない場合、デフォルトの挙動は `both` です。

## 比較（CSV）
- GET `/ui/compare/metrics.csv?run_ids={id1},{id2}` 指標比較CSV
- GET `/ui/compare/diffs.csv?run_ids={id1},{id2}&threshold=5` 差分比較CSV

## レガシーUI
- 旧UI `/ui/planning` は廃止しました。入口は `/ui/plans` を利用してください。

備考:
- すべてのJSON/CSVはUTF-8。CSVはtext/csv; charset=utf-8で返却。
- 認証は環境変数 `AUTH_MODE`（none/apikey/basic）で切替。
