<#
.SYNOPSIS
  Submit a QaHelper command batch on THIS machine and collect the screenshot.

.DESCRIPTION
  Driver for tools/qahelper/QaHelper.cs when the controller runs locally on
  the edit station itself. Protocol:

    1. Read the current value of qa_seq.txt (0 if missing).
    2. Copy the batch file into place as qa_cmd.txt (via a temp name + rename,
       so QaHelper never sees a half-written file).
    3. Poll qa_seq.txt until it increments past the starting value (QaHelper
       increments it after executing the batch and writing qa_shot.png).
    4. Copy qa_shot.png to -ShotDest, if given.

  Refuses batches longer than 38 command lines: longer batches have been
  observed to be dropped silently by slow editors' message pumps. Split the
  work into multiple calls instead.

.PARAMETER BatchFile
  Path to a text file of QaHelper commands, one per line.

.PARAMETER ShotDest
  Optional path to copy the resulting qa_shot.png to.

.PARAMETER TimeoutSec
  Seconds to wait for the batch to complete. Default 60.

.EXAMPLE
  powershell -File tools\drive-local.ps1 -BatchFile batch.txt -ShotDest out\after.png
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BatchFile,

    [Parameter(Mandatory = $false)]
    [string]$ShotDest,

    [Parameter(Mandatory = $false)]
    [int]$TimeoutSec = 60
)

$ErrorActionPreference = 'Stop'

$MaxBatchLines = 38
$QaDir   = 'C:\Users\Public\Documents\qa'
$CmdPath = Join-Path $QaDir 'qa_cmd.txt'
$TmpPath = Join-Path $QaDir ("qa_cmd.{0}.tmp" -f $PID)
$SeqPath = Join-Path $QaDir 'qa_seq.txt'
$ShotPath = Join-Path $QaDir 'qa_shot.png'

function Get-Seq {
    if (Test-Path -LiteralPath $SeqPath) {
        $raw = (Get-Content -LiteralPath $SeqPath -Raw -ErrorAction SilentlyContinue)
        $val = 0
        if ([int]::TryParse(("$raw").Trim(), [ref]$val)) { return $val }
    }
    return 0
}

if (-not (Test-Path -LiteralPath $BatchFile)) {
    Write-Error "Batch file not found: $BatchFile"
    exit 1
}

# Enforce the 38-command ceiling (blank lines don't count; QaHelper skips them).
$lines = @(Get-Content -LiteralPath $BatchFile | Where-Object { $_.Trim() -ne '' })
if ($lines.Count -gt $MaxBatchLines) {
    Write-Error ("Batch has {0} commands; the ceiling is {1}. Batches over {1} are dropped silently by slow editors' message pumps - split into multiple calls." -f $lines.Count, $MaxBatchLines)
    exit 1
}
if ($lines.Count -eq 0) {
    Write-Error "Batch file is empty: $BatchFile"
    exit 1
}

if (-not (Test-Path -LiteralPath $QaDir)) {
    Write-Error "QA folder $QaDir does not exist - is QaHelper installed and running? See tools/qahelper/build.md."
    exit 1
}
if (Test-Path -LiteralPath $CmdPath) {
    Write-Error "A previous qa_cmd.txt is still pending at $CmdPath - QaHelper may not be running, or another driver is mid-batch."
    exit 1
}

$startSeq = Get-Seq

# Stage then rename, so the helper only ever sees a complete file.
Copy-Item -LiteralPath $BatchFile -Destination $TmpPath -Force
Move-Item -LiteralPath $TmpPath -Destination $CmdPath -Force

# Wait for QaHelper to finish the batch.
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$done = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 250
    if ((Get-Seq) -gt $startSeq) { $done = $true; break }
}

if (-not $done) {
    Write-Error ("Timed out after {0}s waiting for qa_seq.txt to pass {1}. Is QaHelper running in the interactive session?" -f $TimeoutSec, $startSeq)
    exit 2
}

if ($ShotDest) {
    if (-not (Test-Path -LiteralPath $ShotPath)) {
        Write-Error "Batch completed but $ShotPath is missing - check qa_err.txt in $QaDir."
        exit 3
    }
    $destDir = Split-Path -Parent $ShotDest
    if ($destDir -and -not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Copy-Item -LiteralPath $ShotPath -Destination $ShotDest -Force
    Write-Host ("Batch done (seq {0} -> {1}); screenshot copied to {2}" -f $startSeq, (Get-Seq), $ShotDest)
} else {
    Write-Host ("Batch done (seq {0} -> {1})" -f $startSeq, (Get-Seq))
}
exit 0
