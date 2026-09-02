# Auth Proxy + Tunnel — Query Face for #18

**Ticket:** #18 `Tunnel + Auth Proxy Query Face` — `ready-for-agent`, blocked by #15 (Orchestrator)

**Branch:** `feat/tunnel-auth-proxy-18` (promoted from `prototype/tunnel-auth-proxy` `095fffa`)

## What this delivers

Chain `claude.ai` → `https://qmd.example.com/mcp` (Cloudflare Edge) → `cloudflared QUIC 7844` → `Auth Proxy 127.0.0.1:3210` → `QMD HTTP MCP 127.0.0.1:8181` (`qmd mcp --http --daemon`, `QMD_ALLOWED_ORIGINS=*` behind proxy).

- **Tunnel:** named remotely-managed `cloudflared tunnel run --token $TUNNEL_TOKEN` (stable `tunnel_id.cfargotunnel.com`, custom `qmd.example.com`, `service KeepAlive` via systemd/launchd/SCM survives sleep/wake, `retries=5`)
- **Auth Proxy:** `auth_proxy/proxy.py` `check_auth` via `hmac.compare_digest` on `Authorization: Bearer <AUTH_PROXY_TOKEN>` (401 plain, not `WWW-Authenticate: Bearer resource_metadata`), forwards `Origin` verbatim for QMD's own `origin-guard` (`https://claude.ai` allowlist)
- **QMD:** stays `127.0.0.1:8181` default, `QMD_ALLOWED_ORIGINS=*` behind proxy (or `https://claude.ai,https://claude.com` directly)

## Smoke tests (thin boundary, `spec.md:128-131`)

```powershell
# Start QMD (or fake handler in tests)
$env:QMD_ALLOWED_ORIGINS="*"; qmd mcp --http --daemon --port 8181
# Start proxy
$env:AUTH_PROXY_TOKEN="secret123"; $env:QMD_TARGET="http://127.0.0.1:8181"; $env:PROXY_PORT="3210"; uv run python -m auth_proxy.proxy

# Correct token → 200 + tools/list (forwarded)
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer secret123" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Wrong/missing → 401 (no forward)
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer wrong" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Via tunnel (after `cloudflared tunnel run --token $TUNNEL_TOKEN` where ingress `service: http://127.0.0.1:3210`)
curl.exe -i -X POST https://qmd.example.com/mcp -H "Authorization: Bearer secret123" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Sleep/wake: close lid 10s, reopen, wait 20s (QUIC reconnect + service RestartSec) → correct-token curl still 200
```

Claude.ai: Settings → Connectors → Add custom connector → URL `https://qmd.example.com/mcp` + Request headers `Authorization: Bearer <TOKEN>` (beta, up to 4 headers). If org lacks beta, needs OAuth shim (see research #4).

## Files

- `auth_proxy/proxy.py` — `check_auth` + `ProxyApp(handle)` + `http.server` `__main__` (3210 → 8181)
- `tests/test_auth_proxy.py` — 7 tests (correct/wrong/missing/case/prefix/forward/Origin)
- This README

## Tests

`pytest tests/test_auth_proxy.py -v` 7 passed, `pytest tests -q` 42 passed, `mypy auth_proxy --ignore-missing-imports` Success.
