#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Uptime watchdog — runs every 5 minutes via launchd.
#
# aitipster.net is a public site running off this Mac. When Docker Desktop
# restarts, the machine wakes from sleep, or a container OOMs, everything stops
# and NOTHING notices: `restart: unless-stopped` doesn't help once the daemon
# itself stopped the containers, the dead-man's-switch heartbeats are unset
# (HEARTBEAT_URL empty → no-op), and the only self-heal is the 06:00 daily run.
# That leaves an outage window of up to ~24 h — which is exactly how the site sat
# at 502 on 2026-07-27 until someone checked by hand.
#
# So: probe the frontend, and if it's not answering, bring the stack back and say
# so. Cheap (one curl per 5 min) and silent while everything is healthy.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# launchd's minimal PATH lacks Docker Desktop's /usr/local/bin — without this
# every `docker` call fails with "command not found" and the watchdog is a
# silent no-op (the same trap the other scheduled jobs hit).
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/football-predictor"
LOG="$LOG_DIR/watchdog.log"
HEALTH_URL="${WATCHDOG_URL:-http://localhost:3000/}"
mkdir -p "$LOG_DIR"

cd "$PROJ_DIR"

# GATE_ALERT_URL lives in .env; without it send_alert falls back to a local
# macOS notification, which nobody sees when they're away from the Mac.
set -a
# shellcheck disable=SC1091
source "$PROJ_DIR/.env" 2>/dev/null || true
set +a
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_alert.sh"

# ── Dead-man's switch for the daily pipeline ─────────────────────────────────
# run_daily.sh can only alert about failures it survives to report. If launchd
# never fires it, the Mac is asleep at 06:00, or the job dies mid-run, the log
# simply stops — and nothing notices. This watchdog already wakes every 5 min,
# so it is the natural place to notice that the last completed run is too old.
#
# 26 h, not 24 h: a run takes ~20 min and launchd can drift after a wake, so a
# 24 h threshold would false-alarm on healthy days. Alerts at most once a day
# (stamp file) — a stuck pipeline shouldn't push 288 notifications.
DAILY_LOG="$LOG_DIR/daily.log"
STALE_STAMP="$LOG_DIR/.daily-stale-alerted"
if [ -f "$DAILY_LOG" ]; then
    last_complete=$(grep 'Daily run complete at' "$DAILY_LOG" | tail -1 \
                    | sed -E 's/.*complete at //')
    if [ -n "$last_complete" ]; then
        last_epoch=$(date -j -f '%Y-%m-%d %H:%M:%S' "$last_complete" +%s 2>/dev/null || echo 0)
        age_h=$(( ( $(date +%s) - last_epoch ) / 3600 ))
        if [ "$last_epoch" -gt 0 ] && [ "$age_h" -ge 26 ]; then
            # Alerted within the last 24 h already? Then stay quiet.
            if [ ! -f "$STALE_STAMP" ] || [ "$(find "$STALE_STAMP" -mtime +1 2>/dev/null)" ]; then
                echo "── $(date '+%Y-%m-%d %H:%M:%S') daily pipeline stale (${age_h}h since last completed run)" >> "$LOG"
                send_alert "Football Predictor: daily pipeline stale" \
                    "Τελευταίο ολοκληρωμένο daily run πριν ${age_h} ώρες (${last_complete}). Δεν τρέχει το pipeline." \
                    high "rotating_light,clock2" "daily.log"
                touch "$STALE_STAMP"
            fi
        elif [ -f "$STALE_STAMP" ]; then
            rm -f "$STALE_STAMP"   # recovered — re-arm for the next outage
        fi
    fi
fi

# ── API-Football: address watch + automatic recovery ─────────────────────────
# The account is IP-whitelisted and this line's address is dynamic. When it
# changes, every API-Football request is refused — answered HTTP 200 with no
# data — and until 2026-09-10 the first anyone heard of it was the next 06:00
# pre-flight, up to a day later; the odds poll had logged the refusal 167 times
# without a word. Two jobs here, both cheap: /status does not count against the
# daily quota, and it is only asked while something is unconfirmed.
#
#  1. Address watch. Whenever the public address is not the one API-Football
#     last accepted, ask /status. Refused → one urgent push per address,
#     carrying the address to paste into the dashboard.
#  2. Recovery. A daily run that found API-Football unusable skipped all of its
#     steps and left .af-recovery-pending holding the date. Once /status
#     answers cleanly, start run_af_recovery.sh, which replays exactly what was
#     skipped — whitelisting the address is then the only manual step.
AF_IP_OK="$LOG_DIR/.af-ip-ok"                 # last address API-Football accepted
AF_IP_ALERTED="$LOG_DIR/.af-ip-alerted"       # last address we pushed an alert for
AF_PENDING="$LOG_DIR/.af-recovery-pending"    # written by run_daily.sh
AF_LAUNCHED="$LOG_DIR/.af-recovery-launched"  # at most one launch per 30 min
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_lock.sh"

# Prints ok | ip | error | unknown: what API-Football says about this address.
af_status() {
    local body
    [ -n "${API_SPORTS_KEY:-}" ] || { echo unknown; return; }
    body=$(curl -s -m 15 -H "x-apisports-key: $API_SPORTS_KEY" \
               https://v3.football.api-sports.io/status 2>/dev/null) || { echo unknown; return; }
    printf '%s' "$body" | python3 -c '
import json, sys
try:
    e = json.load(sys.stdin).get("errors")
except Exception:
    print("unknown"); sys.exit()
print("ok" if not e else "ip" if isinstance(e, dict) and "Ip" in e else "error")
' 2>/dev/null || echo unknown
}

af_verdict=""
cur_ip=$(curl -s -m 5 https://api.ipify.org 2>/dev/null || true)
# Only an IPv4-shaped answer counts — an error page must not read as a change.
if printf '%s' "$cur_ip" | grep -qE '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' \
   && [ "$cur_ip" != "$(cat "$AF_IP_OK" 2>/dev/null)" ]; then
    af_verdict=$(af_status)
    case "$af_verdict" in
        ok)
            echo "$cur_ip" > "$AF_IP_OK"
            echo "── $(date '+%Y-%m-%d %H:%M:%S') API-Football accepts $cur_ip" >> "$LOG"
            ;;
        ip)
            if [ "$(cat "$AF_IP_ALERTED" 2>/dev/null)" != "$cur_ip" ]; then
                echo "$cur_ip" > "$AF_IP_ALERTED"
                echo "── $(date '+%Y-%m-%d %H:%M:%S') API-Football REFUSES $cur_ip — alerting" >> "$LOG"
                send_alert "API-Football blocked - IP changed" \
                    "$(printf 'Η δημόσια IP άλλαξε και το API-Football την απορρίπτει. Πρόσθεσέ τη στο whitelist (dashboard.api-football.com):\n\n%s\n\nΜέχρι τότε: κανένα CL/EL/ECL fixture ή αποτέλεσμα, φιλικά, στατιστικά, τραυματίες. Ό,τι παραλείψει το daily ξανατρέχει αυτόματα μόλις γίνει δεκτή.' "$cur_ip")" \
                    urgent "rotating_light" "watchdog.log"
            fi
            ;;
    esac
fi

if [ "$(cat "$AF_PENDING" 2>/dev/null)" = "$(date '+%Y-%m-%d')" ] \
   && ! lock_held run_daily \
   && [ -z "$(find "$AF_LAUNCHED" -mmin -30 2>/dev/null)" ]; then
    [ -n "$af_verdict" ] || af_verdict=$(af_status)
    if [ "$af_verdict" = "ok" ]; then
        touch "$AF_LAUNCHED"
        echo "── $(date '+%Y-%m-%d %H:%M:%S') API-Football answers again — starting run_af_recovery.sh" >> "$LOG"
        # Its own session: launchd kills whatever is left in a job's process
        # group when the job exits, and this tick ends in seconds while the
        # recovery takes half an hour. (macOS has no setsid command.)
        python3 -c 'import subprocess, sys; subprocess.Popen(["/bin/bash", sys.argv[1]], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)' \
            "$PROJ_DIR/scripts/run_af_recovery.sh" 2>> "$LOG" || true
    fi
fi

# Healthy? Then stay quiet — this runs 288 times a day.
# curl already prints "000" when it can't connect, and exits non-zero doing so —
# a `|| echo 000` fallback would concatenate into "000000".
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" 2>/dev/null)
code=${code:-000}
if [ "$code" = "200" ]; then
    exit 0
fi

echo "── $(date '+%Y-%m-%d %H:%M:%S') site not answering (HTTP $code) — recovering" >> "$LOG"

# Don't fight the daily/prematch jobs if one of them is mid-run (they stop and
# start containers themselves); the lock is released long before the next tick.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_lock.sh"
acquire_lock "run_watchdog" || exit 0

if ! docker info >/dev/null 2>&1; then
    echo "   Docker daemon is down — starting Docker Desktop" >> "$LOG"
    open -a Docker 2>/dev/null || true
    # shellcheck disable=SC1091
    source "$PROJ_DIR/scripts/wait_docker.sh"
    wait_for_docker "$LOG" || {
        send_alert "Football Predictor: site down" \
            "Docker δεν ξεκινά — το site είναι κάτω." urgent "rotating_light" "watchdog.log"
        exit 1
    }
fi

docker compose up -d >> "$LOG" 2>&1

# Give the frontend a moment, then confirm we actually fixed it rather than
# reporting success because the command exited 0.
for _ in $(seq 1 20); do
    sleep 3
    # curl already prints "000" when it can't connect, and exits non-zero doing so —
# a `|| echo 000` fallback would concatenate into "000000".
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" 2>/dev/null)
code=${code:-000}
    [ "$code" = "200" ] && break
done

if [ "$code" = "200" ]; then
    echo "   recovered at $(date '+%H:%M:%S')" >> "$LOG"
    send_alert "Football Predictor: recovered" \
        "Το site είχε πέσει και επανήλθε αυτόματα." default "warning" "watchdog.log"
else
    echo "   STILL DOWN (HTTP $code) after restart" >> "$LOG"
    send_alert "Football Predictor: site down" \
        "Το site είναι κάτω (HTTP $code) και δεν επανέρχεται μετά από restart — χρειάζεται έλεγχος." \
        urgent "rotating_light" "watchdog.log"
fi
