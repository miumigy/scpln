## 目的
- 欠品モード（lost_sales）とレビュー間隔（review_period_days）を追加し、需要計画の表現力を向上（R=0で後方互換）。

## 変更点
- feat(domain): BaseNodeに `lost_sales: bool`（既定false）, `review_period_days: int`（既定0）を追加
- feat(engine): 補充/生産 order-up-to を `μ*(L+R+1) + z*σ*sqrt(L+R)` に拡張（R=0で現行同等）
- feat(engine): `lost_sales=true` の場合、顧客バックオーダーを保持せず、在庫ポジションからも控除しない
- test: `tests/test_p1_features.py` を追加（lost_sales, review R の動作確認）
- docs: README のスキーマ（BaseNode）に項目を追記

## 互換性/影響
- 既存入力は変更不要（`lost_sales` 未指定=従来のバックオーダー挙動, `review_period_days=0`）
- 既存テストはすべて緑＋新規テストも緑

## 確認観点
- `lost_sales=true` で顧客BOが蓄積されないこと
- R=2などで order-up-to が `L+R+1` に基づき拡張されること
