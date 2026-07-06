# shellcheck shell=bash
# ──────────────────────────────────────────────────────────────────────────────
# wait_for_docker — block until the Docker daemon is reachable.
#
# launchd coalesces missed StartCalendarInterval jobs into a single run on wake.
# On a fresh wake/boot Docker Desktop may not have finished starting, so every
# `docker compose exec` fails ("Cannot connect to the Docker daemon") and the
# whole job is a silent no-op. Source this file and call `wait_for_docker "$LOG"`
# before any docker command.
#
# Args:  $1 = log file path (optional; falls back to stdout)
# Return: 0 when Docker is ready, 1 after ~5 min timeout (caller should abort).
# ──────────────────────────────────────────────────────────────────────────────
wait_for_docker() {
    local log="${1:-/dev/stdout}"
    echo "[pre] Waiting for Docker daemon …" | tee -a "$log"
    local i
    for i in $(seq 1 60); do
        if docker info >/dev/null 2>&1; then
            echo "  Docker ready." | tee -a "$log"
            return 0
        fi
        # Try to launch Docker Desktop on the first iteration (no-op if already up)
        [ "$i" -eq 1 ] && open -ga Docker 2>/dev/null || true
        sleep 5
    done
    echo "  [fatal] Docker daemon not ready after 5 min — aborting at $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$log"
    return 1
}
