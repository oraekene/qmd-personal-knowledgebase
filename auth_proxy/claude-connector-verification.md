# Claude.ai Web Custom Connector — Verification for #18 AC3

Per `spec.md:128-131` + issue #18: Claude.ai web at `https://claude.ai` attaches
`tunnel https://qmd.example.com/mcp` + `Authorization: Bearer <TOKEN>` (beta Request headers)
and retrieves corpus Units via MCP `tools/list` + `qmd query`.

## Prerequisites

- QMD running: `QMD_ALLOWED_ORIGINS=* qmd mcp --http --port 8181` (or `qmd mcp --http --daemon`)
- Auth Proxy: `AUTH_PROXY_TOKEN=<secret> QMD_TARGET=http://127.0.0.1:8181 python -m auth_proxy` (systemd/launchd/SCM per `auth_proxy/services/`)
- Tunnel: `cloudflared tunnel run --token $TUNNEL_TOKEN` where dashboard ingress `qmd.example.com -> http://127.0.0.1:3210`
- Smoke passes: `AUTH_PROXY_TOKEN=<secret> ./scripts/smoke_auth_proxy.sh` — proxy 200/401 + direct 403 + tunnel 200

## Steps

1. Claude.ai → Settings → Connectors → Add custom connector
   - URL: `https://qmd.example.com/mcp`
   - Request headers (beta, up to 4): `Authorization: Bearer <AUTH_PROXY_TOKEN>`
   - Save — expect `tools/list` succeeds (shows `qmd_query`, `qmd_get` etc.). If org lacks beta, see research #4 OAuth shim.

2. Fresh web chat (no prior context): prompt
   > Search my corpus for the OCR models I selected and why. Cite sources.

3. Expected: chat calls `qmd query` via MCP, returns top-5 Units from `corpus/{notes,chats}` with provenance (`silo`, `source`, `url`), and can `qmd get` a Unit.

## Evidence

Record `tools/list` response + chat transcript excerpt showing corpus Unit retrieval (redact token). Paste below:

```
# tools/list via tunnel (curl)
curl -i -X POST https://kb.parmeterai.space/mcp \
  -H "Authorization: Bearer <AUTH_PROXY_TOKEN_REDACTED>" \
  -H "Content-Type: application/json" \
  -H "User-Agent: Mozilla/5.0" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# -> HTTP/2 200 OK
# Content-Type: text/event-stream
# Tools available: qmd_query, qmd_get
```

### Connector Status (2026-09-16)

`SKIP_CLAUDE_CONNECTOR=1` recorded per line 40.
Reason: User's Claude.ai organization account currently only supports OAuth 2.0 Dynamic Client Registration (RFC 7591 / RFC 8414) and lacks the beta "Custom Request Headers" UI.
Follow-up issue filed: [#25 feat(auth_proxy): OAuth 2.0 Dynamic Client Registration shim for Claude.ai Web MCP connector](https://github.com/oraekene/qmd-personal-knowledgebase/issues/25).
Direct tunnel MCP endpoint verified live and green via curl smoke.

