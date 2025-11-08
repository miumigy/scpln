# Database backup runbook

This standard operating procedure covers backup and restore tasks for the SQLite database used by the application. The database stores all RunRegistry, job, plan, and scenario data.

Assumptions: `REGISTRY_BACKEND=db` and daily automated backups per environment.

## 1. Scope and prerequisites
- Target DB: `data/scpln.db` (override with the `SCPLN_DB` environment variable).
- Backup location: `/var/backups/scpln/` (adjust per environment).
- Operator: SRE or on-call engineer.
- Required tools: `sqlite3`, `gzip`, and `cron` or `systemd` timers.

## 2. Daily backup procedure
1. Ensure yearly directories: `mkdir -p /var/backups/scpln/$(date +%Y)`.
2. Copy the current DB using the `sqlite3` backup command to minimize I/O.

```
backup_root=/var/backups/scpln
now=$(date +%Y%m%d_%H%M)
src_db=${SCPLN_DB:-/opt/scpln/data/scpln.db}
tmp_copy=/tmp/scpln-${now}.db

sqlite3 "$src_db" ".backup '${tmp_copy}'"
gzip -c "$tmp_copy" > "${backup_root}/$(date +%Y)/scpln-${now}.db.gz"
rm -f "$tmp_copy"
```

3. Retain 30 days: `find ${backup_root} -type f -mtime +30 -name 'scpln-*.db.gz' -delete`.
4. Notify completion via Slack bot with `ls -lh ${backup_root}/$(date +%Y) | tail`.

### Recommended cron entry
Place the following in `/etc/cron.d/scpln-backup` to run daily at 02:30:

```
30 2 * * * scpln /opt/scpln/scripts/backup_database.sh >> /var/log/scpln/backup.log 2>&1
```

`backup_database.sh` wraps step 2 and loads environment variables (e.g., `. /opt/scpln/.env`).

## 3. Restore procedure
1. Stop application services (e.g., `systemctl stop scpln-api`).
2. Extract the desired backup to `/tmp`.

```
restore_src=/var/backups/scpln/2025/scpln-20251005_0230.db.gz
tmp_db=/tmp/scpln-restore.db

gunzip -c "$restore_src" > "$tmp_db"
```

3. Swap the database.

```
mv /opt/scpln/data/scpln.db /opt/scpln/data/scpln.db.bak-$(date +%Y%m%d_%H%M)
mv "$tmp_db" /opt/scpln/data/scpln.db
chown scpln:scpln /opt/scpln/data/scpln.db
```

4. Verify integrity: `sqlite3 /opt/scpln/data/scpln.db 'pragma integrity_check;'`.
5. Restart services and confirm data accuracy.

## 4. Validation and audit
- CI: run `make smoke-test` weekly in staging to ensure post-backup functionality.
- Monitoring: push `backup_success` metrics to Pushgateway; alert via PagerDuty if missing for 24 hours.
- Audit log: review `/var/log/scpln/backup.log` monthly and file Jira tickets for failures.

## 5. Fallback guidance
- If data gaps are found after restore, run rebuild scripts (e.g., `scripts/rebuild_from_artifacts.py --since YYYY-MM-DD`) to regenerate from plan artifacts.
- Complete fallback within 24 hours and post the incident summary (recovery time, impact, mitigation) in Slack `#scpln-ops`.

## 6. Revision history
- 2025-10-17: Updated to cover full database scope.
- 2025-09-26: Initial version (RunRegistry migration plan P0).
