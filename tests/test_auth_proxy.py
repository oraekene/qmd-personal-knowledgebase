import pathlib

# Seam: Auth Proxy HTTP boundary — correct token passes, wrong/missing 401 (spec Testing Decisions)
# Thin boundary smoke tests per t11_body.md and research #4


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

    # Bearer is case-sensitive per spec, token is constant-time compare
    headers = {"Authorization": "Bearer Secret123"}
    assert check_auth(headers, "secret123") is False


def test_check_auth_bearer_prefix_required():
    from auth_proxy.proxy import check_auth

    headers = {"Authorization": "secret123"}  # no Bearer
    assert check_auth(headers, "secret123") is False
    headers2 = {"Authorization": "Basic secret123"}
    assert check_auth(headers2, "secret123") is False


def test_proxy_forwards_when_authorized(tmp_path):
    # Integration: proxy should forward to fake QMD backend when authorized
    # We test via function that would proxy, not full HTTP server, to keep TDD fast
    from auth_proxy.proxy import create_proxy_app

    # Fake QMD backend that returns tools/list
    def fake_qmd_handler(method, path, headers, body):
        return 200, {"Content-Type": "application/json"}, b'{"tools": [{"name": "qmd_query"}]}'

    app = create_proxy_app(expected_token="secret123", qmd_handler=fake_qmd_handler)
    # Simulate authorized request
    status, headers, body = app.handle("POST", "/mcp", {"Authorization": "Bearer secret123"}, b'{"jsonrpc":"2.0","method":"tools/list"}')
    assert status == 200
    assert b"qmd_query" in body
    # Wrong token should not forward
    status2, _, _ = app.handle("POST", "/mcp", {"Authorization": "Bearer wrong"}, b'{}')
    assert status2 == 401
    # Missing token
    status3, _, _ = app.handle("POST", "/mcp", {}, b'{}')
    assert status3 == 401
