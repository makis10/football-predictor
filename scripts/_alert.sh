#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Outbound alerting for the HOST-side scheduled jobs — the bash twin of
# backend/app/alerting.py, pointed at the same GATE_ALERT_URL sink so there is
# one place to change the destination.
#
# The scheduled jobs used to alert with `osascript display notification`, which
# only exists on the Mac's own screen: if the machine is locked, asleep, or
# simply not in the room, the alert is never seen. Every failure this project
# has actually been bitten by (site 502 for a day, five days of IP-blocked
# API-Football calls) was invisible for exactly that reason.
#
# Best-effort by design: never fails the caller, never blocks longer than 10 s.
# No GATE_ALERT_URL → silent no-op, so a fresh checkout without .env still runs.
# ──────────────────────────────────────────────────────────────────────────────

ALERT_LOG_DIR="${ALERT_LOG_DIR:-$HOME/Library/Logs/football-predictor}"

# send_alert <title> <message> [priority] [tags] [logfile]
#   priority: min|low|default|high|urgent   (ntfy)
#   tags:     comma-separated emoji shortcodes, e.g. "warning,soccer"
#   logfile:  bare name ("daily.log") or an absolute path — WHERE TO LOOK.
#
# An alert that says what broke but not where to read about it sends you
# hunting through ~/Library/Logs by hand at the worst moment. The path goes in
# the macOS notification's SUBTITLE (its own line, and it survives in
# Notification Center) and is appended to the phone push, which has room for
# the ready-to-paste tail command.
send_alert() {
    local title="$1" message="$2" priority="${3:-default}" tags="${4:-warning}"
    local logfile="${5:-}" logpath="" subtitle=""

    if [ -n "$logfile" ]; then
        case "$logfile" in
            /*) logpath="$logfile" ;;
            *)  logpath="$ALERT_LOG_DIR/$logfile" ;;
        esac
        subtitle="📄 $logpath"
    fi

    # Also post to the local screen — free, and useful when sitting at the Mac.
    local subtitle_clause=""
    [ -n "$subtitle" ] && subtitle_clause=" subtitle \"${subtitle//\"/\'}\""
    osascript -e "display notification \"${message//\"/\'}\" with title \"${title//\"/\'}\"${subtitle_clause} sound name \"Basso\"" \
        2>/dev/null || true

    # Phone push gets the command itself — nothing to remember or reconstruct.
    if [ -n "$logpath" ]; then
        message="$message

📄 tail -120 $logpath"
    fi

    [ -n "${GATE_ALERT_URL:-}" ] || return 0

    if printf '%s' "$GATE_ALERT_URL" | grep -qi 'ntfy'; then
        # ntfy takes the body raw and everything else as headers. Headers must be
        # latin-1, so the title is stripped to ASCII (emoji go in Tags instead);
        # the message body is UTF-8 and keeps its Greek text.
        local ascii_title
        ascii_title=$(printf '%s' "$title" | LC_ALL=C tr -cd '\11\12\15\40-\176')
        curl -fsS -m 10 \
            -H "Title: ${ascii_title:-Football Predictor}" \
            -H "Priority: $priority" \
            -H "Tags: $tags" \
            -d "$message" \
            "$GATE_ALERT_URL" >/dev/null 2>&1 || true
    else
        # {"content": …} suits Discord, {"text": …} Slack — send both keys so one
        # URL works for either without per-provider config (mirrors alerting.py).
        local body="$title"$'\n'"$message"
        curl -fsS -m 10 -H 'Content-Type: application/json' \
            --data "$(printf '{"content":%s,"text":%s}' \
                        "$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
                        "$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")" \
            "$GATE_ALERT_URL" >/dev/null 2>&1 || true
    fi
}
