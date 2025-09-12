# 用語統一（Planning Hub, P-23）

本プロジェクトで使用する主要用語の対訳・定義を示します（UI/README/APIで統一）。

- Plan（プラン）: 計画の中核オブジェクト。編集・実行・成果物を集約。
- Plan Version（プラン版）: プランのスナップショット。`version_id` で識別。
- Scenario（シナリオ）: 入力データ群の論理まとまり（需要/在庫/政策/制約など）。
- Pipeline（パイプライン）: 版管理された処理DAG（integrated/aggregate/allocate/mrp/reconcile）。
- Run（ラン）: シナリオ版 × パイプライン版 × 条件の実行記録（dry/apply/partial）。
- Job（ジョブ）: 非同期実行のまとまり（キュー投入・監視対象）。
- Change set（変更セット）: プランに対する差分（ドラフト→レビュー→適用/破棄）。
- Workspace（ワークスペース）: プラン詳細画面（`/ui/plans/{id}`）の作業空間。
- Aggregate/Disaggregate/Schedule/Validate/Execute/Results: プラン詳細のタブ名称。
- Reconciliation（整合）: AGG/DETの差分解消（anchor/carryover）。
- Anchor policy（アンカーポリシー）: DET_near/AGG_far/blend の調整方針。
- Carryover（持ち越し）: 境界近傍の差分の前後期への配分方法。
- Window days（ウィンドウ日数）: 境界の前後に設ける調整範囲（日数）。
- Cutover date（カットオーバ日）: 期間境界となる日付。
- KPI（主要指標）: fill rate, profit, capacity utilization, spill など。

補足:
- 推奨入口は Planning Hub（`/ui/plans`）。旧UI（`/ui/planning`）は廃止しました。
