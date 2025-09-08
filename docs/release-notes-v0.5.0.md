# v0.5.0 リリースノート（2025-09-07）

ハイライト
- Planning Hub（/ui/plans）詳細のアクセシビリティを改善（タブ/フィルタ/コピー操作に aria-label 追加）
- 計画UX計画（PLANNING-HUB-UX-PLAN.md）のWBS整合（P-23 用語統一 / P-24 チュートリアル更新 完了）

変更（抜粋）
- feat(ui/plans): タブ（Overview/Aggregate/Disaggregate/Schedule/Validate/Execute/Results/Diff）に aria-label を付与
- feat(ui/plans): Disaggregate/Schedule の SKU/週フィルタ、schedule.csv コピー操作に aria-label を追加
- docs: CHANGELOG を v0.5.0 に更新、PLANNING-HUB-UX-PLAN を整合

移行/互換性
- 表示ラベルは従来通り（英語）で互換維持。支援技術向け属性のみの追加
- API・データ構造の破壊的変更なし

関連PR
- #193 feat(ui/plans): アクセシビリティ改善（aria-label追加）
- #196 docs: CHANGELOGにアクセシビリティ改善と計画書整合を追記
- #197 docs(release): v0.5.0 を確定（CHANGELOG反映）

検証
- /ui/plans/{id} にて、各タブと Disaggregate/Schedule のフィルタ入力が読み上げ/アクセシビリティ検査で認識されること
- Render 連携ワークフローが有効な場合、リリース公開を契機に自動デプロイ
