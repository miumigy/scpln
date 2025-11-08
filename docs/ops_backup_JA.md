# データベース バックアップ手順

本ドキュメントは、本アプリケーションが利用する単一のSQLiteデータベースのバックアップとリストアに関する標準手順を定義します。このデータベースには、RunRegistry、Jobs、Plans、Scenariosなど、システムの全データが含まれています。

実行環境は `REGISTRY_BACKEND=db` を前提とし、環境別に日次バックアップを自動化することを想定しています。

## 1. 対象と前提
- 対象DB: `data/scpln.db`（環境変数 `SCPLN_DB` で上書き可）
- バックアップ先: `/var/backups/scpln/`（例。環境に合わせて調整）
- 作業者: SRE or 当番エンジニア
- 必須ツール: `sqlite3`, `gzip`, `cron` or `systemd timer`

## 2. バックアップ手順（日次）
1. `mkdir -p /var/backups/scpln/$(date +%Y)` で年別ディレクトリを確保。
2. 直近DBファイルをサーバ内でコピー（I/Oを最小化するため `sqlite3` のバックアップコマンドを使用）。

```
backup_root=/var/backups/scpln
now=$(date +%Y%m%d_%H%M)
src_db=${SCPLN_DB:-/opt/scpln/data/scpln.db}
tmp_copy=/tmp/scpln-${now}.db

sqlite3 "$src_db" ".backup '${tmp_copy}'"
gzip -c "$tmp_copy" > "${backup_root}/$(date +%Y)/scpln-${now}.db.gz"
rm -f "$tmp_copy"
```

3. `find ${backup_root} -type f -mtime +30 -name 'scpln-*.db.gz' -delete` で保持期間（30日）を超えたファイルを削除。
4. 完了後、`ls -lh ${backup_root}/$(date +%Y) | tail` をSlack Bot経由で通知。

### 推奨cron設定例
`/etc/cron.d/scpln-backup` に以下を配置し、毎日02:30にバックアップを実行。

```
30 2 * * * scpln /opt/scpln/scripts/backup_database.sh >> /var/log/scpln/backup.log 2>&1
```

※ `backup_database.sh` は上記手順2のスクリプトをラップし、環境変数ロード（`. /opt/scpln/.env`）を行う。

## 3. リストア手順
1. アプリケーションサービスを停止（例: `systemctl stop scpln-api`）。
2. 対象バックアップを `/tmp` へ展開。

```
restore_src=/var/backups/scpln/2025/scpln-20251005_0230.db.gz
tmp_db=/tmp/scpln-restore.db

gunzip -c "$restore_src" > "$tmp_db"
```

3. 既存DBを退避し、新DBへ差し替え。

```
mv /opt/scpln/data/scpln.db /opt/scpln/data/scpln.db.bak-$(date +%Y%m%d_%H%M)
mv "$tmp_db" /opt/scpln/data/scpln.db
chown scpln:scpln /opt/scpln/data/scpln.db
```

4. データベースの整合性を `sqlite3 /opt/scpln/data/scpln.db 'pragma integrity_check;'` で確認。
5. サービスを再起動し、アプリケーションが正常に動作し、データが復元されていることを確認。

## 4. 検証・監査
- CI: `make smoke-test` を staging で週次実行し、バックアップ後も主要機能が成功するか検証。
- 監視: `backup_success` メトリクスをPushgatewayに送信し、未送信が24時間継続した場合にPagerDuty通知。
- 監査ログ: `/var/log/scpln/backup.log` を月次でレビューし、失敗時はJiraに追跡チケットを作成。

## 5. フォールバック指針
- リストア後にデータ欠損が発見された場合、データ再構築スクリプト（例: `scripts/rebuild_from_artifacts.py --since YYYY-MM-DD`）を実行してPlan成果物などから再構築。
- フォールバックは24時間以内に完了し、完了後はSlack `#scpln-ops` へ報告テンプレート（復旧時間・影響範囲・再発防止）を投稿。

## 6. 更新履歴
- 2025-10-17: DB全体を対象とするようにドキュメントを更新。
- 2025-09-26: 初版作成（RunRegistry移行計画P0対応）。
