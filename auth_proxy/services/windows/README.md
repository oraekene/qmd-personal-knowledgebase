# Windows Service (SCM) — QMD Tunnel + Auth Proxy + QMD MCP

Per #18 AC2: `KeepAlive`/`Restart=on-failure` via SCM (services.msc) survives sleep/wake (QUIC reconnect ~20s).

## Install (PowerShell, Admin)

```powershell
# 1. Cloudflare Tunnel — SCM via cloudflared service install
cloudflared service install --token $env:TUNNEL_TOKEN
# This creates service `cloudflared` with Automatic start; SCM will restart on failure.
# Verify: Get-Service cloudflared | Select Status

# 2. QMD MCP (8181) — via NSSM or sc.exe
# Option A: NSSM (recommended for env + logs)
nssm install QMD-MCP "C:\tools\qmd\qmd.exe" "mcp --http --port 8181"
nssm set QMD-MCP AppEnvironmentExtra QMD_ALLOWED_ORIGINS=*
nssm set QMD-MCP Start SERVICE_AUTO_START
nssm set QMD-MCP AppRestartDelay 2000
nssm start QMD-MCP

# Option B: sc.exe (loopback-only, no env file)
sc.exe create QMD-MCP binPath= "C:\tools\qmd\qmd.exe mcp --http --port 8181" start= auto
sc.exe failure QMD-MCP reset= 60 actions= restart/5000/restart/5000/restart/5000
# Set env via registry: HKLM\SYSTEM\CurrentControlSet\Services\QMD-MCP\Environment

# 3. Auth Proxy (3210 -> 8181) — NSSM
nssm install QMD-AuthProxy "C:\Python313\python.exe" "-m auth_proxy"
nssm set QMD-AuthProxy AppEnvironmentExtra AUTH_PROXY_TOKEN=__YOUR_TOKEN__ QMD_TARGET=http://127.0.0.1:8181 PROXY_PORT=3210
nssm set QMD-AuthProxy DependOnService QMD-MCP
nssm set QMD-AuthProxy Start SERVICE_AUTO_START
nssm set QMD-AuthProxy AppRestartDelay 2000
nssm start QMD-AuthProxy
```

## Sleep/wake test

```powershell
# 1. Verify 200 before sleep
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer $env:AUTH_PROXY_TOKEN" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# 2. Sleep 10s: rundll32.exe powrprof.dll,SetSuspendState Sleep
# 3. Wake, wait 20s (QUIC reconnect + SCM RestartSec)
Start-Sleep 20
curl.exe -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer $env:AUTH_PROXY_TOKEN" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Expect 200 without manual restart. If 401/502, check: Get-Service QMD-AuthProxy,QMD-MCP,cloudflared
```

## Token rotation

Update `AUTH_PROXY_TOKEN` in NSSM (`nssm set QMD-AuthProxy AppEnvironmentExtra ...`), restart service, redeploy Cloudflare Pages mirror if using same token there (mirror token is separate).
