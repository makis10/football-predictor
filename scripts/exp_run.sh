#!/bin/bash
# Run a Python script inside the backend container under a concurrency slot.
#
#   scripts/exp_run.sh <host-log-file> <script.py> [args…]
#
# The audit fans experiments out across many agents, and the backend container
# shares an 8 GB VM with Postgres, Redis and the live API. Unbounded parallel
# training would OOM-kill whichever process is largest — not necessarily the
# experiment. So at most EXP_SLOTS (default 3) jobs run at once; the rest wait.
# OMP_NUM_THREADS=4 keeps each XGBoost/LightGBM fit from grabbing every core.
#
# Blocks until the job finishes — call it with run_in_background and read the
# log. The log's last line is "exit=<rc>".
set -u
LOG="$1"; shift
SLOTS="${EXP_SLOTS:-3}"
cd "$(dirname "$0")/.." || exit 2
: > "$LOG"
while :; do
  for s in $(seq 1 "$SLOTS"); do
    docker compose exec -T -e OMP_NUM_THREADS=4 -e EXP_SLOT="$s" backend \
      flock -n -E 250 "/app/backend/data/cache/.slot$s.lock" python "$@" >> "$LOG" 2>&1
    rc=$?
    if [ "$rc" -ne 250 ]; then echo "exit=$rc" >> "$LOG"; exit "$rc"; fi
  done
  sleep 20
done
