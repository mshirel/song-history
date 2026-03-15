# Runbook: Restore Database from Backup

This runbook describes how to restore the worship catalog SQLite database from a
compressed backup created by `scripts/backup.sh`.

## Prerequisites

- `sqlite3` CLI installed (`apt-get install sqlite3` on Debian/Ubuntu)
- `gzip` / `gunzip` available (standard on all Linux/macOS systems)
- Access to a backup file: `backups/worship-YYYYMMDD-HHMMSS.sql.gz`

## Restore Procedure

### 1. Identify the backup to restore

List available backups, most recent first:

```sh
ls -lt backups/worship-*.sql.gz | head -10
```

### 2. Verify the backup file is intact

```sh
gzip -t backups/worship-20260314-120000.sql.gz && echo "OK"
```

If this fails, the backup file is corrupt. Choose an earlier backup.

### 3. Stop the application

If the application is running, stop it so no new writes occur during the restore:

```sh
docker compose down
```

### 4. Create a safe copy of the current database (optional but recommended)

```sh
cp data/worship.db data/worship.db.pre-restore-$(date +%Y%m%d-%H%M%S)
```

### 5. Restore the database

Replace `<backup-file>` with the path to your chosen `.sql.gz` file and
`<db-path>` with the target database path (usually `data/worship.db`):

```sh
gunzip -c <backup-file> | sqlite3 <db-path>
```

Example:

```sh
gunzip -c backups/worship-20260314-120000.sql.gz | sqlite3 data/worship.db
```

### 6. Verify the restore

Check that the database contains expected data:

```sh
sqlite3 data/worship.db "SELECT COUNT(*) FROM songs;"
sqlite3 data/worship.db "SELECT COUNT(*) FROM services;"
```

Both counts should be non-zero (assuming the backup was taken from a populated database).

### 7. Restart the application

```sh
docker compose up -d
```

Check the health endpoint:

```sh
curl http://localhost:8000/health
```

Expected response: `{"status": "ok", "db": "connected"}`

## Automated Backup Verification

To verify the most recent backup without restoring it:

```sh
make backup-verify
```

Or manually:

```sh
latest=$(ls -t backups/worship-*.sql.gz | head -1)
gzip -t "$latest" && echo "OK: $latest"
```

## Backup Frequency

Backups are created by `scripts/backup.sh` which should be scheduled via cron.
The `.last_success` sentinel file in the backup directory records the timestamp
of the most recent successful backup and can be monitored by a healthcheck.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `sqlite3: not found` | CLI not installed | `apt-get install sqlite3` |
| `gzip: invalid compressed data` | Corrupt backup | Choose an earlier backup |
| `Error: near "PRAGMA": syntax error` | Incompatible sqlite3 version | Use sqlite3 >= 3.35 |
| Health endpoint returns 503 | DB path wrong or permissions | Check `DB_PATH` env var and file ownership |
