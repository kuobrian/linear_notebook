#!/usr/bin/env bash
# Smoke test for a running compose stack (used by CI, runnable by hand):
#   docker/check.sh sqlite       # docker-compose.yml
#   docker/check.sh postgresql   # + docker-compose.postgres.yml
# Checks the web app and the MCP endpoint answer to a local Host header and refuse a foreign one, and
# that the database behind them is the expected kind with its tables created and seed data written.
set -euo pipefail

KIND="${1:?usage: check.sh sqlite|postgresql}"
WEB="${WEB_URL:-http://127.0.0.1:8000}"
MCP="${MCP_URL:-http://127.0.0.1:8765/mcp}"

fail() { echo "FAIL: $*" >&2; exit 1; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

[ "$(code -H 'Host: 127.0.0.1:8000' "$WEB/api/meta")" = 200 ] || fail "web app should answer a local Host"
[ "$(code -H 'Host: evil.example' "$WEB/api/meta")" = 421 ] || fail "web app should refuse a foreign Host with 421"

# Tables exist and the demo data was seeded into the database the app is really using.
info="$(curl -sf -H 'Host: 127.0.0.1:8000' "$WEB/api/database")" || fail "/api/database did not answer"
echo "$info" | grep -q "\"kind\":\"$KIND\"" || fail "expected a $KIND database, got: $info"
echo "$info" | grep -Eq '"issues":[1-9]' || fail "no seed data in the database: $info"

# MCP over HTTP: transport_security must refuse foreign hosts even though the container binds 0.0.0.0.
init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}'
mcp() { code -X POST "$MCP" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d "$init" "$@"; }
[ "$(mcp -H 'Host: 127.0.0.1:8765')" = 200 ] || fail "MCP should answer a local Host"
[ "$(mcp -H 'Host: evil.example')" = 421 ] || fail "MCP should refuse a foreign Host with 421"

echo "OK ($KIND)"
