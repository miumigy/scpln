目的
- Planning Hub 詳細画面のアクセシビリティ改善（aria-label 追加）
- 計画書（PLANNING-HUB-UX-PLAN.md）のWBS整合と進捗追記（P-23/P-24 完了）

主な変更
- templates/plans_detail.html
  - タブ（Overview/Aggregate/Disaggregate/Schedule/Validate/Execute/Results/Diff）に aria-label を付与
  - Disaggregate/Schedule の SKU/週フィルタ入力に aria-label を付与
  - schedule.csv コピー操作ボタンに aria-label を付与
- docs/PLANNING-HUB-UX-PLAN.md
  - P-23 用語統一: 完了（✔）に更新、追記（主要入力・コピー系への aria-label）
  - P-24 チュートリアル更新: 完了（✔）に更新（docs/TUTORIAL-JA.md は Hub フロー/エクスポート例を既に反映）

影響範囲
- UIの表示文言は従来通り（英語ラベル）。支援技術向け属性のみ追加で後方互換性を維持。
- ドキュメントは進捗の整合のみ（仕様変更なし）。

確認観点
- /ui/plans/{id} でタブ切替とフィルタ入力の aria-label が読み上げ/検査で確認できること
- docs/PLANNING-HUB-UX-PLAN.md の「整理期」「WBS」ステータスが実装状況と一致

マージ方針
- Auto-merge: squash（マージ後ブランチ削除）

