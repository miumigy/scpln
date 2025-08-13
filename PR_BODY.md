## 目的
- main.py の肥大化解消と責務分離（API/モデル/エンジン）
- 出荷/到着の一元管理（in_transit_orders を廃止し pending_shipments に統一）

## 変更点
- feat(engine): `engine/simulator.py` を新設し、在庫/発注/生産/収支のロジックを集約
- feat(domain): `domain/models.py` に Pydantic モデルを分離
- feat(app): `app/api.py` に FastAPI ルーティングを分離（`main:app` 互換）
- refactor: `main.py` を薄いエントリポイント化（`app`/`SimulationInput`/`SupplyChainSimulator` を再エクスポート）
- refactor(engine): `in_transit_orders` を削除し、`pending_shipments` に統一
- docs(README): 状態管理と累積整合の記述を更新（未来日 `pending_shipments` を「期末未着」と定義）

## 互換性/影響
- 起動エントリ: 変更なし（`uvicorn main:app`）
- インポート: 変更なし（`from main import SimulationInput, SupplyChainSimulator`）
- 既存テスト: 全てグリーン（ユニットテスト実行で確認）

## 確認観点
- API/モデルの分離により、今後のポリシー/コスト/最適化の機能追加が容易か
- 期末未着の集計が `pending_shipments` の未来日で一意に表現できるか

## 備考
- 次ステップ案: レビュー間隔R導入、欠品モード（lost_sales）追加、KPI拡充
