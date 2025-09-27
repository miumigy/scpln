# RunRegistry運用ガイドライン

本ドキュメントは Plan 中心の RunRegistry 運用を円滑に行うための実務ルールとチェックポイントをまとめたものです。Plan生成から Run 履歴確認までの一貫したフロー、およびレガシー経路の段階的廃止に伴う留意事項を定義します。

## 1. 目的
- Plan & Run で生成される `run_id` と `plan_version_id` の整合性を保ち、監査・比較・再実行のトレーサビリティを保証する。
- Run履歴(UI/API)から Plan やシナリオへ即時遷移できる観測性を提供する。
- レガシー（シナリオUI→Run）経路を段階的に停止し、Plan UI 経由の統合パイプラインへ一本化する。

## 2. 環境変数と設定
| 変数 | 推奨値 | 用途 |
| --- | --- | --- |
| `REGISTRY_BACKEND` | `db` | RunRegistry を SQLite に永続化。Plan中心運用では DB バックエンドが前提。 |
| `RUNS_DB_MAX_ROWS` | `200` など | Runテーブルの保持上限。設定すると最古ランを自動削除。 |
| `SCPLN_ALLOW_LEGACY_SCENARIO_RUN` | `0` (既定) | `/ui/scenarios` からのレガシーRun投入を抑止。移行期間のみ `1` にして利用。 |
| `SCPLN_SKIP_SIMULATION_API` | `1` (テスト時) | CIやローカルテストで重いPSIシミュレーションをスキップ。運用環境では未設定。 |
| `SCPLN_DB` | `<path>` | テスト/ステージングごとにRunRegistry DBを切り替える際に指定。 |

## 3. 運用フロー
1. `/ui/plans` で Plan を作成し、Base Scenario と Canonical Config を選択して実行する。作成後は Summary に `config_version_id` と `base_scenario_id` が表示され、Run履歴と双方向リンクが張られる。
2. Run履歴(`/ui/runs`)では `plan_version_id` 列と `scenario_id` 列から該当Plan/シナリオに遷移できる。Run詳細(`/ui/runs/{run_id}`)でも Summary にリンクを表示。
3. Aggregate Jobフォームでは Plan version を指定できる。Plan起点で Run を再処理する際はここで `plan_version_id` を入力し、成果物をPlanにひも付けて管理する。
4. `/ui/jobs` では Plan作成ジョブが `plan_version_id` を示すため、完了後に該当Plan詳細へ遷移して結果を確認する。

## 4. 段階的なレガシー経路停止
- **Phase 1 (現在)**: `SCPLN_ALLOW_LEGACY_SCENARIO_RUN=0` が既定。シナリオUIに警告を表示し Plan UI への利用を促す。必要な場合に限りフラグを `1` にして一時的に解放。
- **Phase 2 (予定)**: 旧 `/ui/scenarios/{sid}/run` エンドポイントを非推奨化し、再びアクセスした場合は Plan UI へリダイレクトする。フラグ廃止前に利用者への周知を実施。
- **Phase 3 (最終)**: レガシーRun投入コードと関連テンプレートを削除。ドキュメントおよび tests からも完全に撤去する。

## 5. 監視とメトリクス
- `RUNS_TOTAL` (Prometheus) : Plan経由Runの件数が期待と合致しているか監視。
- `jobs_duration_seconds{type="planning"}` : Plan生成ジョブの処理時間を追跡し、異常な遅延を検知。
- RunRegistry バックアップ: `data/scpln.db` を日次コピー（任意）。上限を設定している場合は容量推移も併せて監視する。

## 6. テスト方針
- 重要テスト: `tests/test_jobs_canonical_inputs.py`, `tests/test_runs_persistence.py`, `tests/test_ui_runs_list.py`, `tests/test_ui_plans.py` (必要に応じて追加) をPlan中心のパスで実行する。
- `SCPLN_SKIP_SIMULATION_API=1` を利用してPSI実行をスキップし、CI時間を短縮。
- Legacyモードを利用するテストでは `SCPLN_ALLOW_LEGACY_SCENARIO_RUN=1` を明示的に設定し、今後の削除に備えて影響範囲を限定する。

## 7. 今後のフォローアップ候補
- `/runs` APIレスポンスに `plan_version_id` を公式フィールドとして追加する（現在はsummary内で補完）。
- Run履歴フィルタに「Plan version」「Scenario name」を追加し、UI上での検索利便性を向上。
- Legacy経路削除後、関連ドキュメント(README, tutorials) から旧手順を完全に削除し、Plan中心フローへ統一。
- RunRegistryバックアップ/データ保持ポリシーの自動化（例: cron でのエクスポート）。
- Plan & Run実行時のシナリオバリデーション追加（シナリオがロックされている場合の警告など）。

## 8. 参考リンク
- `/ui/plans` : Plan中心運用のエントリポイント
- `/ui/runs` : Run履歴/比較
- `/ui/scenarios` : シナリオ管理（レガシーRunは停止中）
- `/docs/config_integration_plan.md` : Canonical連携の開発計画
