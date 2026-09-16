"""Unit tests for OAuth 2.0 Dynamic Client Registration and Authorization shim (#25)."""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.parse
from io import BytesIO
from unittest.mock import Mock

import pytest

from auth_proxy.oauth import (
    OAuthStore,
    _compute_s256,
    get_authorization_server_metadata,
    get_protected_resource_metadata,
    handle_oauth_request,
    verify_pkce,
)
from auth_proxy.server import make_handler


def test_pkce_verification():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = _compute_s256(verifier)
    assert verify_pkce(verifier, challenge) is True
    assert verify_pkce("wrong_verifier", challenge) is False
    assert verify_pkce("", challenge) is False
    assert verify_pkce(verifier, "") is False


def test_oauth_store_lifecycle():
    store = OAuthStore()
    client = store.register_client({"client_name": "Claude", "redirect_uris": ["https://claude.ai/oauth"]})
    assert client["client_id"].startswith("client_")
    assert client["client_name"] == "Claude"

    verifier = "test-verifier-1234567890-abcdefghijklmnop"
    challenge = _compute_s256(verifier)
    code = store.create_authorization_code(
        client_id=client["client_id"],
        redirect_uri="https://claude.ai/oauth",
        code_challenge=challenge,
    )
    assert code.startswith("code_")

    # Mismatched verifier fails
    ok, err = store.validate_and_consume_code(code, code_verifier="wrong", redirect_uri="https://claude.ai/oauth")
    assert ok is False
    assert "PKCE" in err

    # Recreate code and test successful consumption
    code2 = store.create_authorization_code(
        client_id=client["client_id"],
        redirect_uri="https://claude.ai/oauth",
        code_challenge=challenge,
    )
    ok2, err2 = store.validate_and_consume_code(code2, code_verifier=verifier, redirect_uri="https://claude.ai/oauth")
    assert ok2 is True
    assert err2 == ""

    # Reusing consumed code fails
    ok3, _ = store.validate_and_consume_code(code2, code_verifier=verifier, redirect_uri="https://claude.ai/oauth")
    assert ok3 is False


def test_protected_resource_metadata():
    meta = get_protected_resource_metadata("https://kb.example.com")
    assert meta["resource"] == "https://kb.example.com/mcp"
    assert meta["authorization_servers"] == ["https://kb.example.com"]


def test_authorization_server_metadata():
    meta = get_authorization_server_metadata("https://kb.example.com")
    assert meta["issuer"] == "https://kb.example.com"
    assert meta["authorization_endpoint"] == "https://kb.example.com/oauth/authorize"
    assert meta["token_endpoint"] == "https://kb.example.com/oauth/token"
    assert meta["registration_endpoint"] == "https://kb.example.com/register"
    assert "S256" in meta["code_challenge_methods_supported"]


class DummyHandler:
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.response_code = 0
        self.sent_headers = {}
        self.wfile = BytesIO()

    def send_response(self, code):
        self.response_code = code

    def send_header(self, k, v):
        self.sent_headers[k] = v

    def end_headers(self):
        pass


def test_handle_oauth_discovery():
    store = OAuthStore()
    handler = DummyHandler({"Host": "kb.example.com"})
    handled = handle_oauth_request(
        handler, "GET", "/.well-known/oauth-authorization-server", {"Host": "kb.example.com"}, b"", "secret123", store
    )
    assert handled is True
    assert handler.response_code == 200
    assert handler.sent_headers["Content-Type"] == "application/json"
    data = json.loads(handler.wfile.getvalue().decode())
    assert data["issuer"] == "https://kb.example.com"


def test_handle_oauth_dynamic_registration():
    store = OAuthStore()
    handler = DummyHandler({"Host": "kb.example.com"})
    body = json.dumps({"client_name": "Claude", "redirect_uris": ["https://claude.ai/callback"]}).encode()
    handled = handle_oauth_request(
        handler, "POST", "/register", {"Host": "kb.example.com", "Content-Type": "application/json"}, body, "secret123", store
    )
    assert handled is True
    assert handler.response_code == 201
    data = json.loads(handler.wfile.getvalue().decode())
    assert data["client_id"].startswith("client_")
    assert data["client_name"] == "Claude"


def test_handle_oauth_authorize_and_token_exchange():
    store = OAuthStore()
    expected_token = "my_secret_token_456"

    verifier = "sample-verifier-string-1234567890123456"
    challenge = _compute_s256(verifier)

    # 1. Authorize
    auth_handler = DummyHandler({"Host": "kb.example.com"})
    auth_path = f"/oauth/authorize?response_type=code&client_id=client_1&redirect_uri=https://claude.ai/cb&code_challenge={challenge}&state=xyz123"
    handled_auth = handle_oauth_request(
        auth_handler, "GET", auth_path, {"Host": "kb.example.com"}, b"", expected_token, store
    )
    assert handled_auth is True
    assert auth_handler.response_code == 302
    location = auth_handler.sent_headers["Location"]
    assert location.startswith("https://claude.ai/cb?")
    assert "state=xyz123" in location

    # Extract code
    parsed_loc = urllib.parse.urlparse(location)
    code = urllib.parse.parse_qs(parsed_loc.query)["code"][0]

    # 2. Token exchange with PKCE
    token_handler = DummyHandler({"Host": "kb.example.com"})
    token_body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://claude.ai/cb",
        "code_verifier": verifier,
    }).encode()

    handled_token = handle_oauth_request(
        token_handler,
        "POST",
        "/oauth/token",
        {"Host": "kb.example.com", "Content-Type": "application/x-www-form-urlencoded"},
        token_body,
        expected_token,
        store,
    )
    assert handled_token is True
    assert token_handler.response_code == 200
    token_data = json.loads(token_handler.wfile.getvalue().decode())
    assert token_data["access_token"] == expected_token
    assert token_data["token_type"] == "Bearer"


def test_cors_preflight_for_oauth():
    store = OAuthStore()
    handler = DummyHandler({"Host": "kb.example.com", "Origin": "https://claude.ai"})
    handled = handle_oauth_request(
        handler, "OPTIONS", "/register", {"Host": "kb.example.com", "Origin": "https://claude.ai"}, b"", "secret123", store
    )
    assert handled is True
    assert handler.response_code == 204
    assert handler.sent_headers["Access-Control-Allow-Origin"] == "https://claude.ai"
