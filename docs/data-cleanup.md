# Data Cleanup

Commands for fixing bad data in the worship catalog database. Common scenarios:

- **Bad import** -- A file was imported with wrong metadata (e.g. `0000-00-00` date). The service needs to be deleted so the file can be re-imported after the bug is fixed.
- **Modified file re-import** -- If a PPTX is edited and re-imported, the file hash changes. The old service with stale data remains as a duplicate.
- **Orphaned songs** -- After deleting services, song rows with 0 performances accumulate in the database.

## Command Reference

### delete-service

Delete one or more services and all related data (service\_songs, copy\_events).

```bash
# Delete by service ID
worship-catalog cleanup delete-service --id 30 --db data/worship.db --yes

# Delete all services with a specific date
worship-catalog cleanup delete-service --date 0000-00-00 --db data/worship.db --yes

# Delete services matching date AND name pattern
worship-catalog cleanup delete-service --date 2026-02-15 --name "AM" --db data/worship.db --yes

# Preview what would be deleted (no changes made)
worship-catalog cleanup delete-service --id 30 --db data/worship.db --dry-run
```

### orphaned-songs

Find and remove songs that have 0 performances (no service\_songs rows). Also removes their song\_editions and copy\_events.

```bash
# Preview orphaned songs
worship-catalog cleanup orphaned-songs --db data/worship.db --dry-run

# Remove orphaned songs
worship-catalog cleanup orphaned-songs --db data/worship.db --yes
```

### find-duplicates

List services that share the same (service\_date, service\_name) but have different source\_hash values. Helps identify re-import conflicts.

```bash
worship-catalog cleanup find-duplicates --db data/worship.db
```

## Docker Usage

Use the `cli` service defined in `compose.yml`. It mounts `./data:/data` but
the CLI `--db` flag defaults to `data/worship.db` (a relative path that does
not exist inside the container). Always pass `--db /data/worship.db`:

```bash
# Using the cli compose service (volumes pre-configured)
docker compose run --rm cli worship-catalog cleanup find-duplicates --db /data/worship.db
docker compose run --rm cli worship-catalog cleanup delete-service --date 0000-00-00 --db /data/worship.db --yes
docker compose run --rm cli worship-catalog cleanup orphaned-songs --db /data/worship.db --dry-run
docker compose run --rm cli worship-catalog cleanup orphaned-songs --db /data/worship.db --yes
```

## Re-import Workflow

### For the church admin: just upload the deck again

**There is no re-import button, and none is needed** (#616). Uploading the same service's deck
through `/upload` replaces that service rather than duplicating it: `run_import` matches an existing
service on `(service_date, service_name)`, calls `delete_service_data`, and re-inserts — all inside
one `IMMEDIATE` transaction. A corrected deck therefore removes whatever the previous extraction got
wrong, including phantom songs.

This is the whole answer for the common case, it needs no CLI access, and the service page links to
it. The CLI workflow below is for a developer cleaning up after a *bug*, where several services are
affected at once and the decks may not be to hand.

> **Why not a button wired to the stored path?** #323 proposed re-running the import against
> `services.source_file`. That cannot work: `web/app.py` deletes the uploaded file in the `finally`
> of every import (#138), so `source_file` is a dangling path for every web-uploaded service — which
> is all of them. It would appear to work for a developer importing from the CLI and fail for the
> actual user. `tests/test_web.py::TestReimportByReuploadingTheDeck` pins both halves: that
> re-upload replaces, and that the deck really is deleted. If the second ever starts failing,
> re-import from the stored path has become buildable and #616 is worth revisiting.

### For a developer: after fixing a bug that caused bad data

```bash
# 1. ALWAYS backup before cleanup
/opt/song-history/scripts/backup.sh /opt/song-history/data/worship.db /opt/song-history/backups-usb

# 2. Delete the bad services
docker compose run --rm cli worship-catalog cleanup delete-service --date 0000-00-00 --db /data/worship.db --yes

# 3. Re-import the affected files
docker compose run --rm cli worship-catalog import /inbox/"AM Worship 2025.09.28.pptx" --db /data/worship.db

# 4. Clean up orphaned songs left behind
docker compose run --rm cli worship-catalog cleanup orphaned-songs --db /data/worship.db --yes
```

## Safety

- All destructive commands require `--yes` or interactive confirmation.
- Use `--dry-run` to preview changes before committing.
- Always back up the database before running cleanup commands.
