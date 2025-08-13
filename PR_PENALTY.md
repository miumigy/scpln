## 目的
- 欠品/バックオーダーのペナルティコストを計上可能にし、設定JSON（デフォルト）を「全設定明示」に更新。

## 変更点
- feat(domain): BaseNode に以下を追加
  - `stockout_cost_per_unit`（欠品1単位あたりコスト, 既定0）
  - `backorder_cost_per_unit_per_day`（未出荷1単位×日あたりコスト, 既定0）
- feat(engine): `penalty_costs`（`stockout`/`backorder`）を日次損益に追加し、`total_cost` に反映
  - 欠品コスト: 当日の `shortage` × ノード単価
  - BO保有コスト: 期末時点の未出荷（サプライヤBO/店舗顧客BO）× ノード単価
- docs/data: `static/default_input.json` を全設定明示（lost_sales / review_period_days / penalty costs）
- test: 追加テスト `tests/test_penalty_costs.py`（計上額と total_cost 反映の検証）

## 互換性
- 既存入力は変更不要（未指定=0計上）。
- 既存テストはグリーン、新規テストも成功。

## 確認観点
- 欠品/BOの定義と計上タイミング（当日/期末残）
- `penalty_costs` を `summary` へ含めるかは別PRで議論可能（現状は `total_cost` にのみ寄与）。
