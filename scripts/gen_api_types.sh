#!/usr/bin/env bash
# Regenerate frontend/src/api/schema.d.ts from the backend's OpenAPI schema (no running server needed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCHEMA="$(mktemp -t mtgdm-openapi).json"
trap 'rm -f "$SCHEMA"' EXIT

(cd "$ROOT/backend" && uv run python -c 'import json; from mtgdm.app import create_app; print(json.dumps(create_app().openapi()))') > "$SCHEMA"
# Run via npx: openapi-typescript pins TypeScript 5 as a peer dep, the app uses TypeScript 6.
# --default-non-nullable false: fields with server-side defaults stay optional in request bodies.
(cd "$ROOT/frontend" && npx --yes openapi-typescript@7.13.0 "$SCHEMA" --default-non-nullable false -o src/api/schema.d.ts)
