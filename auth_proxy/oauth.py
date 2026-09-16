"""OAuth 2.0 / MCP Remote Authorization shim for Claude.ai and other OAuth clients.

Per Issue #25 + RFC 8414 + RFC 9728 + RFC 7591 + RFC 7636.
Enables Claude.ai web custom connector to authenticate via standard OAuth 2.1
Dynamic Client Registration and PKCE authorization code exchange, issuing the
master AUTH_PROXY_TOKEN as the Bearer access token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _compute_s256(verifier: str) -> str:
    """RFC 7636 S256: BASE64URL-ENCODE(SHA256(ASCII(code_verifier))) without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """Verify code_verifier against code_challenge using S256 (constant-time)."""
    if not code_verifier or not code_challenge:
        return False
    computed = _compute_s256(code_verifier)
    return hmac.compare_digest(computed, code_challenge.rstrip("="))


class OAuthStore:
    """In-memory store for registered clients and authorization codes."""

    def __init__(self) -> None:
        self.clients: Dict[str, Dict[str, Any]] = {}
        self.codes: Dict[str, Dict[str, Any]] = {}
        self.refresh_tokens: Dict[str, Dict[str, Any]] = {}

    def register_client(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a client dynamically (RFC 7591)."""
        client_id = f"client_{secrets.token_hex(16)}"
        client_secret = secrets.token_urlsafe(32)
        redirect_uris = data.get("redirect_uris", [])
        if isinstance(redirect_uris, str):
            redirect_uris = [redirect_uris]
        client_name = data.get("client_name", "Claude")

        client_record = {
            "client_id": client_id,
            "client_secret": client_secret,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": data.get("token_endpoint_auth_method", "none"),
            "created_at": time.time(),
        }
        self.clients[client_id] = client_record
        return client_record

    def create_authorization_code(
        self,
        client_id: str,
        redirect_uri: str,
        code_challenge: str = "",
        code_challenge_method: str = "S256",
        ttl_seconds: int = 600,
    ) -> str:
        """Create a one-time authorization code."""
        code = f"code_{secrets.token_urlsafe(32)}"
        self.codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "expires_at": time.time() + ttl_seconds,
        }
        return code

    def validate_and_consume_code(
        self,
        code: str,
        code_verifier: str = "",
        redirect_uri: str = "",
    ) -> Tuple[bool, str]:
        """Validate authorization code and PKCE challenge, consuming code on success."""
        record = self.codes.pop(code, None)
        if not record:
            return False, "Invalid or already used authorization code"
        if time.time() > record["expires_at"]:
            return False, "Authorization code has expired"

        expected_redirect = record.get("redirect_uri")
        if expected_redirect and redirect_uri and expected_redirect != redirect_uri:
            # Tolerant match if redirect_uri matches base
            if not redirect_uri.startswith(expected_redirect.split("?")[0]):
                return False, "redirect_uri mismatch"

        challenge = record.get("code_challenge", "")
        if challenge:
            if not code_verifier:
                return False, "code_verifier required for PKCE challenge"
            if not verify_pkce(code_verifier, challenge):
                return False, "PKCE verification failed"

        return True, ""


# Singleton store for the proxy instance
_STORE = OAuthStore()


def get_oauth_store() -> OAuthStore:
    return _STORE


def get_issuer(headers: Dict[str, str]) -> str:
    """Determine the canonical public issuer URL."""
    tunnel_url = os.environ.get("TUNNEL_URL", "").strip()
    if tunnel_url:
        parsed = urllib.parse.urlparse(tunnel_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    host = headers.get("Host", "127.0.0.1:3210")
    proto = headers.get("X-Forwarded-Proto")
    if not proto:
        proto = "https" if ("." in host and not host.startswith("127.")) else "http"
    return f"{proto}://{host}"


def get_protected_resource_metadata(issuer: str) -> Dict[str, Any]:
    """RFC 9728 OAuth 2.0 Protected Resource Metadata."""
    return {
        "resource": f"{issuer}/mcp",
        "authorization_servers": [issuer],
        "scopes_supported": ["mcp"],
    }


def get_authorization_server_metadata(issuer: str) -> Dict[str, Any]:
    """RFC 8414 OAuth 2.0 Authorization Server Metadata."""
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "scopes_supported": ["mcp"],
    }


def handle_oauth_request(
    handler: BaseHTTPRequestHandler,
    method: str,
    path: str,
    headers: Dict[str, str],
    body: bytes,
    expected_token: str,
    store: Optional[OAuthStore] = None,
) -> bool:
    """Handle OAuth discovery, registration, authorization, and token requests.

    Returns True if the request was handled; False if it should be proxied to QMD.
    """
    if store is None:
        store = _STORE

    parsed_url = urllib.parse.urlparse(path)
    clean_path = parsed_url.path.rstrip("/")
    issuer = get_issuer(headers)

    # 1. CORS Preflight for OAuth endpoints
    if method == "OPTIONS":
        if clean_path in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-authorization-server",
            "/register",
            "/oauth/register",
            "/oauth/token",
            "/oauth/authorize",
        ):
            handler.send_response(204)
            origin = headers.get("Origin", "*")
            handler.send_header("Access-Control-Allow-Origin", origin)
            handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            handler.send_header(
                "Access-Control-Allow-Headers",
                "Authorization, Content-Type, Accept, User-Agent, X-Requested-With",
            )
            handler.send_header("Access-Control-Max-Age", "86400")
            handler.end_headers()
            return True

    # Helper for sending JSON
    def send_json(code: int, data: Dict[str, Any]) -> None:
        payload = json.dumps(data).encode("utf-8")
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Access-Control-Allow-Origin", headers.get("Origin", "*"))
        handler.end_headers()
        handler.wfile.write(payload)

    # 2. RFC 9728 Protected Resource Metadata
    if clean_path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        if method == "GET":
            send_json(200, get_protected_resource_metadata(issuer))
            return True

    # 3. RFC 8414 Authorization Server Metadata
    if clean_path == "/.well-known/oauth-authorization-server":
        if method == "GET":
            send_json(200, get_authorization_server_metadata(issuer))
            return True

    # 4. RFC 7591 Dynamic Client Registration
    if clean_path in ("/register", "/oauth/register"):
        if method == "POST":
            try:
                data = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                data = {}
            client_record = store.register_client(data)
            send_json(201, client_record)
            return True

    # 5. OAuth Authorization Endpoint (GET /oauth/authorize)
    if clean_path == "/oauth/authorize":
        query_params = urllib.parse.parse_qs(parsed_url.query)
        client_id = query_params.get("client_id", [""])[0]
        redirect_uri = query_params.get("redirect_uri", [""])[0]
        code_challenge = query_params.get("code_challenge", [""])[0]
        code_challenge_method = query_params.get("code_challenge_method", ["S256"])[0]
        state = query_params.get("state", [""])[0]

        if not redirect_uri:
            send_json(400, {"error": "invalid_request", "error_description": "Missing redirect_uri"})
            return True

        # Generate authorization code
        auth_code = store.create_authorization_code(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

        # Build redirect URL with code and state
        redirect_parts = urllib.parse.urlparse(redirect_uri)
        existing_params = urllib.parse.parse_qs(redirect_parts.query)
        existing_params["code"] = [auth_code]
        if state:
            existing_params["state"] = [state]
        new_query = urllib.parse.urlencode(existing_params, doseq=True)
        final_redirect = urllib.parse.urlunparse(
            (
                redirect_parts.scheme,
                redirect_parts.netloc,
                redirect_parts.path,
                redirect_parts.params,
                new_query,
                redirect_parts.fragment,
            )
        )

        # Send HTTP 302 Found redirect
        handler.send_response(302)
        handler.send_header("Location", final_redirect)
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        return True

    # 6. OAuth Token Endpoint (POST /oauth/token)
    if clean_path == "/oauth/token":
        if method == "POST":
            content_type = headers.get("Content-Type", "")
            params: Dict[str, str] = {}
            if "json" in content_type:
                try:
                    params = json.loads(body.decode("utf-8"))
                except Exception:
                    params = {}
            else:
                try:
                    raw_params = urllib.parse.parse_qs(body.decode("utf-8"))
                    params = {k: v[0] for k, v in raw_params.items() if v}
                except Exception:
                    params = {}

            grant_type = params.get("grant_type", "authorization_code")
            if grant_type == "authorization_code":
                code = params.get("code", "")
                code_verifier = params.get("code_verifier", "")
                redirect_uri = params.get("redirect_uri", "")
                ok, err_msg = store.validate_and_consume_code(code, code_verifier, redirect_uri)
                if not ok:
                    send_json(400, {"error": "invalid_grant", "error_description": err_msg})
                    return True

                send_json(
                    200,
                    {
                        "access_token": expected_token,
                        "token_type": "Bearer",
                        "expires_in": 31536000,
                        "refresh_token": f"refresh_{secrets.token_urlsafe(32)}",
                        "scope": "mcp",
                    },
                )
                return True

            if grant_type == "refresh_token":
                send_json(
                    200,
                    {
                        "access_token": expected_token,
                        "token_type": "Bearer",
                        "expires_in": 31536000,
                        "refresh_token": f"refresh_{secrets.token_urlsafe(32)}",
                        "scope": "mcp",
                    },
                )
                return True

            send_json(400, {"error": "unsupported_grant_type"})
            return True

    return False
