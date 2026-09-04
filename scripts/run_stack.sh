#!/usr/bin/env bash
set -euo pipefail

uv run afterimage serve --host 127.0.0.1 --port 8000 &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT

pnpm --dir apps/web dev
