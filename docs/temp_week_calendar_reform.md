# 週カレンダー仕様改修 メモ（アーカイブ予定）

- 作成日: 2025-02-14（初稿）
- 状態: 完了（正式ドキュメントへ移管済み、削除候補）
- 用途: カレンダー改修の結果を記録していた一時メモ。公式ドキュメントに反映済みのため、本ファイルは参照不要になりました。

## 公式ドキュメント反映先
- `README.md`: Canonical設定に `planning_calendar.json` を含めた場合の挙動と `PlanningCalendarSpec` の概要を追記。
- `docs/AGG_DET_RECONCILIATION_JA.md`: カレンダー仕様、利用モジュール、フォールバック方針を整理。
- `docs/TUTORIAL-JA.md`: UI/Run/APIフローでのカレンダー自動適用とフォールバック手順を更新。
- `docs/API-OVERVIEW-JA.md`: `POST /runs` オプションの説明を更新し、カレンダー自動適用と `weeks` フォールバックの位置づけを明確化。

## 実装サマリ
- `scripts/calendar_utils.py` を新設し、Planningカレンダーの読み込み・週配分・週順序整列・日付→週マッピングを共通化。
- `scripts/allocate.py` / `scripts/mrp.py` / `scripts/reconcile.py` / `scripts/reconcile_levels.py` / `scripts/anchor_adjust.py` で `--calendar` を優先し、`planning_calendar.json` がない場合のみ `--weeks` で等分フォールバック。
- `scripts/run_planning_pipeline.py` と UI/API 経由の実行（`app/plans_api.py`, `app/jobs.py`）で `_calendar_cli_args` を利用し、Canonical設定内の `planning_calendar.json` を自動検出。
- サンプル `samples/planning/planning_calendar.json` と `tests/test_calendar_utils.py` で5週月・ISO週ズレのケースをカバー。

## タスク一覧（完了）

| No | 状態 | 内容 |
|----|------|------|
| T1 | 完了 | UI/API入力パラメータの棚卸しと移管対象整理 |
| T2 | 完了 | Canonicalモデル拡張とバリデーション設計 |
| T3 | 完了 | Configローダ/ストレージ更新と `prepare_canonical_inputs` 調整 |
| T4 | 完了 | `allocate.py` のカレンダーベース配分移行と `--weeks` 非推奨化 |
| T5 | 完了 | `mrp.py` の週キー解釈をカレンダー参照に統一 |
| T6 | 完了 | `anchor_adjust.py` の cutover 推定をカレンダー利用へ切替 |
| T7 | 完了 | `run_planning_pipeline.py` の週関連引数整理とConfig参照化 |
| T8 | 完了 | UI表示を設定値参照表示化（入力欄撤去準備含む） |
| T9 | 完了 | フォールバック／移行戦略と警告ログ設計 |
| T10 | 完了 | 週境界ケース等のテスト拡充 |
| T11 | 完了 | READMEおよび正式ドキュメント更新 |
| T12 | 完了 | 設定移行手順・スクリプト検討 |
| T13 | 完了 | リリース計画と関係者告知 |
| T14 | 完了 | `samples/canonical` の新仕様整備 |
| T15 | 完了 | CI/GitHub Actions の更新と互換性CI調整 |

## 既知フォローアップ
- UI入力欄はフォールバック用に `weeks` を残していますが、カレンダー整備後は自動反映されます。
- 追加のカレンダーを持つ設定（ライン別など）を扱う際は、Plan用カレンダーを `planning_calendar.json` に分離して渡す運用を推奨。

## 削除判断
- 上記ドキュメントに仕様と運用が移管されたため、本ファイルは削除可能です。
- もし将来的に週カレンダー拡張のブレインストーミングが必要な場合は、`docs/archive/` 配下に移して履歴のみ残してください。
