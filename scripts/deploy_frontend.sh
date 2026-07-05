#!/usr/bin/env bash
# Rebuild + redeploy the frontend (production standalone image).
#
# The public app runs the optimised prod build (not the dev/HMR override), so
# source edits under frontend/src DO NOT hot-reload — they need a rebuild. This
# is also the type-check: `next build` fails on any TypeScript error, so a green
# build == a passing tsc.
#
# Usage:  ./scripts/deploy_frontend.sh
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd "$(dirname "$0")/.."

echo "▸ Building frontend (type-checks via next build) …"
docker compose build frontend

echo "▸ Restarting frontend container …"
docker compose up -d frontend

echo "✓ Frontend rebuilt & redeployed. Changes are now live."
