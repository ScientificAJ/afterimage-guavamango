#!/usr/bin/env bash
set -euo pipefail

uv run afterimage export-evidence --fixture accepted --output-dir evidence/replays
uv run afterimage export-evidence --fixture rejected --output-dir evidence/replays

echo "Recorded both deterministic evidence bundles in evidence/replays."
