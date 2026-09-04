#!/usr/bin/env bash
set -euo pipefail

afterimage_demo_dir="$(mktemp -d)"
trap 'rm -rf -- "$afterimage_demo_dir"' EXIT
export AFTERIMAGE_DB_URL="sqlite:///$afterimage_demo_dir/demo.db"
export AFTERIMAGE_SIGNING_KEY_PATH="$afterimage_demo_dir/demo-warrant.pem"

uv run afterimage export-evidence --fixture accepted --output-dir evidence/replays
uv run afterimage export-evidence --fixture rejected --output-dir evidence/replays

echo "Recorded both deterministic evidence bundles in evidence/replays."
