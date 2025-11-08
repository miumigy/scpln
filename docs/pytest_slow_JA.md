# pytest slow tests

`pytest.ini` で `slow` マーカーを定義し、統合/E2E系テストをここに集約しています。

- 通常のローカル検証: `PYTHONPATH=. .venv/bin/pytest -m "not slow"`
- 重量テストのみ確認: `PYTHONPATH=. .venv/bin/pytest -m slow`
- 所要時間の確認: `PYTHONPATH=. .venv/bin/pytest -m slow --durations=20`

CI では `slow` も含めて実行される想定ですが、ローカルでは高速サイクル維持のため `not slow` を基本方針としてください。
