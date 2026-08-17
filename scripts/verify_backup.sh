#!/usr/bin/env bash
# Prove the latest backup can actually be restored.
#
# backup_db.sh checks that the file is not suspiciously small. That catches a
# dump that failed outright; it says nothing about whether the contents restore.
# A gzip of a truncated dump, a dump taken mid-migration, a dump missing a table
# because of a permissions change — all pass a size check and all fail when you
# need them, which is the one moment you cannot afford to find out.
#
# So this restores the newest dump into a throwaway database inside the same
# Postgres container, counts the rows that matter, and drops it. Nothing touches
# the live database at any point: the scratch DB has its own name and is dropped
# in a trap, even if the script is interrupted.
#
# Usage:  ./scripts/verify_backup.sh
set -uo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a
PG_USER="${POSTGRES_USER:-user}"
PG_DB="${POSTGRES_DB:-football_db}"
BACKUP_DIR="${DB_BACKUP_DIR:-$HOME/football-predictor-backups}"

SCRATCH="restore_check_$(date +%s)"

cleanup() {
    docker compose exec -T db psql -U "$PG_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS $SCRATCH;" >/dev/null 2>&1 || true
}
trap cleanup EXIT

LATEST="$(ls -t "$BACKUP_DIR"/*.sql.gz 2>/dev/null | head -1)"
if [ -z "$LATEST" ]; then
    echo "✗ No backup found in $BACKUP_DIR" >&2
    exit 1
fi

AGE_H=$(( ( $(date +%s) - $(stat -f%m "$LATEST" 2>/dev/null || stat -c%Y "$LATEST") ) / 3600 ))
echo "▸ Verifying $(basename "$LATEST")  (${AGE_H}h old)"
if [ "$AGE_H" -gt 48 ]; then
    echo "✗ Newest backup is ${AGE_H}h old — the daily dump is not running." >&2
    exit 1
fi

docker compose exec -T db psql -U "$PG_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS $SCRATCH;" >/dev/null 2>&1
if ! docker compose exec -T db psql -U "$PG_USER" -d postgres \
        -c "CREATE DATABASE $SCRATCH;" >/dev/null 2>&1; then
    echo "✗ Could not create the scratch database." >&2
    exit 1
fi

echo "  restoring …"
if ! gunzip -c "$LATEST" | docker compose exec -T db psql -q -v ON_ERROR_STOP=1 \
        -U "$PG_USER" -d "$SCRATCH" >/dev/null 2>/tmp/restore_err.txt; then
    echo "✗ RESTORE FAILED — the backup is not usable:" >&2
    tail -5 /tmp/restore_err.txt >&2
    exit 1
fi

# Compare the restored copy against the live database. Exact equality is not the
# test — rows land between the dump and now — but an order-of-magnitude gap means
# the dump captured a fraction of the data.
FAIL=0
for TBL in matches predictions users value_bets tickets; do
    LIVE=$(docker compose exec -T db psql -tA -U "$PG_USER" -d "$PG_DB" \
           -c "SELECT count(*) FROM $TBL;" 2>/dev/null || echo 0)
    REST=$(docker compose exec -T db psql -tA -U "$PG_USER" -d "$SCRATCH" \
           -c "SELECT count(*) FROM $TBL;" 2>/dev/null || echo "MISSING")
    LIVE=$(echo "$LIVE" | tr -d '[:space:]'); REST=$(echo "$REST" | tr -d '[:space:]')
    if [ "$REST" = "MISSING" ]; then
        echo "  ✗ $TBL: table absent from the restored dump"; FAIL=1; continue
    fi
    if [ "$LIVE" -gt 0 ] && [ "$REST" -lt $(( LIVE / 2 )) ]; then
        echo "  ✗ $TBL: restored $REST vs live $LIVE — dump is incomplete"; FAIL=1; continue
    fi
    printf "  ✓ %-14s restored %-8s (live %s)\n" "$TBL" "$REST" "$LIVE"
done

if [ "$FAIL" -ne 0 ]; then
    echo "✗ Backup restored but the contents are wrong." >&2
    exit 1
fi

echo "✓ Backup verified — restored cleanly and the row counts line up."
