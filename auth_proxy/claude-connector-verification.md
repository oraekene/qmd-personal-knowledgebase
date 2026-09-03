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
curl -i -X POST https://qmd.example.com/mcp -H "Authorization: Bearer $TOKEN" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# → 200 + {"tools":[{"name":"qmd_query"},...]}

# Fresh chat transcript (YYYY-MM-DD):
# Q: "Search my corpus..."
# A: [cites corpus/notes/...md:1-5, corpus/chats/claude/...md]
```

If beta headers unavailable, set `SKIP_CLAUDE_CONNECTOR=1` and rely on smoke + tunnel smokes; file an issue for OAuth shim per research #4.
