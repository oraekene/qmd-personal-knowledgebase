"""Auth Proxy HTTP server — runnable side of the split (fixes Divergent Change).

Listens on 127.0.0.1:3210, forwards verbatim to QMD at 127.0.0.1:8181 if authorized.
Preserves method/path/body/headers verbatim; on upstream HTTPError forwards
status/headers/body verbatim (no forced Content-Type overwrite).

Per #18 + spec.md:128-131 + research #4.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

from auth_proxy.proxy import _UNAUTHORIZED_BODY, _UNAUTHORIZED_HEADERS, check_auth


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
            if not check_auth(headers, token):
                _send_unauthorized(self)
                return
            url = target + self.path
            # Preserve verbatim method via self.command; body only if present
            data = body if body else None
            req = urllib.request.Request(url, data=data, method=self.command)
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
                # Forward upstream error verbatim — status/headers/body
                self.send_response(e.code)
                # e.headers is http.client.HTTPMessage — forward as-is
                if e.headers is not None:
                    for k, v in e.headers.items():
                        self.send_header(k, v)
                else:
                    self.send_header("Content-Type", "application/json")
                self.end_headers()
                try:
                    self.wfile.write(e.read())
                except Exception:
                    self.wfile.write(b"")
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(f'{{"error": "Bad Gateway: {e}"}}'.encode())

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

    target = os.environ.get("QMD_TARGET", "http://127.0.0.1:8181")
    listen_port = int(os.environ.get("PROXY_PORT", "3210"))

    handler_cls = make_handler(token, target)
    print(f"Auth Proxy listening on 127.0.0.1:{listen_port} -> {target}")
    print(
        'Smoke: curl -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer $AUTH_PROXY_TOKEN" '
        '-d \'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\''
    )
    try:
        HTTPServer(("127.0.0.1", listen_port), handler_cls).serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)


if __name__ == "__main__":
    main()
