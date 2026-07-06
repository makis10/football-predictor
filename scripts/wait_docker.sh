# shellcheck shell=bash
# ──────────────────────────────────────────────────────────────────────────────
# wait_for_docker — block until the daemon AND the db/backend containers are
# actually ready to serve requests.
#
# launchd coalesces missed StartCalendarInterval jobs into a single run on wake.
# On a fresh wake/boot Docker Desktop may not have finished starting, and even
# once the daemon answers, the `db`/`backend` containers can still be
# restarting or crash-looping for a while — every `docker compose exec` in
# that window fails ("service is not running" / connection refused) and the
# whole job is a silent no-op. Source this file and call `wait_for_docker "$LOG"`
# before any docker command.
#
# Args:  $1 = log file path (optional; falls back to stdout)
# Return: 0 when Docker + db + backend are ready, 1 after timeout (caller should abort).
# ──────────────────────────────────────────────────────────────────────────────
wait_for_docker() {
    local log="${1:-/dev/stdout}"
    echo "[pre] Waiting for Docker daemon …" | tee -a "$log"
    local i
    local daemon_ready=0
    for i in $(seq 1 60); do
        if docker info >/dev/null 2>&1; then
            echo "  Docker daemon ready." | tee -a "$log"
            daemon_ready=1
            break
        fi
        # Re-trigger Docker Desktop launch every ~30s in case it quit again mid-wait.
        if [ $(( (i - 1) % 6 )) -eq 0 ]; then
            open -ga Docker 2>/dev/null || true
        fi
        sleep 5
    done
    if [ "$daemon_ready" -ne 1 ]; then
        echo "  [fatal] Docker daemon not ready after 5 min — aborting at $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$log"
        return 1
    fi

    # Bring up any stopped services (idempotent — no-op for services already up).
    echo "[pre] Ensuring containers are up (docker compose up -d) …" | tee -a "$log"
    docker compose up -d >>"$log" 2>&1

    echo "[pre] Waiting for backend to answer /health …" | tee -a "$log"
    for i in $(seq 1 36); do
        if docker compose exec -T backend python -c \
            "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status==200 else 1)" \
            >/dev/null 2>&1; then
            echo "  Backend ready." | tee -a "$log"
            return 0
        fi
        sleep 5
    done
    echo "  [fatal] Backend not healthy after 3 min — aborting at $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$log"
    return 1
}
