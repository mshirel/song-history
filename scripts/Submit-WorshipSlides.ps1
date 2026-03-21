<#
.SYNOPSIS
    Scans a folder tree for new/modified PPTX files and submits them to the
    song-history web API for automatic import.

.DESCRIPTION
    Designed to run as a Windows Task Scheduler job on the church presentation PC.
    Walks a year-based directory structure (e.g. 2026/2026.03.16/) looking for
    .pptx files that haven't been submitted yet.  Tracks submitted files by
    SHA-256 hash in a local JSON manifest so re-saves don't re-upload.

    Directory structure expected:
      <WatchRoot>\2026\2026.01.05\AM Worship 2026.01.05.pptx
      <WatchRoot>\2026\2026.01.05\PM Worship 2026.01.05.pptx
      <WatchRoot>\2026\2026.01.05\Announcements 2026.01.05.pptx

.PARAMETER ConfigPath
    Path to the .env configuration file.  Defaults to Submit-WorshipSlides.env
    in the same directory as this script.

.NOTES
    Requires PowerShell 5.1+ (ships with Windows 10/11).
    Issue #151 — https://github.com/mshirel/song-history/issues/151
#>
[CmdletBinding()]
param(
    [string]$ConfigPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $PSScriptRoot "Submit-WorshipSlides.env"
}

if (-not (Test-Path $ConfigPath)) {
    Write-Error "Config file not found: $ConfigPath.  Copy Submit-WorshipSlides.env.example and fill in values."
    exit 1
}

# Parse .env file (KEY=VALUE, one per line, # comments)
$config = @{}
Get-Content $ConfigPath | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $parts = $line -split "=", 2
        if ($parts.Count -eq 2) {
            $config[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
}

$uploadUrl    = $config["UPLOAD_URL"]
$watchRoot    = $config["WATCH_ROOT"]
$manifestPath = $config["MANIFEST_PATH"]
$logPath      = $config["LOG_PATH"]

if (-not $uploadUrl)    { Write-Error "UPLOAD_URL not set in config"; exit 1 }
if (-not $watchRoot)    { Write-Error "WATCH_ROOT not set in config"; exit 1 }
if (-not $manifestPath) { $manifestPath = Join-Path $PSScriptRoot "submitted-files.json" }
if (-not $logPath)      { $logPath = Join-Path $PSScriptRoot "submit-worship-slides.log" }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $entry = "[$ts] [$Level] $Message"
    Add-Content -Path $logPath -Value $entry
    if ($Level -eq "ERROR") { Write-Warning $entry } else { Write-Host $entry }
}

function Get-FileHash256 {
    param([string]$FilePath)
    (Get-FileHash -Path $FilePath -Algorithm SHA256).Hash
}

function Load-Manifest {
    if (Test-Path $manifestPath) {
        return (Get-Content $manifestPath -Raw | ConvertFrom-Json -AsHashtable)
    }
    return @{}
}

function Save-Manifest {
    param([hashtable]$Manifest)
    $Manifest | ConvertTo-Json -Depth 3 | Set-Content $manifestPath -Encoding UTF8
}

function Submit-File {
    param([string]$FilePath)
    $fileName = Split-Path $FilePath -Leaf
    $mimeType = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    # Build multipart form data
    $fileBytes = [System.IO.File]::ReadAllBytes($FilePath)
    $boundary = [System.Guid]::NewGuid().ToString()

    $bodyLines = @(
        "--$boundary",
        "Content-Disposition: form-data; name=`"file`"; filename=`"$fileName`"",
        "Content-Type: $mimeType",
        "",
        ""  # placeholder for binary content
    )
    $headerBytes = [System.Text.Encoding]::UTF8.GetBytes(($bodyLines -join "`r`n"))
    $footerBytes = [System.Text.Encoding]::UTF8.GetBytes("`r`n--$boundary--`r`n")

    # Concatenate header + file bytes + footer
    $body = New-Object byte[] ($headerBytes.Length + $fileBytes.Length + $footerBytes.Length)
    [System.Buffer]::BlockCopy($headerBytes, 0, $body, 0, $headerBytes.Length)
    [System.Buffer]::BlockCopy($fileBytes, 0, $body, $headerBytes.Length, $fileBytes.Length)
    [System.Buffer]::BlockCopy($footerBytes, 0, $body, $headerBytes.Length + $fileBytes.Length, $footerBytes.Length)

    $headers = @{ "Content-Type" = "multipart/form-data; boundary=$boundary" }

    $response = Invoke-RestMethod -Uri $uploadUrl -Method Post -Body $body -Headers $headers -TimeoutSec 60
    return $response
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-Log "Starting scan of $watchRoot"

if (-not (Test-Path $watchRoot)) {
    Write-Log "Watch root not found: $watchRoot" "ERROR"
    exit 1
}

$manifest = Load-Manifest
$submitted = 0
$skipped = 0
$failed = 0

# Scan for .pptx files recursively
$pptxFiles = Get-ChildItem -Path $watchRoot -Filter "*.pptx" -Recurse -File |
    Where-Object { $_.Name -notlike "~*" -and $_.Name -notlike ".*" }

foreach ($file in $pptxFiles) {
    $hash = Get-FileHash256 -FilePath $file.FullName

    # Skip if already submitted with same hash
    if ($manifest.ContainsKey($file.FullName) -and $manifest[$file.FullName] -eq $hash) {
        $skipped++
        continue
    }

    Write-Log "Submitting: $($file.FullName) (hash: $($hash.Substring(0,12))...)"

    try {
        $result = Submit-File -FilePath $file.FullName
        $jobId = $result.job_id
        Write-Log "Accepted: job_id=$jobId for $($file.Name)"

        # Record in manifest
        $manifest[$file.FullName] = $hash
        $submitted++
    }
    catch {
        $errMsg = $_.Exception.Message
        Write-Log "FAILED to submit $($file.Name): $errMsg" "ERROR"
        $failed++
    }
}

# Save manifest after processing all files
Save-Manifest -Manifest $manifest

Write-Log "Scan complete: $submitted submitted, $skipped already up-to-date, $failed failed"

if ($failed -gt 0) {
    exit 1
}
exit 0
