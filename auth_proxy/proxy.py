"""Auth Proxy — shared-secret Bearer token gate between Cloudflare Tunnel and QMD HTTP MCP.

Per research #4 + spec.md:128-131 + CONTEXT.md:53:
- Listens where tunnel ingress points (e.g. localhost:3210), forwards to QMD at 8181 if authorized
- Checks `Authorization: Bearer <AUTH_PROXY_TOKEN>` via constant-time compare
- Returns 401 on missing/wrong, 200 + forward on correct, forwards Origin verbatim
- Preserves method/path/body verbatim; for production we simulate via ProxyApp

This is the production implementation for #18 — previously prototyped as 095fffa, now promoted.

Library only — runnable server lives in auth_proxy/server.py + auth_proxy/__main__.py
(per Divergent Change fix: library vs deployment in one file).
"""

from __future__ import annotations

import hmac
from typing import Callable, Dict, Tuple

# Single source of truth for 401 — fixes Duplicated Code smell
_UNAUTHORIZED_BODY: bytes = b'{"error": "Unauthorized"}'
_UNAUTHORIZED_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def unauthorized_response() -> Tuple[int, Dict[str, str], bytes]:
    """Single helper for 401 plain (not WWW-Authenticate: Bearer resource_metadata)."""
    return 401, dict(_UNAUTHORIZED_HEADERS), _UNAUTHORIZED_BODY


def _get_auth_header(headers: Dict[str, str]) -> str:
    """Case-insensitive lookup per RFC 7230 — HTTP headers are case-insensitive."""
    for k, v in headers.items():
        if k.lower() == "authorization":
            return v if isinstance(v, str) else ""
    return ""


def check_auth(headers: Dict[str, str], expected_token: str) -> bool:
    """Check Authorization header against expected token.

    Requires exact `Bearer <token>` (case-sensitive Bearer, single space).
    Uses constant-time compare. Rejects empty expected_token to avoid
    `Bearer ` == "" bypass via compare_digest("", "").
    """
    if not expected_token:
        return False
    # case-insensitive header name, strict value check
    auth = _get_auth_header(headers)
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:]
    # Spec is strict: single space, no trim of token — trailing spaces fail compare
    return hmac.compare_digest(token, expected_token)


class ProxyApp:
    """Minimal proxy app for TDD — handle() simulates HTTP without network."""

    def __init__(self, expected_token: str, qmd_handler: Callable[..., Tuple[int, Dict[str, str], bytes]]) -> None:
        if not expected_token:
            raise ValueError("expected_token must not be empty")
        if not callable(qmd_handler):
            raise TypeError("qmd_handler must be callable")
        self.expected_token = expected_token
        self.qmd_handler = qmd_handler

    def handle(
        self, method: str, path: str, headers: Dict[str, str], body: bytes
    ) -> Tuple[int, Dict[str, str], bytes]:
        if not check_auth(headers, self.expected_token):
            return unauthorized_response()
        return self.qmd_handler(method, path, headers, body)


def create_proxy_app(
    expected_token: str, qmd_handler: Callable[..., Tuple[int, Dict[str, str], bytes]]
) -> ProxyApp:
    """Factory with validation — not a pure delegation (fixes Middle Man)."""
    if not expected_token:
        raise ValueError("expected_token must not be empty — set AUTH_PROXY_TOKEN")
    if not callable(qmd_handler):
        raise TypeError("qmd_handler must be callable")
    return ProxyApp(expected_token, qmd_handler)


# Back-compat: `python -m auth_proxy.proxy` still works (delegates to server.main)
# New canonical is `python -m auth_proxy`
if __name__ == "__main__":
    from auth_proxy.server import main

    main()
