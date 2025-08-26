# 粗密計画パイプライン 進捗と運用ノート（記録用）

本ドキュメントは、粗粒度→按分→MRP→製販物整合→レポートの段階導入の進め方と進捗を簡潔に記録します。途中で作業が中断しても、ここから再開できます。

## 現状サマリ（2025-08-26）
- 目的: 製品ファミリ×月次の粗粒度計画からSKU/週次へ按分し、材料・能力を考慮して整合させるパイプラインを段階導入。
- 実装状況（PRステップ）
  - PR1: スキーマ/サンプル/CLIスタブ 追加（完了）
    - 追加: `planning/schemas.py`（雛形）、`samples/planning/*`、`scripts/*.py`（スタブ）
    - READMEに利用手順を追記
  - PR2: 粗粒度S&OP（ヒューリスティク） 実装（完了）
  - PR3: 按分（family→SKU、月→週）＋丸め（完了）
  - PR4: MRPライト（LT/ロット/MOQ/BOM）実装（完了）
  - PR5: 能力整合（CRPライト）実装（未着手）
  - PR6: 整合ループ＋KPI/シナリオ（未着手）
  - PR7: CLI配線強化/ドキュメント（未着手）

## 実行手順（再現性）
- 粗粒度計画（雛形出力）:
  - `PYTHONPATH=. python3 scripts/plan_aggregate.py -i samples/planning -o out/aggregate.json`
  - 出力: `rows: [{family, period, demand, supply, backlog, capacity_total}]`
- 按分スタブ:
  - `PYTHONPATH=. python3 scripts/allocate.py -i out/aggregate.json -I samples/planning -o out/sku_week.json --weeks 4 --round int`
  - 出力: `rows: [{family, period, sku, week, demand, supply, backlog}]`
  - オプション: `--weeks`（週数, 既定4）、`--round none|int|dec1|dec2`（丸め）。丸め後の総量差は最終週に吸収。
- MRPスタブ:
  - `PYTHONPATH=. python3 scripts/mrp.py -i out/sku_week.json -I samples/planning -o out/mrp.json --lt-unit day --weeks 4`
  - 入力CSV: `item.csv`, `inventory.csv`, `open_po.csv`, 任意で `bom.csv`
  - 出力: `[{item, week, gross_req, scheduled_receipts, on_hand_start, net_req, planned_order_receipt, planned_order_release, lt_weeks, lot, moq}]`
- 製販物整合スタブ:
  - `PYTHONPATH=. python3 scripts/reconcile.py -i out/sku_week.json out/mrp.json -o out/plan_final.json`
- レポート出力（雛形CSV）:
  - `PYTHONPATH=. python3 scripts/report.py -i out/plan_final.json -o out/report.csv`

出力は `out/` に生成されます。スタブ段階のため、`rows` は空配列です（今後のPRで計算結果が入ります）。

## 設計メモ（要点）
- 依存方針: PR1では外部依存導入を避け、スタブを素のPythonで動作させる。
- スキーマ厳格化: 将来PRで `planning/schemas.py` をCLIに接続し、pydanticで入出力を厳格化。
- データI/F: CSV（サンプル）→JSON（中間成果物）を採用。将来はDB/APIも視野。

## 次アクション（PR5以降の仕様メモ）
- PR5 能力整合: 工程能力に基づく自動調整（前倒し/繰越/外注）。
- PR6 整合ループ+KPI: 反復収束とKPI算出/シナリオ比較。

## 合意事項・未決事項
- 合意: パイプライン段階導入、PR1はI/F整備に留める。
- 未決: コスト重み（欠品/遅延/外注/在庫）とサービスレベル目標、ソルバ利用範囲。

## 変更履歴（抜粋）
- 2025-08-26: PR1 完了、ドキュメント作成。
