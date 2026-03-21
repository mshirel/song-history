# Windows Auto-Submit Setup

Automatically upload worship PPTX files from the presentation PC to the
song-history Pi whenever new slides are saved.

---

## How It Works

A PowerShell script (`Submit-WorshipSlides.ps1`) runs on a schedule via
Windows Task Scheduler. It scans the worship folder tree for `.pptx` files,
computes a SHA-256 hash of each, and skips any that have already been
submitted. New or modified files are uploaded to the Pi's `/upload` endpoint.

A JSON manifest (`submitted-files.json`) tracks what's been sent so the same
file is never uploaded twice.

---

## Directory Structure

The script expects a year/date folder layout:

```
C:\Worship\
  2026\
    2026.01.05\
      AM Worship 2026.01.05.pptx
      PM Worship 2026.01.05.pptx
      Announcements 2026.01.05.pptx
    2026.01.12\
      AM Worship 2026.01.12.pptx
      PM Worship 2026.01.12.pptx
```

The script scans recursively, so any nesting depth works.

---

## Setup

### 1. Copy the script files

Copy these two files to a permanent location on the presentation PC
(e.g., `C:\Scripts\`):

- `scripts/Submit-WorshipSlides.ps1`
- `scripts/Submit-WorshipSlides.env.example`

### 2. Create the config file

```powershell
Copy-Item C:\Scripts\Submit-WorshipSlides.env.example C:\Scripts\Submit-WorshipSlides.env
notepad C:\Scripts\Submit-WorshipSlides.env
```

Fill in:

| Setting | Value |
|---|---|
| `UPLOAD_URL` | `https://songs.highland-coc.com/upload` |
| `WATCH_ROOT` | `C:\Worship` (or wherever slides are saved) |

### 3. Test manually

Open PowerShell and run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
& C:\Scripts\Submit-WorshipSlides.ps1
```

You should see log output showing which files were submitted. Check the
song-history web UI to confirm the songs appeared.

### 4. Create a scheduled task

Open **Task Scheduler** and create a new task:

| Field | Value |
|---|---|
| Name | `Submit Worship Slides` |
| Trigger | Daily at 1:00 PM (after Sunday morning service) |
| Action | Start a program |
| Program | `powershell.exe` |
| Arguments | `-NoProfile -ExecutionPolicy Bypass -File "C:\Scripts\Submit-WorshipSlides.ps1"` |
| Run whether user is logged on or not | Yes |

Or create it from an elevated PowerShell prompt:

```powershell
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Scripts\Submit-WorshipSlides.ps1"'

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "1:00PM"

Register-ScheduledTask `
    -TaskName "Submit Worship Slides" `
    -Action $action `
    -Trigger $trigger `
    -Description "Upload new PPTX worship slides to song-history" `
    -RunLevel Highest
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Config file not found" | Copy `.env.example` to `.env` next to the script |
| "Watch root not found" | Check `WATCH_ROOT` path in `.env` |
| Connection timeout | Verify the Pi is reachable: `curl https://songs.highland-coc.com/health` |
| File re-uploaded after edit | Expected — the hash changed, so it re-submits |
| Temp files uploaded | The script skips files starting with `~` (Office temp files) |

### Logs

Check `C:\Scripts\submit-worship-slides.log` (or the path in your `.env`)
for submission history and errors.

### Manifest

`submitted-files.json` maps file paths to SHA-256 hashes. Delete this file
to force re-submission of all files.
