#!/usr/bin/env bash
#
# drive-ssh.sh — submit a QaHelper command batch to a REMOTE Windows machine
# over ssh/scp and collect the screenshot.
#
# Counterpart to tools/drive-local.ps1 for when the controller runs somewhere
# other than the edit station. Requires an OpenSSH server on the Windows box
# (default shell cmd.exe) and key-based auth already set up.
#
# Configure the target host via environment variable (placeholder shown —
# set your own):
#
#   export QA_HOST=user@edit-station
#
# Usage:
#   tools/drive-ssh.sh BATCH_FILE [SHOT_DEST] [TIMEOUT_SEC]
#
#   BATCH_FILE   text file of QaHelper commands, one per line
#   SHOT_DEST    optional local path to copy the resulting qa_shot.png to
#   TIMEOUT_SEC  seconds to wait for completion (default 60)
#
# Protocol: stage the batch as qa_cmd.tmp, rename it to qa_cmd.txt (so the
# helper never reads a half-copied file), then poll qa_seq.txt until it
# increments, then scp qa_shot.png back.
#
# Refuses batches longer than 38 command lines: longer batches have been
# observed to be dropped silently by slow editors' message pumps. Split the
# work into multiple calls instead.

set -euo pipefail

MAX_BATCH_LINES=38
HOST="${QA_HOST:-user@edit-station}"   # placeholder — set QA_HOST

# Remote paths, in both cmd.exe form (for ssh commands) and scp form.
QA_DIR_WIN='C:\Users\Public\Documents\qa'
QA_DIR_SCP='C:/Users/Public/Documents/qa'

usage() {
    echo "usage: $0 BATCH_FILE [SHOT_DEST] [TIMEOUT_SEC]" >&2
    echo "       QA_HOST=user@edit-station must point at the Windows box" >&2
    exit 1
}

[ $# -ge 1 ] || usage
BATCH_FILE="$1"
SHOT_DEST="${2:-}"
TIMEOUT_SEC="${3:-60}"

if [ ! -f "$BATCH_FILE" ]; then
    echo "error: batch file not found: $BATCH_FILE" >&2
    exit 1
fi

if [ "$HOST" = "user@edit-station" ]; then
    echo "error: QA_HOST is not set (still the placeholder). export QA_HOST=youruser@your-edit-pc" >&2
    exit 1
fi

# Enforce the 38-command ceiling (blank lines don't count; QaHelper skips them).
line_count=$(grep -c '[^[:space:]]' "$BATCH_FILE" || true)
if [ "$line_count" -gt "$MAX_BATCH_LINES" ]; then
    echo "error: batch has $line_count commands; the ceiling is $MAX_BATCH_LINES." >&2
    echo "Batches over $MAX_BATCH_LINES are dropped silently by slow editors' message pumps - split into multiple calls." >&2
    exit 1
fi
if [ "$line_count" -eq 0 ]; then
    echo "error: batch file is empty: $BATCH_FILE" >&2
    exit 1
fi

# Read the current sequence number (0 if the file doesn't exist yet).
get_seq() {
    local raw
    raw=$(ssh "$HOST" 'type '"$QA_DIR_WIN"'\qa_seq.txt 2>nul' 2>/dev/null | tr -d '[:space:]' || true)
    case "$raw" in
        ''|*[!0-9]*) echo 0 ;;
        *)           echo "$raw" ;;
    esac
}

# Refuse to stomp a batch that is still pending.
pending=$(ssh "$HOST" 'if exist '"$QA_DIR_WIN"'\qa_cmd.txt (echo YES) else (echo NO)' | tr -d '[:space:]')
if [ "$pending" = "YES" ]; then
    echo "error: a previous qa_cmd.txt is still pending on $HOST - QaHelper may not be running, or another driver is mid-batch." >&2
    exit 1
fi

start_seq=$(get_seq)

# Stage then rename, so the helper only ever sees a complete file.
scp -q "$BATCH_FILE" "$HOST:$QA_DIR_SCP/qa_cmd.tmp"
ssh "$HOST" 'move /Y '"$QA_DIR_WIN"'\qa_cmd.tmp '"$QA_DIR_WIN"'\qa_cmd.txt >nul'

# Poll for completion.
elapsed=0
done=0
while [ "$elapsed" -lt "$TIMEOUT_SEC" ]; do
    sleep 1
    elapsed=$((elapsed + 1))
    now_seq=$(get_seq)
    if [ "$now_seq" -gt "$start_seq" ]; then
        done=1
        break
    fi
done

if [ "$done" -ne 1 ]; then
    echo "error: timed out after ${TIMEOUT_SEC}s waiting for qa_seq.txt to pass $start_seq." >&2
    echo "Is QaHelper running in the interactive session on $HOST? (see tools/qahelper/build.md)" >&2
    exit 2
fi

if [ -n "$SHOT_DEST" ]; then
    dest_dir=$(dirname "$SHOT_DEST")
    [ -d "$dest_dir" ] || mkdir -p "$dest_dir"
    scp -q "$HOST:$QA_DIR_SCP/qa_shot.png" "$SHOT_DEST"
    echo "batch done (seq $start_seq -> $now_seq); screenshot copied to $SHOT_DEST"
else
    echo "batch done (seq $start_seq -> $now_seq)"
fi
