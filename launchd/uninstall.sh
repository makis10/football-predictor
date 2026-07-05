#!/usr/bin/env bash
# Unload and remove football-predictor launchd services.
#
# Usage:
#   bash launchd/uninstall.sh

set -euo pipefail

AGENTS_DIR="$HOME/Library/LaunchAgents"

for label in com.football-predictor.cloudflared com.football-predictor.tunnel com.football-predictor.daily com.football-predictor.odds-poll com.football-predictor.prematch com.football-predictor.results-poll; do
    plist="$AGENTS_DIR/$label.plist"
    if [[ -f "$plist" ]]; then
        echo "Unloading $label …"
        launchctl unload "$plist" 2>/dev/null || true
        rm "$plist"
        echo "  ✓ removed"
    else
        echo "  (not installed: $label)"
    fi
done

echo "Done."
