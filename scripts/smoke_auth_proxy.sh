#!/usr/bin/env bash
# Smoke: Auth Proxy + QMD + Tunnel — per #18 AC1 + spec.md:128-131
# Usage: AUTH_PROXY_TOKEN=secret123 ./scripts/smoke_auth_proxy.sh
set -euo pipefail
: "${AUTH_PROXY_TOKEN:?Set AUTH_PROXY_TOKEN}"
PROXY_URL="${PROXY_URL:-http://127.0.0.1:3210/mcp}"
TUNNEL_URL="${TUNNEL_URL:-https://qmd.example.com/mcp}"
QMD_DIRECT_URL="${QMD_DIRECT_URL:-http://127.0.0.1:8181/mcp}"
PAYLOAD='{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

check() {
  local url=$1 token_header=$2 expect=$3 label=$4 origin=${5:-}
  local hdr=()
  hdr+=(-H "Content-Type: application/json")
  [ -n "$token_header" ] && hdr+=(-H "$token_header")
  [ -n "$origin" ] && hdr+=(-H "Origin: $origin")
  set +e
  resp=$(curl -s -i -X POST "$url" "${hdr[@]}" -d "$PAYLOAD" 2>&1)
  code=$(echo "$resp" | head -1 | grep -oE '[0-9]{3}' | head -1)
  has_www=$(echo "$resp" | grep -i "WWW-Authenticate:" || true)
  set -e
  if [ "$code" != "$expect" ]; then
    echo "FAIL $label — expected $expect got $code ($url)"; echo "$resp"; exit 1
  fi
  if [ "$expect" = "401" ] && [ -n "$has_www" ]; then
    echo "FAIL $label — 401 must not include WWW-Authenticate"; exit 1
  fi
  echo "PASS $label — $code"
}

echo "=== Via proxy (127.0.0.1:3210) — AC1 ==="
check "$PROXY_URL" "Authorization: Bearer $AUTH_PROXY_TOKEN" 200 "proxy correct →200"
check "$PROXY_URL" "Authorization: Bearer wrong" 401 "proxy wrong →401"
check "$PROXY_URL" "" 401 "proxy missing →401"
check "$PROXY_URL" "Authorization: Bearer $AUTH_PROXY_TOKEN" 200 "proxy Origin claude.ai →200" "https://claude.ai"
check "$PROXY_URL" "Authorization: Bearer $AUTH_PROXY_TOKEN" 200 "proxy Origin attacker via proxy →200 (QMD_ALLOWED_ORIGINS=*)" "https://attacker.example"

echo "=== Direct to QMD (without proxy) — 403 proof ==="
if [ "${SKIP_DIRECT_QMD:-0}" != "1" ]; then
  if check "$QMD_DIRECT_URL" "" 403 "direct attacker →403" "https://attacker.example" 2>/dev/null; then
    check "$QMD_DIRECT_URL" "" 200 "direct claude.ai →200" "https://claude.ai"
  else
    echo "SKIP direct QMD — set QMD_ALLOWED_ORIGINS=https://claude.ai or SKIP_DIRECT_QMD=1 if behind proxy (*)"
  fi
fi

if [ "${SKIP_TUNNEL:-0}" != "1" ]; then
  echo "=== Via tunnel ==="
  if curl -sf "$TUNNEL_URL" -H "Authorization: Bearer $AUTH_PROXY_TOKEN" -d "$PAYLOAD" >/dev/null 2>&1; then
    check "$TUNNEL_URL" "Authorization: Bearer $AUTH_PROXY_TOKEN" 200 "tunnel correct →200"
    check "$TUNNEL_URL" "Authorization: Bearer wrong" 401 "tunnel wrong →401"
    check "$TUNNEL_URL" "" 401 "tunnel missing →401"
  else
    echo "SKIP tunnel — not reachable (cloudflared tunnel run --token ... required)"
  fi
fi
echo "=== All smokes passed ==="
echo "Sleep/wake AC2: sleep 10s, wake, wait 20s (QUIC+RestartSec), re-run — correct-token must still 200"
