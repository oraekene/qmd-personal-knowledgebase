"""Tests for OpenAI-compatible / Cloudflare Workers AI synthesis in scripts/wiki.py (#20)."""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from connectors.sdk.base import UnitPayload
from connectors.sdk.writer import write_unit
from scripts.wiki import (
    ProviderUnavailableError,
    _call_openai_compatible,
    compile_wiki,
)


def _make_unit(silo: str, source_id: str, body: str) -> UnitPayload:
    return UnitPayload(
        source="test",
        silo=silo,
        source_id=source_id,
        url=f"https://example.com/{source_id}",
        created_at="2026-09-01T00:00:00+00:00",
        tags=[],
        author="",
        title=source_id,
        summary="A test unit.",
        body_markdown=f"# {source_id}\n\n{body}",
    )


def test_call_openai_compatible_success():
    fake_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Synthesized concept summary citing ^[notes/sample.md:1-5] and [[MOC]].",
                }
            }
        ]
    }
    resp_bytes = json.dumps(fake_response).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = resp_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = _call_openai_compatible(
            prompt="Summarize this",
            base_url="https://api.cloudflare.com/client/v4/accounts/test_account/ai/v1",
            api_key="secret_token",
            model="@cf/meta/llama-3.1-8b-instruct-fp8-fast",
        )
        assert "Synthesized concept summary" in result
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer secret_token"
        assert req.get_header("Content-type") == "application/json"


def test_call_openai_compatible_http_503_raises_provider_unavailable():
    fp = BytesIO(b'{"error": "Service Temporarily Unavailable"}')
    http_err = urllib.error.HTTPError(
        url="https://api.cloudflare.com/test",
        code=503,
        msg="Service Unavailable",
        hdrs={},
        fp=fp,
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(ProviderUnavailableError) as exc:
            _call_openai_compatible(
                prompt="Summarize",
                base_url="https://api.cloudflare.com/ai/v1",
                api_key="token",
                model="llama-3.1-8b",
            )
        assert "503" in str(exc.value) or "Service" in str(exc.value)


def test_compile_wiki_real_mode_uses_llm():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state = tmp_path / ".llmwiki" / "state.json"

        p = _make_unit("notes", "topic", "Detailed discussion of topic.")
        write_unit(p, corpus)

        fake_llm_response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Deep synthesis of the topic with clear points.",
                    }
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_llm_response).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        os.environ["OPENAI_API_KEY"] = "dummy_key"
        os.environ.pop("LLMWIKI_MOCK", None)
        try:
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = compile_wiki(corpus, state_path=state, mock=False)
                assert result["compiled"] == 1

                concept_file = next((corpus / "wiki" / "concepts").glob("*.md"))
                content = concept_file.read_text(encoding="utf-8")
                assert "Deep synthesis of the topic" in content
                assert "source: wiki-compiler" in content
                assert "silo: wiki" in content
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
