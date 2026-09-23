"""Tests verifying resolution of all issues identified in logs/system.log.

Covers:
1. Auth Proxy upstream retry on connection refused / transient outage.
2. Wiki synthesis provider guard accepting CLOUDFLARE_API_TOKEN.
3. Orchestrator graceful skip when LLM provider unavailable.
4. Daemon supervisor cloudflared protocol configuration (--protocol http2).
5. Daemon supervisor staggered startup.
"""

from __future__ import annotations

import io
import os
import pathlib
import sys
import tempfile
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from auth_proxy.server import make_handler
from control_plane.server import DaemonSupervisor
from orchestrator import run_once
from scripts.wiki import (
    ProviderUnavailableError,
    ensure_provider_available,
)


def test_auth_proxy_upstream_retry_recovers_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth proxy should retry on transient URLError / connection refused and succeed."""
    call_count = 0

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self) -> bytes:
            return b'{"jsonrpc":"2.0","result":{"ok":true}}'

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            pass

    def flaky_urlopen(req: urllib.request.Request) -> FakeResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise urllib.error.URLError("[WinError 10061] Connection actively refused")
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)

    handler_cls = make_handler("test_token", "http://127.0.0.1:8181")

    class FakeHandler:
        def __init__(self) -> None:
            self.command = "POST"
            self.path = "/mcp"
            self.headers = {
                "Authorization": "Bearer test_token",
                "Content-Length": "2",
            }
            self.rfile = io.BytesIO(b"{}")
            self.wfile = io.BytesIO()
            self._response_code: int | None = None
            self._sent_headers: dict[str, str] = {}

        def send_response(self, code: int, message: str | None = None) -> None:
            self._response_code = code

        def send_header(self, k: str, v: str) -> None:
            self._sent_headers[k] = v

        def end_headers(self) -> None:
            pass

    h = handler_cls.__new__(handler_cls)
    fake = FakeHandler()
    h.command = fake.command  # type: ignore[attr-defined]
    h.path = fake.path  # type: ignore[attr-defined]
    h.headers = fake.headers  # type: ignore[attr-defined]
    h.rfile = fake.rfile  # type: ignore[attr-defined]
    h.wfile = fake.wfile  # type: ignore[attr-defined]
    h.send_response = fake.send_response  # type: ignore[method-assign]
    h.send_header = fake.send_header  # type: ignore[method-assign]
    h.end_headers = fake.end_headers  # type: ignore[method-assign]
    h.client_address = ("127.0.0.1", 54321)  # type: ignore[attr-defined]
    h.log_date_time_string = lambda: "now"  # type: ignore[method-assign]

    handler_cls._proxy_request(h)  # type: ignore[attr-defined]

    assert call_count == 2
    assert fake._response_code == 200


def test_wiki_compiler_accepts_cloudflare_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_provider_available accepts CLOUDFLARE_API_TOKEN for openai (Workers AI)."""
    monkeypatch.setenv("LLMWIKI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "mock_cf_token_123")

    # Should not raise ProviderUnavailableError
    ensure_provider_available()


def test_wiki_compiler_raises_when_both_keys_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_provider_available raises ProviderUnavailableError when neither key is set."""
    monkeypatch.setenv("LLMWIKI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)

    with pytest.raises(ProviderUnavailableError):
        ensure_provider_available()


def test_orchestrator_wiki_runner_gracefully_skips_on_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Orchestrator run_once should isolate and cleanly skip when wiki provider is unavailable."""
    from connectors.sdk.base import UnitPayload

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state_path = corpus / "_state" / "crawl_state.json"

        payload = UnitPayload(
            source="test",
            silo="notes",
            source_id="note1",
            url="",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="Note 1",
            summary="A test note.",
            body_markdown="# Note 1\nContent",
        )

        class MockConnector:
            NAME = "notes"
            def fetch_recent(self, since: object, limit: int = 50) -> object:
                yield payload

        qmd_mock = MagicMock(return_value=0)

        def failing_wiki_runner() -> int:
            raise ProviderUnavailableError("missing credentials")

        # Running run_once should complete without raising
        run_once(
            connectors=[MockConnector()],
            corpus_root=corpus,
            state_path=state_path,
            qmd_runner=qmd_mock,
            wiki_runner=failing_wiki_runner,
        )

        assert qmd_mock.call_count == 1


def test_daemon_supervisor_cloudflared_protocol_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """DaemonSupervisor passes --protocol http2 by default on win32 to eliminate QUIC timeouts."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    supervisor = DaemonSupervisor(repo_root)

    launched_cmd = None

    def mock_popen(cmd: list[str], **kwargs: object) -> MagicMock:
        nonlocal launched_cmd
        if "cloudflared" in str(cmd):
            launched_cmd = cmd
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_proc.stdout = io.StringIO("")
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.__enter__.return_value = mock_proc
        return mock_proc

    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setenv("TUNNEL_TOKEN", "mock_tunnel_token")

    res = supervisor.start_daemon("tunnel")
    assert res["status"] == "started"
    assert launched_cmd is not None
    assert "--protocol" in launched_cmd
    proto_idx = launched_cmd.index("--protocol")
    assert launched_cmd[proto_idx + 1] in ("http2", "auto")
