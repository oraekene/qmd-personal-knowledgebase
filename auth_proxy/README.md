# Prototype: Auth Proxy + Tunnel skeleton

**Ticket:** #12 `Prototype: Auth Proxy + Tunnel skeleton` — `wayfinder:prototype` (HITL, throwaway, does not ship) — blocked by #4 research.

**Branch:** `prototype/tunnel-auth-proxy`

## What this prototype proves

Chain `claude.ai` (or any MCP client) → `https://qmd.example.com/mcp` (Cloudflare Edge) → `cloudflared QUIC 7844` → `Auth Proxy localhost:3210` → `QMD HTTP MCP 127.0.0.1:8181` (with `QMD_ALLOWED_ORIGINS=*` behind proxy).

Per research #4 + spec.md:130 + CONTEXT.md:53:
- Named remotely-managed Tunnel `cloudflared tunnel run --token $TUNNEL_TOKEN` (stable `tunnel_id.cfargotunnel.com`), not quick `trycloudflare.com`
- Service `KeepAlive` (systemd LaunchAgent/SCM) survives sleep/wake — `retries=5` covers transient, service covers beyond
- Auth Proxy checks `Authorization: Bearer <AUTH_PROXY_TOKEN>` via `hmac.compare_digest` (constant-time), returns plain `401` (not `WWW-Authenticate: Bearer resource_metadata` which triggers OAuth discovery)
- QMD stays `localhost:8181` default, no `Host` allowlist needed when proxy is loopback

## Smoke tests (thin boundary, spec Testing Decisions)

```powershell
# 1. Start fake QMD (or real `qmd mcp --http --port 8181` with `QMD_ALLOWED_ORIGINS=*`)
# For prototype, fake handler in tests already covers forwarding; for manual:
$env:AUTH_PROXY_TOKEN="secret123"; $env:QMD_TARGET="http://127.0.0.1:8181"; $env:PROXY_PORT="3210"
uv run python -m auth_proxy.proxy
# In another shell:
# Correct token → 200 + tools/list (forwarded)
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer secret123" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Wrong token → 401 (no forward)
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer wrong" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Missing → 401
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Via tunnel (after `cloudflared tunnel run --token $TUNNEL_TOKEN` where ingress service: http://127.0.0.1:3210):
curl.exe -i -X POST https://qmd.example.com/mcp -H "Authorization: Bearer secret123" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Sleep/wake recovery: close lid 10s, reopen, wait 20s (QUIC reconnect + service RestartSec), repeat correct-token curl → still 200 without manual restart
```

Claude.ai registration: Settings → Connectors → Add custom connector → URL `https://qmd.example.com/mcp` + Request headers `Authorization: Bearer <TOKEN>` (beta, up to 4 headers). If org lacks beta, UI shows only OAuth `client_id/secret` → need FastAPI OAuth shim (see research #4, issues #10/#644).

## Files

- `auth_proxy/proxy.py` — `check_auth(headers, expected)` + `ProxyApp(handle)` + `__main__` http.server (20 LOC forward)
- `tests/test_auth_proxy.py` — 6 tests (correct/wrong/missing/case/prefix/forward)
- This README — smoke + tunnel flags

## Next

Real implementation moves this to `auth_proxy` service with `httpx` forward, `QMD_ALLOWED_ORIGINS=*` env, and `cloudflared service install` KeepAlive. Prototype sharpens token-header vs OAuth decision per #4.
