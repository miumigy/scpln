# Plan DB 設計ドキュメント運用ガイド

## 位置付け

- `docs/plan_db_assumed_requirements.md`
  - 想定仕様・前提条件をまとめたドキュメント。
  - ヒアリングなしで決めた粒度・KPI・保管期間・非機能要件、スプリント/ブランチ戦略などを記載。
  - 仕様が変わったらここを更新して「想定」と実態を同期させる。

- `docs/plan_db_design_todo.md`
  - 設計・実装タスクの進捗管理表。
  - 各タスクのステータス（未着手/実装メモ有/完了）とメモ、優先順を管理。
  - 実装の着手・完了に合わせてステータスやメモを更新する。

- `docs/plan_db_persistence_plan.md`
  - 詳細設計書。
  - スキーマ、マイグレーション、PlanRepository、UI/API対応、テスト・監視方針を章立てで記録。
  - 実装内容が設計とズレた場合はここを修正して整合性を保つ。

## 実装時の更新目安

1. 仕様変更・追加 → `plan_db_assumed_requirements.md`
2. タスク進捗の更新 → `plan_db_design_todo.md`
3. 設計詳細の変更・補足 → `plan_db_persistence_plan.md`

この3ファイルを役割ごとに保守することで、実装とドキュメントの整合を維持する。

