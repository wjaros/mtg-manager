#!/usr/bin/env bash
# Dev mode: backend with auto-reload on :8765 + Vite dev server (proxies /api) on :5173.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

(cd "$ROOT/backend" && uv run mtgdm serve --reload) &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null' EXIT

cd "$ROOT/frontend" && npm run dev
