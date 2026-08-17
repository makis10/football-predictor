#!/usr/bin/env bash
# Keep the log directory from growing without limit.
#
# Nothing had ever rotated these. On 2026-08-11 daily.log was 9.7 MB across
# 100,864 lines covering weeks of runs, tunnel-stderr.log was 10 MB, and reading
# "what happened this morning" meant finding the last run's start line and
# slicing by line number. Logs you cannot read are logs you stop reading, and
# they are the only record of what the pipeline actually did.
#
# Rotation is by SIZE, not by day: the pipeline writes very unevenly (a retrain
# day is many times a normal one), so a daily rotation would leave some files
# huge and others empty.
#
# Truncate-in-place rather than rename: launchd holds these files open, and a
# renamed file keeps receiving writes to an inode nobody can find.
#
# Usage:  ./scripts/rotate_logs.sh          (called at the end of run_daily.sh)
set -uo pipefail

LOG_DIR="${ALERT_LOG_DIR:-$HOME/Library/Logs/football-predictor}"
MAX_MB="${LOG_MAX_MB:-5}"
KEEP="${LOG_KEEP_ARCHIVES:-5}"

[ -d "$LOG_DIR" ] || { echo "No log dir at $LOG_DIR"; exit 0; }

rotated=0
for f in "$LOG_DIR"/*.log; do
    [ -f "$f" ] || continue
    bytes=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0)
    [ "$bytes" -gt $(( MAX_MB * 1024 * 1024 )) ] || continue

    stamp="$(date +%Y%m%d_%H%M%S)"
    # Copy then truncate, so the writing process keeps the same file descriptor.
    if cp "$f" "$f.$stamp" 2>/dev/null && gzip -f "$f.$stamp" 2>/dev/null; then
        : > "$f"
        mb=$(( bytes / 1024 / 1024 ))
        echo "  rotated $(basename "$f") (${mb}MB) → $(basename "$f").$stamp.gz"
        rotated=$(( rotated + 1 ))
    else
        echo "  [warn] could not rotate $(basename "$f")" >&2
    fi

    # Keep only the newest $KEEP archives per log.
    ls -t "$f".*.gz 2>/dev/null | tail -n +$(( KEEP + 1 )) | while read -r old; do
        rm -f "$old"
    done
done

if [ "$rotated" -eq 0 ]; then
    echo "  no log over ${MAX_MB}MB — nothing to rotate."
fi
