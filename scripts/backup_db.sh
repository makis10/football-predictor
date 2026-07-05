#!/usr/bin/env bash
# Daily PostgreSQL backup — pg_dump → gzip → rotate.
#
# The Postgres volume holds everything that CAN'T be regenerated: user accounts,
# tracked bets, the value-bet ledger (CLV/ROI history), settled predictions. A
# lost volume = all of it gone. This takes a compressed logical dump and keeps
# the last $KEEP_DAYS days.
#
# Restore:  gunzip -c <file>.sql.gz | docker compose exec -T db psql -U <user> -d <db>
#
# Usage:  ./scripts/backup_db.sh        (also called at the top of run_daily.sh)
set -uo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd "$(dirname "$0")/.."

# Load DB creds (POSTGRES_USER/PASSWORD/DB) from .env.
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a
PG_USER="${POSTGRES_USER:-user}"
PG_DB="${POSTGRES_DB:-football_db}"

BACKUP_DIR="${DB_BACKUP_DIR:-$HOME/football-predictor-backups}"
KEEP_DAYS="${DB_BACKUP_KEEP_DAYS:-14}"
mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/${PG_DB}_${STAMP}.sql.gz"

echo "▸ Dumping $PG_DB → $OUT"
if docker compose exec -T db pg_dump -U "$PG_USER" "$PG_DB" | gzip > "$OUT"; then
    SIZE="$(du -h "$OUT" | cut -f1)"
    # A valid gzip'd dump is never a few bytes; guard against a silent empty dump.
    BYTES="$(stat -f%z "$OUT" 2>/dev/null || stat -c%s "$OUT" 2>/dev/null || echo 0)"
    if [ "$BYTES" -lt 1000 ]; then
        echo "✗ Backup suspiciously small ($BYTES bytes) — keeping it but check the DB." >&2
    else
        echo "✓ Backup OK ($SIZE)"
    fi
else
    echo "✗ pg_dump failed — no backup written." >&2
    rm -f "$OUT"
    exit 1
fi

# Rotate — drop dumps older than KEEP_DAYS.
find "$BACKUP_DIR" -name "${PG_DB}_*.sql.gz" -type f -mtime +"$KEEP_DAYS" -print -delete \
    | sed 's/^/  rotated out: /' || true

echo "  retained: $(find "$BACKUP_DIR" -name "${PG_DB}_*.sql.gz" | wc -l | tr -d ' ') backup(s) in $BACKUP_DIR"
