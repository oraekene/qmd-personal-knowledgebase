# Auth Proxy + Tunnel — Query Face for #18

**Ticket:** #18 `Tunnel + Auth Proxy Query Face` — `ready-for-agent`, blocked by #15 (Orchestrator)

**Branch:** `feat/tunnel-auth-proxy-18` (promoted from `prototype/tunnel-auth-proxy` `095fffa`)

## What this delivers

Chain `claude.ai` → `https://qmd.example.com/mcp` (Cloudflare Edge) → `cloudflared QUIC 7844` → `Auth Proxy 127.0.0.1:3210` → `QMD HTTP MCP 127.0.0.1:8181` (`qmd mcp --http --port 8181`, `QMD_ALLOWED_ORIGINS=*` behind proxy).

- **Tunnel:** named remotely-managed `cloudflared tunnel run --token $TUNNEL_TOKEN` (stable `tunnel_id.cfargotunnel.com`, custom `qmd.example.com`, `service KeepAlive` via systemd/launchd/SCM survives sleep/wake, `retries=5` via QUIC). See `auth_proxy/tunnel-config.example.yml` + `auth_proxy/services/systemd/cloudflared.service` + `auth_proxy/services/launchd/com.qmd.cloudflared.plist` + `auth_proxy/services/windows/README.md`.
- **Auth Proxy:** `auth_proxy/proxy.py` `check_auth` via `hmac.compare_digest` on `Authorization: Bearer <AUTH_PROXY_TOKEN>` (401 plain, not `WWW-Authenticate: Bearer resource_metadata`), forwards `Origin` verbatim for QMD's own `origin-guard` (`https://claude.ai` allowlist). Library (`proxy.py`) vs runnable (`server.py` + `__main__.py`) split fixes Divergent Change; 401 helper `unauthorized_response()` fixes Duplicated Code; `create_proxy_app` validates `expected_token` (fixes Middle Man).
- **QMD:** stays `127.0.0.1:8181` default, `QMD_ALLOWED_ORIGINS=*` behind proxy (or `https://claude.ai,https://claude.com` directly when exposed without proxy).

## Acceptance criteria coverage

- **AC1 — 200 vs 401 + Origin 403:** `curl -i -X POST https://qmd.example.com/mcp -H "Authorization: Bearer $TOKEN" -d '{"jsonrpc":"2.0","method":"tools/list"}'` →200, wrong/missing →401 (no forward, no `WWW-Authenticate`); direct `curl -H "Origin: https://attacker.example"` to QMD (`http://127.0.0.1:8181/mcp`) →403 without proxy, 200 via proxy (see `tests/test_auth_proxy.py::test_origin_via_proxy_vs_direct_qmd` + `scripts/smoke_auth_proxy.{sh,ps1}`).
- **AC2 — KeepAlive sleep/wake:** `cloudflared` + `qmd mcp --http` + `auth_proxy` run as services `KeepAlive`/`Restart=on-failure`; after 10s sleep/wake, correct-token curl still 200 without manual restart (20s QUIC reconnect + `RestartSec`). Units in `auth_proxy/services/` for systemd/launchd/SCM; smoke note at end of `scripts/smoke_auth_proxy.{sh,ps1}`.
- **AC3 — Claude.ai web:** Add custom connector `https://qmd.example.com/mcp` + `Authorization: Bearer <TOKEN>` (beta Request headers, up to 4) → `tools/list` succeeds and fresh web chat retrieves corpus Unit (e.g. `qmd query` via MCP). See `auth_proxy/claude-connector-verification.md` for steps + evidence template. If org lacks beta, needs OAuth shim per research #4.
- **AC4 — Tests + smokes:** thin auth-proxy boundary `auth_proxy/proxy.py` + `auth_proxy/server.py` style — correct 200 vs 401, constant-time `hmac.compare_digest`, forward verbatim (method/path/body/headers, upstream `HTTPError` headers/body verbatim), 401 plain, case-insensitive header lookup, empty-token bypass guard; smoke scripts document `curl` matrix (see below).

## Smoke tests (thin boundary, `spec.md:128-131`)

```powershell
# Start QMD (QMD_ALLOWED_ORIGINS=* behind proxy)
$env:QMD_ALLOWED_ORIGINS="*"; qmd mcp --http --port 8181
# Start proxy (canonical)
$env:AUTH_PROXY_TOKEN="secret123"; $env:QMD_TARGET="http://127.0.0.1:8181"; $env:PROXY_PORT="3210"; python -m auth_proxy
# Back-compat also works: python -m auth_proxy.proxy
# For local smoke without env, set ALLOW_INSECURE_DEFAULT=1 (uses secret123)

# Correct token → 200 + tools/list (forwarded verbatim)
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer secret123" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Wrong/missing → 401 plain (no WWW-Authenticate, no forward)
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer wrong" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Origin verbatim — via proxy attacker 200 (QMD_ALLOWED_ORIGINS=*), direct 403 (see scripts/smoke_*.sh)
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer secret123" -H "Origin: https://attacker.example" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Via tunnel (after `cloudflared tunnel run --token $TUNNEL_TOKEN` where ingress `service: http://127.0.0.1:3210`)
curl.exe -i -X POST https://qmd.example.com/mcp -H "Authorization: Bearer secret123" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Sleep/wake: close lid 10s, reopen, wait 20s (QUIC reconnect + service RestartSec) → correct-token curl still 200
```

Or run automated matrix:

```powershell
$env:AUTH_PROXY_TOKEN="secret123"; .\scripts\smoke_auth_proxy.ps1
# bash: AUTH_PROXY_TOKEN=secret123 ./scripts/smoke_auth_proxy.sh
```

Claude.ai: Settings → Connectors → Add custom connector → URL `https://qmd.example.com/mcp` + Request headers `Authorization: Bearer <TOKEN>` (beta, up to 4 headers). If org lacks beta, needs OAuth shim (see research #4 + `auth_proxy/claude-connector-verification.md`).

## Files

- `auth_proxy/proxy.py` — `check_auth` (case-insensitive header, empty-token guard, `hmac.compare_digest`) + `unauthorized_response()` + `ProxyApp(handle)` + `create_proxy_app` (validates)
- `auth_proxy/server.py` — `make_handler(token,target)` + `_send_unauthorized` + `_proxy_request` (preserves `self.command` verbatim, forwards upstream `HTTPError` headers/body verbatim) + `main()` (binds 127.0.0.1, fail-closed if `AUTH_PROXY_TOKEN` missing)
- `auth_proxy/__main__.py` — `python -m auth_proxy` entry point
- `auth_proxy/tunnel-config.example.yml` — ingress example (remotely-managed dashboard wins)
- `auth_proxy/services/systemd/{cloudflared,qmd-mcp,auth-proxy}.service` — `Restart=on-failure` KeepAlive
- `auth_proxy/services/launchd/com.qmd.{cloudflared,auth-proxy,qmd-mcp}.plist` — `KeepAlive NetworkState`
- `auth_proxy/services/windows/README.md` — SCM/NSSM steps + sleep/wake test
- `auth_proxy/claude-connector-verification.md` — AC3 evidence template
- `scripts/smoke_auth_proxy.{ps1,sh}` — AC1 200/401/403 + Tunnel + Origin matrix (checks no `WWW-Authenticate`)
- `tests/test_auth_proxy.py` — 20 tests (correct/wrong/missing/case/prefix/lowercase/double-space/trailing/empty-token/header-case/unauthorized-plain/forward-verbatim/Origin-direct-vs-via-proxy/no-forward-on-401/verbatim-HTTPError)

## Tests

`pytest tests/test_auth_proxy.py -v` 20 passed, `pytest tests -q` 55 passed, `mypy auth_proxy --ignore-missing-imports` Success.
