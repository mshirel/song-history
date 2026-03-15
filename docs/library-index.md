# Library Index

`data/library_index.json` is a pre-built JSON index of song credits scraped from the
TPH (Taylor Publications / Paperless Hymnal) library. It maps canonical song titles to
`{words_by, music_by, arranger}` metadata.

The file is committed to the repository and baked into the Docker image so that server
deployments (Pi, RKE2, any host without the Dropbox symlink) can resolve credits via
the library lookup without needing the original `.ppt` files.

---

## Structure

```json
{
  "amazing grace": {
    "display_title": "Amazing Grace",
    "words_by": "John Newton",
    "music_by": "Traditional",
    "arranger": null
  }
}
```

Keys are canonical titles (lowercase, punctuation stripped). Values include a display
title and up to three credit fields.

**Current snapshot:** ~3,380 songs, ~550 KB.

---

## Regenerating the Index

Run this on a machine where the `tph_libarary/` Dropbox symlink is active:

```bash
# Regenerate from the TPH library
worship-catalog library index --path tph_libarary/ --out data/library_index.json

# Verify the output looks right
python3 -c "import json; d=json.load(open('data/library_index.json')); print(len(d), 'songs')"

# Commit the updated snapshot
git add data/library_index.json
git commit -m "chore: regenerate library_index.json"
git push
```

CI will bake the new snapshot into the next Docker image automatically.

---

## Priority for File Variants

When multiple `.ppt` variants exist for the same title, the scraper picks the best:

| Priority | Suffix | Meaning |
|---|---|---|
| 0 (highest) | `-PH-HD` | Paperless Hymnal high-definition |
| 1 | `-HD` | High-definition |
| 2 | `-PH20` | Paperless Hymnal 2020 edition |
| 3 (lowest) | (plain) | Standard edition |
