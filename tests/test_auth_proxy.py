# Seam: Auth Proxy HTTP boundary — correct token passes, wrong/missing 401, constant-time, forward verbatim
# Per #18 + research #4 + spec.md:128-131 + #12 prototype 095fffa
from __future__ import annotations

import pytest

from auth_proxy.proxy import ProxyApp, check_auth, create_proxy_app, unauthorized_response
from auth_proxy.server import _send_unauthorized, make_handler


def test_check_auth_correct_token_passes() -> None:
    headers = {"Authorization": "Bearer secret123"}
    assert check_auth(headers, "secret123") is True


def test_check_auth_wrong_token_rejected() -> None:
    headers = {"Authorization": "Bearer wrong"}
    assert check_auth(headers, "secret123") is False


def test_check_auth_missing_header_rejected() -> None:
    headers: dict[str, str] = {}
    assert check_auth(headers, "secret123") is False


def test_check_auth_case_sensitive() -> None:
    headers = {"Authorization": "Bearer Secret123"}
    assert check_auth(headers, "secret123") is False


def test_check_auth_bearer_prefix_required() -> None:
    headers = {"Authorization": "secret123"}
    assert check_auth(headers, "secret123") is False
    headers2 = {"Authorization": "Basic secret123"}
    assert check_auth(headers2, "secret123") is False


def test_check_auth_lowercase_bearer_rejected() -> None:
    # spec: Bearer is case-sensitive, single space — `bearer` must fail
    assert check_auth({"Authorization": "bearer secret123"}, "secret123") is False


def test_check_auth_double_space_rejected() -> None:
    # "Bearer  secret123" → token is " secret123" (leading space), must fail
    assert check_auth({"Authorization": "Bearer  secret123"}, "secret123") is False


def test_check_auth_trailing_space_rejected() -> None:
    # strict: no trim — "Bearer secret123 " → token "secret123 " != "secret123"
    assert check_auth({"Authorization": "Bearer secret123 "}, "secret123") is False


def test_check_auth_empty_expected_token_rejected() -> None:
    # empty expected_token must never authenticate — avoids `Bearer ` == "" bypass
    assert check_auth({"Authorization": "Bearer "}, "") is False
    assert check_auth({"Authorization": "Bearer anything"}, "") is False
    assert check_auth({}, "") is False


def test_check_auth_empty_bearer_token_rejected() -> None:
    assert check_auth({"Authorization": "Bearer "}, "secret123") is False


def test_check_auth_case_insensitive_header_name() -> None:
    # HTTP headers case-insensitive — all casings must be accepted
    assert check_auth({"authorization": "Bearer secret123"}, "secret123") is True
    assert check_auth({"AUTHORIZATION": "Bearer secret123"}, "secret123") is True
    assert check_auth({"AuThOrIzAtIoN": "Bearer secret123"}, "secret123") is True


def test_unauthorized_response_is_plain_no_www_authenticate() -> None:
    status, headers, body = unauthorized_response()
    assert status == 401
    assert headers == {"Content-Type": "application/json"}
    assert b"Unauthorized" in body
    # Must be plain 401, not WWW-Authenticate: Bearer resource_metadata
    assert "WWW-Authenticate" not in headers


def test_create_proxy_app_validates_empty_token() -> None:
    def fake(_m, _p, _h, _b):  # type: ignore[no-untyped-def]
        return 200, {}, b"ok"

    with pytest.raises(ValueError):
        create_proxy_app("", fake)
    with pytest.raises(ValueError):
        ProxyApp("", fake)
    with pytest.raises(TypeError):
        create_proxy_app("secret123", None)  # type: ignore[arg-type]


def test_proxy_forwards_when_authorized(tmp_path):  # type: ignore[no-untyped-def]
    def fake_qmd_handler(method, path, headers, body):  # type: ignore[no-untyped-def]
        return 200, {"Content-Type": "application/json"}, b'{"tools": [{"name": "qmd_query"}]}'

    app = create_proxy_app(expected_token="secret123", qmd_handler=fake_qmd_handler)
    status, headers, body = app.handle(
        "POST", "/mcp", {"Authorization": "Bearer secret123"}, b'{"jsonrpc":"2.0","method":"tools/list"}'
    )
    assert status == 200
    assert b"qmd_query" in body
    status2, _, _ = app.handle("POST", "/mcp", {"Authorization": "Bearer wrong"}, b"{}")
    assert status2 == 401
    status3, _, _ = app.handle("POST", "/mcp", {}, b"{}")
    assert status3 == 401


def test_proxy_does_not_call_handler_on_401() -> None:
    called: list[bool] = []

    def fake_qmd(method, path, headers, body):  # type: ignore[no-untyped-def]
        called.append(True)
        return 200, {}, b"ok"

    app = create_proxy_app(expected_token="secret123", qmd_handler=fake_qmd)
    status, headers, body = app.handle("POST", "/mcp", {"Authorization": "Bearer wrong"}, b"{}")
    assert status == 401
    assert called == []
    assert "WWW-Authenticate" not in headers
    assert headers["Content-Type"] == "application/json"


def test_proxy_preserves_method_path_body_verbatim() -> None:
    captured: dict[str, object] = {}

    def fake_qmd(method, path, headers, body):  # type: ignore[no-untyped-def]
        captured["method"] = method
        captured["path"] = path
        captured["headers"] = dict(headers)
        captured["body"] = body
        return 200, {"Content-Type": "application/json"}, b'{"ok": true}'

    app = create_proxy_app(expected_token="secret123", qmd_handler=fake_qmd)
    app.handle(
        "GET",
        "/mcp?foo=bar",
        {"Authorization": "Bearer secret123", "Origin": "https://claude.ai", "X-Custom": "1"},
        b"hello",
    )
    assert captured["method"] == "GET"
    assert captured["path"] == "/mcp?foo=bar"
    assert captured["body"] == b"hello"
    assert captured["headers"]["Origin"] == "https://claude.ai"  # type: ignore[index]


def test_proxy_origin_allowlist_via_qmd() -> None:
    """QMD's origin guard should allow https://claude.ai when behind proxy (QMD_ALLOWED_ORIGINS=*).

    This test verifies the proxy does not interfere with Origin header — it forwards verbatim,
    and QMD's own guard (tested in qmd-main) handles allowlist. Here we just check proxy forwards Origin.
    """
    captured: dict[str, object] = {}

    def fake_qmd(method, path, headers, body):  # type: ignore[no-untyped-def]
        captured["headers"] = headers  # type: ignore[assignment]
        return 200, {}, b"ok"

    app = create_proxy_app(expected_token="secret123", qmd_handler=fake_qmd)
    app.handle("POST", "/mcp", {"Authorization": "Bearer secret123", "Origin": "https://claude.ai"}, b"{}")
    assert captured["headers"]["Origin"] == "https://claude.ai"  # type: ignore[index,attr-defined]
    # Attacker Origin is also forwarded verbatim — QMD behind proxy with QMD_ALLOWED_ORIGINS=* will allow it (200).
    # Direct-to-QMD without proxy (allowlist https://claude.ai only) would 403 — see next test.
    captured.clear()
    app.handle("POST", "/mcp", {"Authorization": "Bearer secret123", "Origin": "https://attacker.example"}, b"{}")
    assert captured["headers"]["Origin"] == "https://attacker.example"  # type: ignore[index,attr-defined]


def test_origin_via_proxy_vs_direct_qmd() -> None:
    """Spec AC1: direct curl -H 'Origin: https://attacker.example' to QMD →403, via proxy →200.

    Simulates QMD origin guard: behind proxy QMD_ALLOWED_ORIGINS=* (allow all);
    direct QMD has allowlist https://claude.ai,https://claude.com.
    Proxy must forward Origin verbatim so behavior differs only by QMD config.
    """

    def make_qmd_handler(allowed_origins: str):  # type: ignore[no-untyped-def]
        allowed = [o.strip() for o in allowed_origins.split(",")] if allowed_origins != "*" else ["*"]

        def handler(method, path, headers, body):  # type: ignore[no-untyped-def]
            origin = headers.get("Origin", "")
            if "*" in allowed:
                return 200, {}, b"ok"
            if origin in allowed:
                return 200, {}, b"ok"
            return 403, {}, b"forbidden"

        return handler

    # Via proxy — QMD behind proxy has QMD_ALLOWED_ORIGINS=*
    allowed_qmd_behind_proxy = make_qmd_handler("*")
    app_via_proxy = create_proxy_app(expected_token="secret123", qmd_handler=allowed_qmd_behind_proxy)
    status_ok, _, _ = app_via_proxy.handle(
        "POST", "/mcp", {"Authorization": "Bearer secret123", "Origin": "https://attacker.example"}, b"{}"
    )
    assert status_ok == 200, "attacker via proxy must be 200 when QMD_ALLOWED_ORIGINS=*"
    status_claude, _, _ = app_via_proxy.handle(
        "POST", "/mcp", {"Authorization": "Bearer secret123", "Origin": "https://claude.ai"}, b"{}"
    )
    assert status_claude == 200

    # Direct to QMD — allowlist without *
    direct_qmd = make_qmd_handler("https://claude.ai,https://claude.com")
    status_direct_attacker = direct_qmd("POST", "/mcp", {"Origin": "https://attacker.example"}, b"{}")[0]
    assert status_direct_attacker == 403
    status_direct_claude = direct_qmd("POST", "/mcp", {"Origin": "https://claude.ai"}, b"{}")[0]
    assert status_direct_claude == 200


def test_proxy_401_no_forward_even_with_attacker_origin() -> None:
    """Wrong token must 401 even if Origin is allowed — no forward."""
    called: list[bool] = []

    def fake_qmd(method, path, headers, body):  # type: ignore[no-untyped-def]
        called.append(True)
        return 200, {}, b"ok"

    app = create_proxy_app(expected_token="secret123", qmd_handler=fake_qmd)
    status, _, _ = app.handle(
        "POST", "/mcp", {"Authorization": "Bearer wrong", "Origin": "https://claude.ai"}, b"{}"
    )
    assert status == 401
    assert called == []


def test_server_make_handler_forwards_verb_and_error_verbatim(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Handler must preserve method verbatim and forward upstream HTTPError headers/body verbatim."""
    import io
    import urllib.error
    import urllib.request

    # Mock upstream that returns 403 for attacker Origin when not behind proxy
    def fake_urlopen(req):  # type: ignore[no-untyped-def]
        # Verify method verbatim
        assert req.method == "GET"
        # Verify Origin forwarded verbatim
        assert req.get_header("Origin") == "https://attacker.example"

        # Simulate upstream 403 with custom header/body
        headers = {"Content-Type": "text/plain", "X-Upstream": "1"}
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", headers, io.BytesIO(b"forbidden"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    handler_cls = make_handler("secret123", "http://127.0.0.1:8181")

    # Build a minimal mock handler instance without opening socket
    # We exercise _proxy_request via direct call on a fake self
    import types

    class FakeHandler:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.command = "GET"
            self.path = "/mcp"
            self.headers = {
                "Authorization": "Bearer secret123",
                "Origin": "https://attacker.example",
                "Content-Length": "0",
            }
            self.rfile = io.BytesIO(b"")
            self.wfile = io.BytesIO()
            self._response_code: int | None = None
            self._sent_headers: dict[str, str] = {}

        def send_response(self, code, message=None):  # type: ignore[no-untyped-def]
            self._response_code = code

        def send_header(self, k, v):  # type: ignore[no-untyped-def]
            self._sent_headers[k] = v

        def end_headers(self):  # type: ignore[no-untyped-def]
            pass

    fake = FakeHandler()
    # Bind Handler._proxy_request to fake instance
    # Create instance of Handler without __init__ and call _proxy_request
    h = handler_cls.__new__(handler_cls)
    h.command = fake.command  # type: ignore[attr-defined]
    h.path = fake.path  # type: ignore[attr-defined]
    h.headers = fake.headers  # type: ignore[attr-defined]
    h.rfile = fake.rfile  # type: ignore[attr-defined]
    h.wfile = fake.wfile  # type: ignore[attr-defined]
    h.send_response = fake.send_response  # type: ignore[method-assign]
    h.send_header = fake.send_header  # type: ignore[method-assign]
    h.end_headers = fake.end_headers  # type: ignore[method-assign]
    h.client_address = ("127.0.0.1", 12345)  # type: ignore[attr-defined]
    # Provide required for log_message
    h.log_date_time_string = lambda: "now"  # type: ignore[method-assign]

    # type: ignore[attr-defined] - call private
    handler_cls._proxy_request(h)  # type: ignore[attr-defined]

    assert fake._response_code == 403
    assert fake._sent_headers.get("X-Upstream") == "1"
    assert fake.wfile.getvalue() == b"forbidden"
