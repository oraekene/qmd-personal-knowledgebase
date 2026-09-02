"""Minimal Auth Proxy — shared-secret Bearer token gate between Cloudflare Tunnel and QMD HTTP MCP.

Per research #4 + spec.md:130 + CONTEXT.md:53:
- Listens where tunnel ingress points (e.g. localhost:3210), forwards to QMD at 8181 if authorized
- Checks `Authorization: Bearer <AUTH_PROXY_TOKEN>` via constant-time compare
- Returns 401 on missing/wrong, 200 + forward on correct
- Preserves method/path/body verbatim; for prototype we simulate via create_proxy_app

Prototype (HITL) — throwaway, does not ship; links branch prototype/tunnel-auth-proxy.
"""
from __future__ import annotations
import hmac
from typing import Callable, Tuple, Dict


def check_auth(headers: Dict[str, str], expected_token: str) -> bool:
    """Check Authorization header against expected token.

    Requires exact `Bearer <token>` (case-sensitive Bearer, single space).
    Uses constant-time compare to avoid timing leak.
    """
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if not auth.startswith("Bearer "):
        return False
    # Extract token after "Bearer " (7 chars)
    token = auth[7:]
    # Use constant-time compare; also ensure expected_token is str
    return hmac.compare_digest(token, expected_token)


class ProxyApp:
    """Minimal proxy app for TDD — handle() simulates HTTP without network.

    Real deployment would use http.server or FastAPI with httpx forwarding.
    For prototype, qmd_handler is a callable that mimics QMD response.
    """

    def __init__(self, expected_token: str, qmd_handler: Callable):
        self.expected_token = expected_token
        self.qmd_handler = qmd_handler

    def handle(self, method: str, path: str, headers: Dict[str, str], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        if not check_auth(headers, self.expected_token):
            return 401, {"Content-Type": "application/json"}, b'{"error": "Unauthorized"}'
        # Authorized — forward verbatim to QMD handler
        return self.qmd_handler(method, path, headers, body)


def create_proxy_app(expected_token: str, qmd_handler: Callable) -> ProxyApp:
    return ProxyApp(expected_token, qmd_handler)


# Optional: simple HTTP server for manual smoke test (not used in TDD)
# Run: AUTH_PROXY_TOKEN=secret123 QMD_TARGET=http://127.0.0.1:8181 python -m auth_proxy.proxy
if __name__ == "__main__":
    import os
    import sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import urllib.request
    import urllib.error

    token = os.environ.get("AUTH_PROXY_TOKEN", "secret123")
    target = os.environ.get("QMD_TARGET", "http://127.0.0.1:8181")
    listen_port = int(os.environ.get("PROXY_PORT", "3210"))

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items()}
            if not check_auth(headers, token):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized"}')
                return
            # Forward to QMD
            url = target + self.path
            req = urllib.request.Request(url, data=body, method="POST")
            for k, v in self.headers.items():
                if k.lower() not in ("host", "content-length"):
                    req.add_header(k, v)
            try:
                with urllib.request.urlopen(req) as resp:
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(resp.read())
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(e.read())
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(f'{{"error": "Bad Gateway: {e}"}}'.encode())

        def log_message(self, format, *args):
            sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), format % args))

    print(f"Auth Proxy listening on :{listen_port} -> {target} (token {token[:3]}...)")
    print("Smoke: curl -i -X POST http://127.0.0.1:3210/mcp -H \"Authorization: Bearer $AUTH_PROXY_TOKEN\" -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'")
    HTTPServer(("127.0.0.1", listen_port), Handler).serve_forever()
