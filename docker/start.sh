#!/usr/bin/env bash
# Run the web app and the MCP HTTP server side by side. If either one stops, stop the other and
# exit with its status so the container restarts instead of half-running.
set -uo pipefail

HOST="${BIND_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-8000}"
MCP_PORT="${MCP_PORT:-8765}"

# Create the tables once, before both servers start, so they don't race on an empty database.
python -c "from local_linear.db import init_db; init_db()" || exit 1

local-linear --host "$HOST" --port "$WEB_PORT" &
web=$!
local-linear-mcp --transport http --host "$HOST" --port "$MCP_PORT" &
mcp=$!

trap 'kill "$web" "$mcp" 2>/dev/null' TERM INT

wait -n "$web" "$mcp"
status=$?
kill "$web" "$mcp" 2>/dev/null
wait
exit "$status"
