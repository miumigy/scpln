# 週カレンダー仕様改修 タスクメモ（テンポラリ）

- 作成日: 2025-02-14
- 作成者: Codex CLI エージェント
- 用途: 仕様変更対応の進捗管理用テンポラリドキュメント。セッション断絶や担当交代時の引き継ぎを想定。
- ステータス: 草稿（非公開想定、対応完了後は正式ドキュメントへ反映・本ファイル削除予定）

## 背景と課題

- 現行パイプラインは `scripts/allocate.py` で period を `--weeks` 等分し `YYYY-MM-WkX` を生成。実際のカレンダー週長（ISO週・工場休業日など）を反映できない。
- `scripts/mrp.py` でも到着日→週キー変換を月内1〜4週へ単純丸めしており、週境界が実態と乖離。
- UI や API で `weeks` / `calendar_mode` / `week_start_offset` など多数のパラメータを直接入力させているが、実務上は Canonical Config 起点で固定・共有すべき設定が多い。

## 対応方針（概要）

- Canonical Config の `calendars` / メタ属性へ「週境界・期間パラメータ」を集約。Planning Hub UI からの入力を廃止し参照専用とする。
- パイプライン各ステージ（aggregate→allocate→mrp→reconcile）で同一カレンダー情報を利用し、週分割・cutover 推定・MRPの週キー解釈を統一。
- カレンダー未定義の場合のみ現行ロジックへフォールバックし、警告ログで移行を促す。

## タスク一覧

| No | 状態 | オーナー | 内容 | 備考 |
|----|------|----------|------|------|
| T1 | 未着手 | TBD | UI/API 入力パラメータ棚卸し (`plans.html` `app/ui_plans.py` `app/plans_api.py`) と移管対象の整理 | 取扱禁止項目の明示リスト化 |
| T2 | 未着手 | TBD | Canonical モデル拡張 (`CalendarDefinition` 周辺) とバリデーション設計 | 週境界 (`week_code` `start_date` `end_date` `weight`) 仕様確定 |
| T3 | 未着手 | TBD | Config ローダ/ストレージ更新（CSV/JSON→DB→Planning Inputs） | `prepare_canonical_inputs` 更新含む |
| T4 | 進行中 | TBD | `allocate.py` の週配分ロジックをカレンダーベースへ改修、`--weeks` 非推奨化 | 週キー生成をカレンダー準拠に変更 |
| T5 | 進行中 | TBD | `mrp.py` の週キー解釈をカレンダー参照に統一 | `open_po` 変換とLT計算の整合性確認 |
| T6 | 未着手 | TBD | `anchor_adjust.py` の cutover 週推定をカレンダー利用へ切替、旧オプション整理 | `--calendar-mode` 廃止方針と互換ログ |
| T7 | 未着手 | TBD | `run_planning_pipeline.py` から週関連引数削除・Config参照へ移行 | CLI ユースケースの互換検証 |
| T8 | 未着手 | TBD | UI 表示更新（設定値の参照表示化、入力欄撤去） | ユーザ通知内容を準備 |
| T9 | 未着手 | TBD | フォールバック／移行戦略策定（既存Plan/Run影響調査、警告ログ設計） | 移行期間中のFeature Flag検討 |
| T10 | 未着手 | TBD | テスト拡充（週境界ケース、5週月、月跨ぎ、ISO週） | `tests/` および受入スモーク更新 |
| T11 | 未着手 | TBD | ドキュメント更新（README, docs/）とcanonicalサンプル整備 | カレンダー定義例と導入手順 |
| T12 | 未着手 | TBD | 設定移行手順・スクリプト検討（既存環境へのカレンダー投入） | CLI/SQLサンプル作成 |
| T13 | 未着手 | TBD | リリース計画と関係者告知 | 段階的公開やFeature Flag要否判断 |
| T14 | 未着手 | TBD | `ui/configs` でロードするサンプルJSON（例: `samples/canonical/*.json`）を新仕様へ整備 | UIロード確認と整合性検証を含む |
| T15 | 未着手 | TBD | CI/GitHub Actions の更新（新テスト追加・互換性CI調整） | 長時間テスト有無や移行期間中の一時的なFail対策を整理 |

## 進捗ログ（2025-11-01）

- `scripts/calendar_utils.py` を新設し、PlanningカレンダーのLookUp・週配分・日付マッピングを共通化。
- `scripts/allocate.py` をカレンダーベース配分へ移行。`planning_calendar.json` を自動探索し、サマリーへ `calendar_mode` を出力する形に変更。`--weeks` はフォールバック用途のみ保持。
- `scripts/mrp.py` を同等方針に更新。週リストをカレンダー順へ並べ替え、`open_po` の到着日を週境界で解釈するロジックへ刷新。
- サンプル `samples/planning/planning_calendar.json` を追加し、`tests/test_calendar_utils.py` を新設。`tests/test_canonical_builders.py` も含めてローカルpytestを通過（2025-11-01）。
- UI/API 連携部分（`app/plans_api.py` `app/ui_plans.py` など）は未対応。今後 `--weeks`/`calendar_mode` を撤廃し、`--calendar` のみに統一する必要あり。
- `app/plans_api.py`・`app/ui_plans.py`・`scripts/run_planning_pipeline.py` に `_calendar_cli_args` を導入。Canonical Input から `planning_calendar.json` を発見した場合は `--calendar` を渡し、欠落時のみ `--weeks` フォールバックを自動付与するよう統一。UIのフォーム値としての `weeks` は受理するがAPIへは送らない暫定仕様。

### 進捗ログ（2025-11-01 追加）

- `scripts/reconcile.py` と `scripts/reconcile_levels.py` を `calendar_utils` ベースへ移行し、`--weeks` 引数を削除。
- `templates/plans.html` から `weeks` と `calendar_mode` の入力フォームを削除。
- `app/ui_plans.py` の `ui_plans_create_and_execute`, `ui_plan_reconcile`, `ui_plan_execute_auto` から `weeks` と `calendar_mode` のパラメータ授受を削除。
- `pytest` で `ImportError` が発生したため、`core/config/models.py` に `PlanningCalendarSpec` 関連モデルを追加し、`git reset` で失われていた `scripts/calendar_utils.py` を復元してテストをパスさせた。

### 次のアクション

1. `app/plans_api.py` のエンドポイントから `weeks` と `calendar_mode` のパラメータを削除し、`_calendar_cli_args` ヘルパー関数への依存に切り替える。
2. `scripts/run_planning_pipeline.py` から `--weeks` 引数を削除し、`_calendar_cli_args` のフォールバックのみに依存させる。
3. T1, T8, T10, T11のタスクを進め、関連ドキュメントを更新する。

## 依存関係・検討事項

- カレンダー定義フォーマットは `CalendarDefinition.definition` に JSON で保持予定。外部システム連携の要否を決定する必要あり。
- 週境界定義を Canonical に含める場合、既存の `period_cost` や `period_score` と同期させるルール（例: 期間キー形式）を策定する。
- `mrp.py` や後続レポートで週キーをソートする際の順序定義（例: カレンダー側で順序付与、または日付基準でソート）を明確化する。

## T1 棚卸しメモ（2025-02-14）

### 対象UI / エンドポイント

- Plan作成フォーム: `templates/plans.html:45-114`
- Plan詳細操作（reconcile/auto execute）: `app/ui_plans.py:909-1188`
- API統合実行: `app/plans_api.py:560-878`
- Reconcile API: `app/plans_api.py:2249-2370`

### UI入力パラメータ整理

| パラメータ | UI入力元 | API/スクリプトでの消費箇所 | 現状の課題 | Config移行方針メモ |
|------------|----------|-----------------------------|-------------|--------------------|
| `weeks` | `templates/plans.html:45-48` | `app/ui_plans.py:930-942` → `app/plans_api.py:603-722` で `allocate.py`/`mrp.py`/`reconcile.py` へ渡す | カレンダー実体に無関係な等分週を強制。`post_plan_reconcile` では無視される点も非対称。 | Canonical `calendars` から週境界を算出し自動設定。UI入力は廃止し、フォールバック時のみ警告付きで既定値を用いる。 |
| `calendar_mode` | `templates/plans.html:83-90` | `app/ui_plans.py:930-937` → `app/plans_api.py:646-720`/`2259-2307` で `anchor_adjust.py` へ渡す | simple/iso しか選べず実カレンダーの粒度を反映できない。週分割とも整合しない。 | Canonical カレンダー種別で自動決定（例: ISO週 or custom 定義）。UI選択肢は削除。 |
| `tol_abs` / `tol_rel` | `templates/plans.html:75-82` | `app/ui_plans.py:933-935` → `app/plans_api.py:637-640`,`709-716`,`2270-2276`,`2311-2317` | ユーザー入力の度に閾値がブレ、整合性検証が不安定。 | Canonical メタ属性（例: `planning_constraints.tolerance_abs/rel`）として管理し、UIは値表示のみ。 |
| `carryover` / `carryover_split` | `templates/plans.html:93-106` | `app/ui_plans.py:936-938` → `app/plans_api.py:642-649`,`2265-2270` | 週割と連動しない carryover 設定を都度入力させている。値の妥当性・既定が不明瞭。 | Config 側に carryover ポリシーを定義し、Plan単位では初期値を参照する。UIでの任意入力は廃止。 |
| `anchor_policy` | `templates/plans.html:65-73` | `app/ui_plans.py:932-933` → `app/plans_api.py:632-633`,`682-688`,`2260-2266` | Configに依存すべき整合ポリシーをUIで切り替え可能になっており、計画間の一貫性が崩れる。 | Canonical メタにデフォルトポリシー設定。Plan個別変更が必要な場合のみ限定的に許可する（要運用方針検討）。 |
| `recon_window_days` | `templates/plans.html:61-63` | `app/ui_plans.py:931-932` → `app/plans_api.py:626-628`,`674-680`,`2254-2259` | 週境界との整合が取れておらず、調整対象週の範囲が直感的でない。 | カレンダー定義と整合する日数/週数をConfigで指定し、自動で週単位に変換。 |
| `lt_unit` | `templates/plans.html:49-55` | `app/ui_plans.py:940-941`,`1039-1040` → `app/plans_api.py:618-620`,`679-684` | LT単位をPlan実行ごとに変更可能だが、MRPデータやConfigに依存するため自由入力はリスク。 | Canonical 設定に LT 基準（day/week）を保持し、UIは表示参照のみを想定。 |
| `apply_adjusted` | `templates/plans.html:107-113` | `app/ui_plans.py:938-939`,`974-978` → `app/plans_api.py:604-612`,`2295-2307` | 調整版の適用有無をUIが直接制御。carryover/anchorとセットで扱わないと整合が崩れる。 | Configに既定ポリシーを置き、UIは実行オプションとして残すか要検討。 |
| （参考）`weeks` in Reconcile | `app/ui_plans.py:909-942` | `post_plan_reconcile` 側では未使用 | UI側で入力できるがAPIで使われず混乱要因。 | Config移行時にUI項目ごと削除。 |

### 追加で確認が必要な項目

- `blend_split_next` / `blend_weight_mode` / `max_adjust_ratio` は現状APIオプションのみ（UI未露出）。Config化の範囲に含めるかステークホルダー確認が必要。
- `week_days`（`scripts/mrp.py:179`）は `run_planning_pipeline.py` CLI専用だが、Canonical カレンダーが日数ベースのため設定項目としては不要になる想定。CLI互換をどう扱うかはT7/T15で検討。
- Jobs UI (`templates/jobs.html:185-199`) で `week_start_offset`/`month_len` を扱うが、本改修範囲（Planning Hub UI）とは別タスクか要整理。

## リスク・オープン課題

- 既存Plan/Runデータが旧形式 (`YYYY-MM-WkX`) を前提にしているため、移行時に再計算が必要となる可能性。
- カレンダー定義が欠落した場合のフォールバック仕様と、警告の扱い（ログのみかUI表示か）を決める必要がある。
- UI 入力撤去に伴うユーザーガイド更新・周知が遅れると運用混乱を招く恐れ。

## 次に行うべき作業（引き継ぎ用メモ）

1. T1の棚卸しドキュメント草案を作成し、UI/APIで廃止するフィールド一覧と移行先（Canonical属性）を定義する。
2. カレンダー定義のJSONスキーマ案を作り、`CalendarDefinition.definition` に載せる具体例（ISO週、工場独自カレンダー）を準備する。
3. ステークホルダー（Planning Hub利用チーム）へ仕様変更方針を事前共有し、レビュー期限を設定する。

## T2 カレンダー拡張案メモ（2025-02-14）

### 目的
- Canonical配置の `CalendarDefinition` から週境界情報と計画パラメータをパイプラインへ供給し、UI入力を撤廃できるようにする。

### 追加予定フィールド（案）

`CalendarDefinition.definition` は下記のような構造を想定（JSON Schema化予定）。

```jsonc
{
  "calendar_type": "custom",      // iso_week / custom / gregorian 等
  "week_unit": "day",             // weightの単位（day or hourなど拡張余地）
  "periods": [
    {
      "period": "2025-01",        // 月などの集計単位
      "start_date": "2024-12-30", // ISO週を含む場合は月外を許容
      "end_date": "2025-02-02",
      "weeks": [
        {
          "week_code": "2025-W01",
          "sequence": 1,
          "start_date": "2024-12-30",
          "end_date": "2025-01-05",
          "weight": 7,             // 計画週長（day単位）。後続で正規化に利用。
          "attributes": {
            "is_cutover": false    // 任意メタ情報
          }
        },
        {
          "week_code": "2025-W02",
          "sequence": 2,
          "start_date": "2025-01-06",
          "end_date": "2025-01-12",
          "weight": 7
        }
      ]
    }
  ],
  "planning_params": {
    "default_anchor_policy": "DET_near",
    "tolerance_abs": 1e-6,
    "tolerance_rel": 1e-6,
    "carryover_mode": "auto",
    "carryover_split": 0.8,
    "lt_unit": "day",
    "recon_window_days": 14
  }
}
```

### 利用イメージ
- `prepare_canonical_inputs` で `planning_bundle` に以下を含める。
  - 期間ごとの週一覧（`weeks`）と `weight` 合計。
  - `planning_params` を `options` に展開しPlan生成時の既定値にする。
- `allocate.py` は `periods[*].weeks` を読み取り、`weight` 比率で週配分＆`week_code` を採用。フォールバック時は従来の等分ロジック。
- `mrp.py` は `week_code` のソートと `open_po` マッピングをこの一覧で参照。
- `anchor_adjust.py` は `sequence` および `weight` からcutover週推定を行い、`calendar_mode` 引数廃止。

### 追加検討
- `planning_params` を `CalendarDefinition.attributes` に置く案もあるが、構造化しやすいよう `definition` 直下で別キー化する。
- 複数カレンダーを持つ場合（例: 製造ライン別）でも、Plan用カレンダーを `calendar_code="PLANNING_PERIODS"` で特定できるようルール化が必要。
- 週コードと期間の対応が1:多になり得る（月跨ぎISO週）。`allocate.py` 側で週配分時に `period` の合計値が一致するか検証する。
- `weight` の合計が0や欠落の場合はフォールバック（等分 or 等分+警告）。

### モデル/ローダ変更案

| 対象 | 変更概要 | メモ |
|------|----------|------|
| `core/config/models.CalendarDefinition` | `definition` に型安全なアクセサを追加するか、`PlanningCalendarPayload` 新設。`attributes` は現行互換維持。 | Pydanticモデルで `periods`/`weeks`/`planning_params` を表現し、`definition` へ格納/復元。 |
| `core/config/loader._build_calendars` | Planning Payloadから `planning_calendar.json`（新規ファイル想定）を読み込み、`CalendarDefinition` を構築。既存の `period_cost`/`period_score` 生成は維持しつつ `definition` に統合。 | 初期実装として `samples/canonical` に新形式ファイルを追加。 |
| `prepare_canonical_inputs` | `PlanningDataBundle` に `calendar` 情報と `planning_params` を含めるフィールドを追加。 | 既存利用箇所へ影響するため、`PlanningDataBundle` 定義変更（`core/config/builders.py` 等）も要確認。 |
| `core/config/storage` | `definition_json` へ新構造をそのまま保存。既存データとの互換を保つため、旧形式 (`period_cost`/`period_score` のみ) も受け入れる。 | 読み出し時に欠損フィールドは空/Noneで補完。 |

### 影響範囲メモ
- `scripts/` 系: `allocate`, `mrp`, `anchor_adjust`, `reconcile`, `run_planning_pipeline`。
- `app/` 系: `plans_api`, `ui_plans`, `jobs`, `ui_configs`（カレンダー表示/編集）。
- `tests/`: 週カレンダーの新ケース追加、既存テストの更新。

## 参照ファイル／コード（現状確認用）

- `scripts/allocate.py` `scripts/mrp.py` `scripts/anchor_adjust.py`
- `scripts/run_planning_pipeline.py`
- `app/ui_plans.py` `app/plans_api.py`
- `core/config/models.py` `core/config/loader.py` `core/config/storage.py`

---
※本ファイルは一時的な進捗共有を目的としたメモです。正式決定事項・実装完了内容は別途既存ドキュメントへ反映した上で、本ファイルを削除またはアーカイブ化してください。
