#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Install football-predictor launchd services on macOS.
#
# What this does:
#   1. Substitutes __PROJ_DIR__ and __LOG_DIR__ placeholders in each plist.
#   2. Copies the filled-in plists to ~/Library/LaunchAgents/.
#   3. Loads (or reloads) each service with launchctl.
#
# The public tunnel is Cloudflare (cloudflared) — see CLOUDFLARED_SETUP.md.
#
# Run from the repo root:
#   bash launchd/install.sh
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/football-predictor"

# ── Locate .env (used by services at runtime) ────────────────────────────────
ENV_FILE="$PROJ_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: .env not found at $ENV_FILE"
    echo "       Copy .env.example to .env and fill in your values."
    exit 1
fi


# ── Prepare directories ───────────────────────────────────────────────────────
mkdir -p "$AGENTS_DIR" "$LOG_DIR"

# ── Helper: substitute placeholders + install a plist ────────────────────────
install_plist() {
    local template="$1"
    local label
    label="$(basename "$template" .plist)"
    local dest="$AGENTS_DIR/$label.plist"

    echo "Installing $label …"
    sed \
        -e "s|__PROJ_DIR__|$PROJ_DIR|g" \
        -e "s|__LOG_DIR__|$LOG_DIR|g" \
        "$template" > "$dest"

    # Unload first (ignore errors if not loaded)
    launchctl unload "$dest" 2>/dev/null || true
    launchctl load "$dest"
    echo "  ✓ $label loaded"
}

# ── Install all services ──────────────────────────────────────────────────────
install_plist "$SCRIPT_DIR/com.football-predictor.cloudflared.plist"   # Cloudflare tunnel
install_plist "$SCRIPT_DIR/com.football-predictor.daily.plist"
install_plist "$SCRIPT_DIR/com.football-predictor.odds-poll.plist"
install_plist "$SCRIPT_DIR/com.football-predictor.prematch.plist"
install_plist "$SCRIPT_DIR/com.football-predictor.results-poll.plist"

echo ""
echo "Done. Services installed:"
echo "  • com.football-predictor.cloudflared — Cloudflare tunnel → aitipster.net (always on)"
echo "  • com.football-predictor.daily     — daily data refresh at 06:00"
echo "  • com.football-predictor.odds-poll — odds movement snapshots every 3h"
echo "  • com.football-predictor.prematch  — closing-line odds refresh at 15:00"
echo ""
echo "Logs: $LOG_DIR/"
echo "Uninstall: bash $SCRIPT_DIR/uninstall.sh"
