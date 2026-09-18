"""Auth Proxy HTTP server — runnable side of the split (fixes Divergent Change).

Listens on 127.0.0.1:3210, forwards verbatim to QMD at 127.0.0.1:8181 if authorized.
Preserves method/path/body/headers verbatim; on upstream HTTPError forwards
status/headers/body verbatim (no forced Content-Type overwrite).

Per #18 + spec.md:128-131 + research #4.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from auth_proxy.oauth import handle_oauth_request
from auth_proxy.proxy import _UNAUTHORIZED_BODY, _UNAUTHORIZED_HEADERS, check_auth, check_origin

logger = logging.getLogger("auth_proxy")

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _load_dotenv() -> None:
    """Load repo-root .env variables into os.environ if missing."""
    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(env_file):
        return
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


def _allowed_origins() -> tuple[str, ...]:
    raw = os.environ.get("QMD_ALLOWED_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ("*",)
    return tuple(o.strip() for o in raw.split(",") if o.strip()) or ("*",)


def _send_unauthorized(handler: BaseHTTPRequestHandler) -> None:
    """Send 401 plain — deliberately no WWW-Authenticate header."""
    handler.send_response(401)
    for k, v in _UNAUTHORIZED_HEADERS.items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(_UNAUTHORIZED_BODY)


def make_handler(token: str, target: str) -> type[BaseHTTPRequestHandler]:
    """Factory so token/target are captured without globals."""

    class Handler(BaseHTTPRequestHandler):
        # class vars for introspection/tests
        expected_token: ClassVar[str] = token
        upstream_target: ClassVar[str] = target

        def _proxy_request(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items()}
            # OAuth shim: intercept discovery, dynamic registration, authorize, and token exchange
            if handle_oauth_request(self, self.command, self.path, headers, body, token):
                print(f"[AUTH_PROXY] Handled OAuth: {self.command} {self.path}", flush=True)
                return
            if self.command == "OPTIONS":
                self.send_response(204)
                origin = headers.get("Origin", "*")
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Authorization, Content-Type, Accept, User-Agent, X-Requested-With",
                )
                self.send_header("Access-Control-Max-Age", "86400")
                self.end_headers()
                return
            if not check_auth(headers, token):
                print(f"[AUTH_PROXY] 401 Unauthorized: {self.command} {self.path}", flush=True)
                _send_unauthorized(self)
                return
            if not check_origin(headers, _allowed_origins()):
                print(f"[AUTH_PROXY] 403 Forbidden Origin '{headers.get('Origin')}' for {self.path}", flush=True)
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden origin"}')
                return

            # If tools/call query in cpu-only mode without explicit rerank, default to rerank=False for sub-second response
            retrieval_mode = os.getenv("RETRIEVAL_MODE", "cpu-only").lower()
            if retrieval_mode == "cpu-only" and self.command == "POST" and self.path.startswith("/mcp") and body:
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if (
                        payload.get("method") == "tools/call"
                        and payload.get("params", {}).get("name") == "query"
                    ):
                        args = payload.setdefault("params", {}).setdefault("arguments", {})
                        if "rerank" not in args:
                            args["rerank"] = False
                            body = json.dumps(payload).encode("utf-8")
                except Exception:
                    pass

            url = target + self.path
            # Preserve verbatim method via self.command; body only if present
            data = body if body else None
            req = urllib.request.Request(url, data=data, method=self.command)
            for k, v in self.headers.items():
                if k.lower() not in ("host", "content-length"):
                    req.add_header(k, v)

            # Ensure Accept header includes both application/json and text/event-stream
            # to satisfy QMD MCP server transport requirement (#881 / MCP 2024-11-05).
            accept_val = req.get_header("Accept", "")
            if not accept_val or accept_val == "*/*":
                req.headers["Accept"] = "application/json, text/event-stream"
            elif "text/event-stream" not in accept_val:
                req.headers["Accept"] = f"{accept_val}, text/event-stream"

            try:
                try:
                    resp_cm = urllib.request.urlopen(req)
                except (urllib.error.URLError, TimeoutError) as conn_err:
                    # Fallback between 127.0.0.1 and localhost if IPv4/IPv6 loopback differs
                    fallback_url = None
                    if "127.0.0.1" in url:
                        fallback_url = url.replace("127.0.0.1", "localhost")
                    elif "localhost" in url:
                        fallback_url = url.replace("localhost", "127.0.0.1")
                    if fallback_url:
                        fallback_req = urllib.request.Request(
                            fallback_url, data=data, method=self.command, headers=req.headers
                        )
                        resp_cm = urllib.request.urlopen(fallback_req)
                    else:
                        raise conn_err

                with resp_cm as resp:
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    # Strip hop-by-hop headers to prevent protocol breakage (e.g. dechunked body with chunked header)
                    for k, v in resp.headers.items():
                        if k.lower() not in _HOP_BY_HOP and k.lower() != "content-length":
                            self.send_header(k, v)
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.end_headers()
                    self.wfile.write(resp_body)
                    print(f"[AUTH_PROXY] 200 Forwarded {self.command} {self.path} ({len(resp_body)} bytes)", flush=True)
            except urllib.error.HTTPError as e:
                # Forward upstream error verbatim — status/headers/body, stripping hop-by-hop headers
                err_body = e.read() if hasattr(e, "read") else b""
                self.send_response(e.code)
                if e.headers is not None:
                    for k, v in e.headers.items():
                        if k.lower() not in _HOP_BY_HOP and k.lower() != "content-length":
                            self.send_header(k, v)
                else:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_body)))
                self.end_headers()
                self.wfile.write(err_body)
                print(f"[AUTH_PROXY] Upstream {e.code} for {self.command} {self.path}", flush=True)
            except Exception as e:
                logger.exception("Proxy upstream forwarding error")
                err_bytes = json.dumps({"error": f"Bad Gateway: {e}"}).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_bytes)))
                self.end_headers()
                self.wfile.write(err_bytes)
                print(f"[AUTH_PROXY] 502 Bad Gateway for {self.command} {self.path}: {e}", flush=True)

        # Verb-preserving: each HTTP verb delegates to _proxy_request
        def do_GET(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_POST(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_PUT(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_DELETE(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_PATCH(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_HEAD(self) -> None:  # noqa: N802
            self._proxy_request()

        def log_message(self, format: str, *args: object) -> None:
            sys.stderr.write(
                "%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), format % args)
            )

    return Handler


def main() -> None:
    _load_dotenv()
    token = os.environ.get("AUTH_PROXY_TOKEN", "")
    if not token:
        if os.environ.get("ALLOW_INSECURE_DEFAULT"):
            token = "secret123"
            print("WARNING: AUTH_PROXY_TOKEN not set — using insecure default secret123 (ALLOW_INSECURE_DEFAULT=1).", file=sys.stderr)
        else:
            print(
                "ERROR: AUTH_PROXY_TOKEN not set — fail-closed. Set AUTH_PROXY_TOKEN or ALLOW_INSECURE_DEFAULT=1 for local smoke.",
                file=sys.stderr,
            )
            # Fail-closed: use placeholder that never matches, so every request 401
            token = "__UNSET_AUTH_PROXY_TOKEN__"

    target = os.environ.get("QMD_TARGET", "http://localhost:8181")
    listen_port = int(os.environ.get("PROXY_PORT", "3210"))
    if _allowed_origins() == ("*",):
        print(
            "WARNING: QMD_ALLOWED_ORIGINS=* — Origin passthrough (fail-open). "
            "Set QMD_ALLOWED_ORIGINS=https://claude.ai to 403 spoofed Origins in proxy.",
            file=sys.stderr,
        )

    handler_cls = make_handler(token, target)
    print(f"Auth Proxy listening on 127.0.0.1:{listen_port} -> {target}")
    print(
        'Smoke: curl -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer $AUTH_PROXY_TOKEN" '
        '-d \'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\''
    )
    try:
        server = ThreadingHTTPServer(("127.0.0.1", listen_port), handler_cls)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)


if __name__ == "__main__":
    main()


