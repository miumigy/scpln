# Plan DB 監査イベント フォローアップ

- 目的: plan_overrides/events の監査粒度とUI表示方針を整理し、actor/notesの扱いを決定する。
- TODO:
  - actor: API呼び出しヘッダ (`X-User`/`X-Actor`) を優先し、未指定時は `system` へ正規化する。
  - notes: UIから編集理由を受け取り、`plan_override_events.notes` に保存する。APIインタフェース変更検討。
  - UI反映: `/ui/plans` の履歴ダイアログにイベント一覧を表示し、ロック/編集/解除を時系列で確認できるようにする。
  - インデックス: `plan_override_events` の `event_ts` 降順取得用インデックスを再確認。
  - `psi_state` 表示: submit/approveイベントから最新状態を計算し、UIに表示するロジックを整備する。
- 関連タスク: docs/plan_db_design_todo.md (T2/T3系)、docs/plan_db_persistence_plan.md P2/P3 セクション。
