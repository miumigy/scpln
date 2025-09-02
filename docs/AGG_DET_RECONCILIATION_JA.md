# 集約↔詳細 計画の統合・整合設計（案）

本書は、集約レベル計画（例: ファミリ×週/月）と詳細レベル計画（例: SKU×日）の両立・整合を、単一の計画バージョン上で運用するための設計案です。直近は詳細主導、先々は集約主導としつつ、境界での断絶なく整合することを目的とします。

## 目的・要件
- 一貫バージョン: 同一 `plan_version` に集約・詳細の両計画を格納し、相互参照・比較・整合を可能にする。
- 双方向整合:
  - 下り: 集約計画 → 詳細按分（制約・BOM・能力を考慮）
  - 上り: 詳細計画 → 集約ロールアップ（差異・残差の可視化）
- 境界整合: 直近（詳細）と先々（集約）の境目で、在庫・需要・バックログ・WIPが連続する。
- 保存則: 需要・供給・在庫収支のトータルは、レベル/粒度変換後も一致。
- 運用: 再現性（idempotency）、段階的な導入、計算時間の制御、監査可能なログ。

## 用語・前提
- レベル: `AGG`（集約）/`DET`（詳細）。
- 粒度: 時間（週・月 vs 日）、品目（ファミリ vs SKU）、場所（拠点/ネットワーク）。
- 境界日: `cutover_date`。`< cutover` は詳細、`≥ cutover` は集約を原則とする。
- 整合ウィンドウ: `recon_window_days`。境界前後の数日（例: ±3〜7日）で厳格整合を実施。

## データモデル（DB/JSON）
- `plan_versions`:
  - `version_id` (PK), `created_at`, `base_scenario_id`, `status`(draft/active/superseded), `cutover_date`, `recon_window_days`, `objective`, `note`。
- `plan_rows`（正規化、もしくはJSON列に格納）:
  - 共通キー: `version_id`, `level`(AGG/DET), `time_bucket`(date or period), `item_key`(sku or family), `location_key`。
  - 指標: `demand`, `supply`, `prod_qty`, `ship_qty`, `inventory_open`, `inventory_close`, `backlog`, `capacity_used`, `cost_*`。
  - メタ: `source`(aggregate|allocate|mrp|recon|override), `lock_flag`, `quality_flag`。
- `reconciliation_log`:
  - `version_id`, `window_start`, `window_end`, `delta_metric`, `delta_value`, `policy`, `run_id`, `summary`。

JSONスキーマ（簡略）例: `out/plan_final.json`
- `version`: `string`
- `cutover_date`: `YYYY-MM-DD`
- `levels`: `{ "AGG": [...], "DET": [...] }` の配列。各要素は上記キー/指標を保持。

## アーキテクチャとフロー
- フェーズ（標準）:
  1) Aggregate（粗粒度S&OP）
  2) Allocate（按分: 集約→詳細）
  3) MRP/CRPライト（詳細の資材・能力整合）
  4) Reconcile（詳細→集約ロールアップと差の解消）
  5) Report/KPI
- オーケストレーション: `plan_integrated(version_id, cutover_date, recon_window_days, policy)` を中核にDAG実行。
- 再実行: 入力/パラメタが同一なら同一 `version_id` で上書き可能（`lock_flag` がある行は保持）。

## 整合アルゴリズム（要点）
- 集約→詳細（Allocate）:
  - 時間粒度: 週/月→日配分（営業日/稼働日ウェイト、需要位相、リードタイム/キャパ制約）
  - 品目粒度: ファミリ→SKU配分（過去実績ミックス、プロモ、優先度、サービスレベル重み）
  - 丸め: `round=int|bankers`。残差は需要優先・在庫余力・コスト低の順に再配分。
- 詳細→集約（Roll-up）:
  - 同一 `version_id` のDETをロールアップし、AGGとの差分`Δ`を算出。
  - `|Δ| ≤ tol`（許容）なら採用。超過ならポリシー適用。
- ポリシー（例）:
  - `anchor=DET_near`：境界の前`N`日はDETを固定、AGG側を修正。
  - `anchor=AGG_far`：境界の後`M`期間はAGGを固定、DET側を再配分。
  - `blend`：整合ウィンドウでDET/AGGを重み付けブレンド（例: 三角重み）。
- 保存・連続条件:
  - 在庫連続: `INV_close(t-1) == INV_open(t)`（境界日に厳格チェック）。
  - 需要保存: 集約期間合計需要 = 詳細日合計需要。
  - 供給保存: 生産+調達+受入 = 出荷+在庫変動+廃棄。
  - バックログ連続: `BL_close(t-1) == BL_open(t)`。
- 制約反映:
  - 能力: 工程/リソース負荷を上限内に。DETでの超過はAGGに戻し抑制（mix見直し）。
  - BOM: 上位需要→下位展開量の整合、原材料在庫/リードタイム制約の逆伝播。

## 境界設計
- `cutover_date` 周辺の整合ウィンドウ `[cutover-W, cutover+W]` で以下を実施:
  - 前半（<cutover）: DET優先、AGGとの差分はAGGへ吸収（先々のmix/量を微調整）。
  - 後半（≥cutover）: AGG優先、DETの配分でAGGターゲットに合わせる。
  - 境界日: 在庫・バックログ・WIPの橋渡し（DETの`close`をAGGの`open`へ厳格一致）。
- 例外: 設備停止/販促等のイベントは境界で明示ロック（`lock_flag`）して上位/下位からの変更を禁止。

## 設定パラメタ（例）
- `cutover_date`: `YYYY-MM-DD`
- `recon_window_days`: `int`（既定: 7）
- `agg_time_bucket`: `week|month`、`det_time_bucket`: `day`
- `mix_source`: `history|manual|ml`
- `rounding`: `int|bankers`、`residual_policy`: `demand-priority|cost-min`
- `tol`: 許容誤差（相対/絶対）
- `anchor_policy`: `DET_near|AGG_far|blend`

## API/ジョブ（案）
- `POST /plans/integrated/run`:
  - body: `{ version_id?, base_scenario_id, cutover_date, recon_window_days, params... }`
  - 実行: aggregate→allocate→mrp→reconcile。`version_id` を返却。
- `POST /plans/{version}/reconcile`（再整合のみ）
- `GET /plans/{version}/summary`（KPI・差分・整合ログ）
- `GET /plans/{version}/compare?level=AGG|DET`（ロールアップ比較）

## 入出力スキーマ（抜粋）
- 入力: 需要/在庫/能力/BOM/カレンダー/階層/ミックス。
- 出力: `AGG`/`DET` 計画配列＋整合ログ、KPI（サービスレベル、在庫回転、能力使用率、PL）。

## 検証・KPI
- ハードチェック: 在庫連続/保存、バックログ連続、能力超過なし。
- ソフトチェック: 期間別`Δ`、SKU×拠点×期間の偏差分布、丸め残差の最大/中央値。
- KPI: fill rate、backlog days、inventory turns、capacity util、COGS/variance。

## 実装ステップ（段階導入）
1) v1: 既存パイプラインに `version_id` を通し、DET→AGGロールアップ比較・整合ログ出力を追加。
2) v2: `cutover_date`/`recon_window_days`/`anchor_policy` を導入し、境界整合を実装。
3) v3: API/UI 統合（統合実行・差分可視化・ロック編集）。
4) v4: ヒューリスティク高度化（混雑コスト・優先度・サービスレベル最適化）。

## 失敗時リカバリ
- 仕様: idempotent再実行（同versionで一部上書き）。
- ロールバック: `status=superseded` で旧versionを保持し参照切替。
- ログ: `reconciliation_log` に差分とポリシー適用を記録。

## テスト指針
- 単体: 配分丸め/残差再配分、境界在庫連続、保存則、能力上限処理。
- 結合: サンプルデータで AGG⇄DET 差が tol 内に収まること、境界`open/close`一致。
- 退行: 既存の`aggregate→allocate→mrp→reconcile`が破壊されないこと。

## 付録: 最小例（イメージ）
- `cutover=2025-09-01`, `W=3`。
- 週次AGG需要: family=A, loc=TOKYO, 9/1週=700。
- 日次DET配分: sku=A1/A2、9/1..9/7で営業日ウェイト配分、能力・LTで微調整。
- ロールアップ: DET合計=700、差分=0、境界 8/31 close = 9/1 open を満たす。

---
以上をベースに、段階導入（v1→v4）で統合整合を進めます。既存スクリプト群（aggregate/allocate/mrp/reconcile）に `version_id` と `cutover`/`window` パラメタを順次付与し、整合ログを追加する実装を提案します。
