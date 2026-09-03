# Smoke: Auth Proxy + QMD + Tunnel — per #18 AC1 + spec.md:128-131
# Usage: $env:AUTH_PROXY_TOKEN="secret123"; .\scripts\smoke_auth_proxy.ps1
# Optional: $env:QMD_TARGET="http://127.0.0.1:8181" $env:PROXY_URL="http://127.0.0.1:3210/mcp" $env:TUNNEL_URL="https://qmd.example.com/mcp"
param(
  [string]$ProxyUrl = $env:PROXY_URL ?? "http://127.0.0.1:3210/mcp",
  [string]$TunnelUrl = $env:TUNNEL_URL ?? "https://qmd.example.com/mcp",
  [string]$QmdDirectUrl = $env:QMD_DIRECT_URL ?? "http://127.0.0.1:8181/mcp"
)
$token = $env:AUTH_PROXY_TOKEN
if (-not $token) { Write-Error "AUTH_PROXY_TOKEN not set"; exit 1 }

function Assert-Status($url, $headers, $body, $expected, $label) {
  $h = @{"Content-Type"="application/json"} + $headers
  try {
    $resp = Invoke-WebRequest -Uri $url -Method POST -Headers $h -Body $body -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 10
    $code = [int]$resp.StatusCode
  } catch {
    Write-Host "FAIL $label — request error: $_" -ForegroundColor Red; exit 1
  }
  if ($code -ne $expected) {
    Write-Host "FAIL $label — expected $expected got $code ($url)" -ForegroundColor Red
    Write-Host $resp.Content
    exit 1
  }
  # AC1: 401 must be plain, not WWW-Authenticate: Bearer resource_metadata
  if ($code -eq 401 -and $resp.Headers["WWW-Authenticate"]) {
    Write-Host "FAIL $label — 401 must not include WWW-Authenticate" -ForegroundColor Red; exit 1
  }
  Write-Host "PASS $label — $code" -ForegroundColor Green
  return $resp
}

$payload = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

Write-Host "=== Via proxy (127.0.0.1:3210) — AC1 ==="
Assert-Status $ProxyUrl @{"Authorization"="Bearer $token"} $payload 200 "proxy correct token →200"
Assert-Status $ProxyUrl @{"Authorization"="Bearer wrong"} $payload 401 "proxy wrong token →401 (no forward)"
Assert-Status $ProxyUrl @{} $payload 401 "proxy missing token →401"
# Origin allowlist: via proxy with QMD_ALLOWED_ORIGINS=* must 200 even for attacker
Assert-Status $ProxyUrl @{"Authorization"="Bearer $token"; "Origin"="https://claude.ai"} $payload 200 "proxy Origin claude.ai →200 (forwarded verbatim, QMD allows)"
Assert-Status $ProxyUrl @{"Authorization"="Bearer $token"; "Origin"="https://attacker.example"} $payload 200 "proxy Origin attacker →200 (forwarded, QMD behind proxy QMD_ALLOWED_ORIGINS=*)"

Write-Host "=== Direct to QMD (without proxy) — AC1 403 proof ==="
if ($env:SKIP_DIRECT_QMD -ne "1") {
  # QMD with allowlist https://claude.ai only should 403 attacker, 200 claude.ai
  # If QMD behind proxy is QMD_ALLOWED_ORIGINS=*, direct test requires separate QMD instance or env.
  # This smoke expects QMD_ALLOWED_ORIGINS=https://claude.ai,https://claude.com for direct URL.
  try {
    Assert-Status $QmdDirectUrl @{"Origin"="https://attacker.example"} $payload 403 "direct QMD attacker →403"
    Assert-Status $QmdDirectUrl @{"Origin"="https://claude.ai"} $payload 200 "direct QMD claude.ai →200"
  } catch {
    Write-Host "SKIP direct QMD check — set QMD_ALLOWED_ORIGINS=https://claude.ai or SKIP_DIRECT_QMD=1 if QMD is behind proxy (*)" -ForegroundColor Yellow
  }
}

Write-Host "=== Via tunnel (if cloudflared running) ==="
if ($env:SKIP_TUNNEL -ne "1") {
  try {
    Assert-Status $TunnelUrl @{"Authorization"="Bearer $token"} $payload 200 "tunnel correct →200"
    Assert-Status $TunnelUrl @{"Authorization"="Bearer wrong"} $payload 401 "tunnel wrong →401"
    Assert-Status $TunnelUrl @{} $payload 401 "tunnel missing →401"
  } catch {
    Write-Host "SKIP tunnel — not reachable (cloudflared tunnel run --token ... required)" -ForegroundColor Yellow
  }
}

Write-Host "=== All smokes passed ===" -ForegroundColor Green
Write-Host "Sleep/wake AC2: close lid 10s, reopen, wait 20s (QUIC+RestartSec), re-run this script — correct-token must still 200"
