# RunRegistry運用ガイドライン

- 最終更新: 2025-10-05
- 適用範囲: Plan中心RunRegistry運用・Run履歴トレーサビリティ

本ドキュメントは Plan 中心の RunRegistry 運用を円滑に行うための実務ルールとチェックポイントをまとめたものです。Plan生成から Run 履歴確認までの一貫したフロー、およびレガシー経路の段階的廃止に伴う留意事項を定義します。

## 0. 現行運用サマリ
- 2025-09-30 に Plan 経由 Run への切替を完了し、レガシー Run 投入経路は停止済み。
- RunRegistry DB は `config_version_id` と `plan_version_id` を必須キーとして保持し、Canonical 設定スナップショットとRun成果物を相互トレースできる。
- 運用チェックリスト・バックアップ手順は `docs/config_integration_plan.md` と `docs/ops_backup.md` に統合管理し、本ドキュメントはRun履歴運用の一次リファレンスとして恒久保守する。
- KPI監視・CIテストは Plan 中心パスに合わせて更新済み。Run 再構築スクリプト(`scripts/rebuild_run_registry.py`) をフォールバック手順に組み込み済み。

## 1. 目的
- Plan & Run で生成される `run_id` と `plan_version_id` の整合性を保ち、監査・比較・再実行のトレーサビリティを保証する。
- Run履歴(UI/API)から Plan やシナリオへ即時遷移できる観測性を提供する。
- レガシー（シナリオUI→Run）経路を段階的に停止し、Plan UI 経由の統合パイプラインへ一本化する。

## 2. 環境変数と設定
| 変数 | 推奨値 | 用途 |
| --- | --- | --- |
| `REGISTRY_BACKEND` | `db` | RunRegistry を SQLite に永続化。Plan中心運用では DB バックエンドが前提。 |
| `RUNS_DB_MAX_ROWS` | `200` など | Runテーブルの保持上限。設定すると最古ランを自動削除。 |
| `SCPLN_SKIP_SIMULATION_API` | `1` (テスト時) | CIやローカルテストで重いPSIシミュレーションをスキップ。運用環境では未設定。 |
| `SCPLN_DB` | `<path>` | テスト/ステージングごとにRunRegistry DBを切り替える際に指定。 |

## 3. 運用フロー
1. `/ui/plans` で Plan を作成し、Base Scenario と Canonical Config を選択して実行する。作成後は Summary に `config_version_id` と `base_scenario_id` が表示され、Run履歴と双方向リンクが張られる。
2. Run履歴(`/ui/runs`)では `plan_version_id` 列と `scenario_id` 列から該当Plan/シナリオに遷移できる。Run詳細(`/ui/runs/{run_id}`)でも Summary にリンクを表示し、レスポンスJSONにも `plan_version_id` が含まれる。
3. Aggregate Jobフォームでは Plan version を指定できる。Plan起点で Run を再処理する際はここで `plan_version_id` を入力し、成果物をPlanにひも付けて管理する。
4. `/ui/jobs` では Plan作成ジョブが `plan_version_id` を示すため、完了後に該当Plan詳細へ遷移して結果を確認する。

## 4. レガシー経路停止ステータス
- `/ui/scenarios/{sid}/run` は 403 を返し、Plan & Run UI へ誘導するバナーを表示。環境フラグによる一時復旧経路は廃止済み。
- シナリオUIからPlan UIへのクイックリンクを設置し、Base Scenario を渡したPlan作成が標準フローとなる。
- 今後は関連コード・テストからレガシーRun依存を削除し、Plan中心フローに一本化する。

### 移行計画（Plan中心化ロードマップ / 履歴）
| フェーズ | 目的 | 主体 | 主なアクション | 完了判定 | 実績 |
| --- | --- | --- | --- | --- | --- |
| P0 事前整備 | 並行運用に備えた共通設定へ統一 | SRE / アプリ開発 | `REGISTRY_BACKEND=db` を全環境で固定、Plan UI にBase Scenarioリンクを周知、`SCPLN_SKIP_SIMULATION_API` の本番未設定を監査 | 全環境でPlan UI → Run登録が成功し、通知テンプレートを更新済み | 2025-09-24 完了 |
| P1 並行稼働 | Plan経由Runを本番トラフィックで検証 | 運用チーム | 本番とステージングでPlan→Runを優先案内、レガシーRunは計画停止日を明示、`RUNS_TOTAL` を日次確認 | 主要シナリオがPlan経由で完了し、レガシーフロー割合が20%未満 | 2025-09-27 完了 |
| P2 切り替え | レガシーUIを停止しPlan経路へ一本化 | プロダクト / 運用 | `/ui/scenarios/{sid}/run` を read-only にし、Plan作成ガイドをバナーで表示、Plan再実行ジョブをRunbook化 | レガシーRun発行数が連続7日ゼロ、Plan版Runbook承認済み | 2025-09-30 完了 |
| P3 廃止・清掃 | レガシー資産の削除と権限整理 | 開発チーム | レガシーRun API／テスト／ジョブを削除、権限ロールから旧操作を除外、バックアップ保持期間を再設定 | mainブランチでレガシーコードが消滅し、監視ダッシュボードがPlan指標のみ | 2025-10-03 完了 |

#### 環境別ターゲット
| 環境 | ターゲット日 | 事前条件 | 検証方法 | 実績 |
| --- | --- | --- | --- | --- |
| dev | 2025-09-30 | Canonicalシナリオ種別のテストデータが最新 | `make smoke-plan-run` でPlan→Run→履歴表示まで確認 | 2025-09-28 完了 |
| staging | 2025-10-07 | RunRegistry DBマイグレーション手順書レビュー済み、リードタイム警告アラート設定 | QAがPlan UIで3シナリオの再実行を完了、`RUNS_TOTAL`/`jobs_duration_seconds` が許容範囲 | 2025-10-01 完了 |
| production | 2025-10-21 | 運用Runbook承認、サポート告知送付、監視ダッシュボード更新 | 本番Plan→Runジョブが1営業日で50件以上成功、レガシーRunリクエストがSupportキューで0件 | 2025-10-04 完了 |

#### 移行チェックリスト（2025-10-04 完了）
- [x] RunRegistry DBのバックアップおよびリストア手順を docs/ops_backup.md に追記
- [x] 運用チームへのPlan UI操作トレーニング完了（録画／スライド共有）
- [x] レガシーRun API利用サービスへ停止予定日を通知し、代替APIサンプルを提供
- [x] `tests/test_ui_runs_list.py` をPlan経路用データフィクスチャへ移行
- [x] 監視アラートの閾値をPlan中心化に合わせて更新し、PagerDuty Escalationを確認

#### フォールバック / ロールバック
- 切り替え後7日間はレガシーRun APIを `--maintenance` モードで保持し、致命的障害時のみ手動でフラグを戻す。
- `SCPLN_DB` を切り替える前に `cp data/scpln.db data/scpln.db.bak-YYYYMMDD` を実施し、容量肥大時は `sqlite3 .dump` でのバックアップも準備。
- 重大障害時の手順: (1) RunRegistryサービスを停止 → (2) バックアップDBへ差し替え → (3) Plan UIで告知バナーを表示し、復旧完了まで新規Plan登録を制限。
- フォールバックを行った場合はRun履歴の欠損が出るため、`scripts/rebuild_run_registry.py` でPlan成果物から再構築するワークフローを24時間以内に実行。

## 5. 監視とメトリクス
- `RUNS_TOTAL` (Prometheus) : Plan経由Runの件数が期待と合致しているか監視。
- `jobs_duration_seconds{type="planning"}` : Plan生成ジョブの処理時間を追跡し、異常な遅延を検知。
- RunRegistry バックアップ: `data/scpln.db` を日次コピー（任意）。上限を設定している場合は容量推移も併せて監視する。

## 6. テスト方針
- 重要テスト: `tests/test_jobs_canonical_inputs.py`, `tests/test_runs_persistence.py`, `tests/test_ui_runs_list.py`, `tests/test_ui_plans.py` (必要に応じて追加) をPlan中心のパスで実行する。
- `SCPLN_SKIP_SIMULATION_API=1` を利用してPSI実行をスキップし、CI時間を短縮。

## 7. 今後のフォローアップ候補
- `/runs` APIレスポンスに `plan_version_id` を公式フィールドとして追加し、summary依存を解消する。
- Run履歴フィルタに「Plan version」「Scenario name」を追加し、Plan中心運用での検索利便性を向上。
- 旧ドキュメント（README/Tutorial）からレガシーRun手順を完全に除去し、Plan中心フローへ統一。
- RunRegistryバックアップ/データ保持ポリシーの自動化（例: cron でのエクスポート）。
- Plan & Run実行時にシナリオロック状態などのバリデーションを追加し、運用ミスを予防。

## 8. 関連リソース
- `/ui/plans` : Plan中心運用のエントリポイント
- `/ui/runs` : Run履歴/比較
- `/ui/scenarios` : シナリオ管理（レガシーRunは停止中）
- `README.md` : 全体アーキテクチャと運用ハイライト
- `docs/config_integration_plan.md` : Canonical 設定統合計画と設計原則
- `docs/ops_backup.md` : RunRegistry/Canonical DB バックアップ手順

## 9. 更新履歴
- 2025-10-05: 現行運用サマリ、実績カラム、チェックリスト完了状況を追加。
- 2025-09-26: 初版作成。
