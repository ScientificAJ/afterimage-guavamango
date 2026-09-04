#!/usr/bin/env bash
set -euo pipefail
export ALPACA_PAPER_TRADE=true
export ALPACA_TOOLSETS=assets,stock-data,options-data
exec uvx "${AFTERIMAGE_ALPACA_MCP_PACKAGE:-alpaca-mcp-server==2.3.1}" --transport stdio --env-file "${AFTERIMAGE_ENV_FILE:-.env}"
