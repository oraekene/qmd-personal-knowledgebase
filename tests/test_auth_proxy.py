import pathlib

# Seam: Auth Proxy HTTP boundary — correct token passes, wrong/missing 401, constant-time, forward verbatim
# Per #18 + research #4 + spec.md:128-131 + #12 prototype 095fffa


def test_check_auth_correct_token_passes():
    from auth_proxy.proxy import check_auth

    headers = {"Authorization": "Bearer secret123"}
    assert check_auth(headers, "secret123") is True


def test_check_auth_wrong_token_rejected():
    from auth_proxy.proxy import check_auth

    headers = {"Authorization": "Bearer wrong"}
    assert check_auth(headers, "secret123") is False


def test_check_auth_missing_header_rejected():
    from auth_proxy.proxy import check_auth

    headers = {}
    assert check_auth(headers, "secret123") is False


def test_check_auth_case_sensitive():
    from auth_proxy.proxy import check_auth

    headers = {"Authorization": "Bearer Secret123"}
    assert check_auth(headers, "secret123") is False


def test_check_auth_bearer_prefix_required():
    from auth_proxy.proxy import check_auth

    headers = {"Authorization": "secret123"}
    assert check_auth(headers, "secret123") is False
    headers2 = {"Authorization": "Basic secret123"}
    assert check_auth(headers2, "secret123") is False


def test_proxy_forwards_when_authorized(tmp_path):
    from auth_proxy.proxy import create_proxy_app

    def fake_qmd_handler(method, path, headers, body):
        return 200, {"Content-Type": "application/json"}, b'{"tools": [{"name": "qmd_query"}]}'

    app = create_proxy_app(expected_token="secret123", qmd_handler=fake_qmd_handler)
    status, headers, body = app.handle("POST", "/mcp", {"Authorization": "Bearer secret123"}, b'{"jsonrpc":"2.0","method":"tools/list"}')
    assert status == 200
    assert b"qmd_query" in body
    status2, _, _ = app.handle("POST", "/mcp", {"Authorization": "Bearer wrong"}, b'{}')
    assert status2 == 401
    status3, _, _ = app.handle("POST", "/mcp", {}, b'{}')
    assert status3 == 401


def test_proxy_origin_allowlist_via_qmd():
    """QMD's origin guard should allow https://claude.ai when behind proxy (QMD_ALLOWED_ORIGINS=*).

    This test verifies the proxy does not interfere with Origin header — it forwards verbatim,
    and QMD's own guard (tested in qmd-main) handles allowlist. Here we just check proxy forwards Origin.
    """
    from auth_proxy.proxy import create_proxy_app

    captured = {}

    def fake_qmd(method, path, headers, body):
        captured["headers"] = headers
        return 200, {}, b'ok'

    app = create_proxy_app(expected_token="secret123", qmd_handler=fake_qmd)
    app.handle("POST", "/mcp", {"Authorization": "Bearer secret123", "Origin": "https://claude.ai"}, b'{}')
    assert captured["headers"]["Origin"] == "https://claude.ai"
    # Also test attacker Origin is forwarded (QMD will reject 403, proxy should not block)
    app.handle("POST", "/mcp", {"Authorization": "Bearer secret123", "Origin": "https://attacker.example"}, b'{}')
    assert captured["headers"]["Origin"] == "https://attacker.example"
