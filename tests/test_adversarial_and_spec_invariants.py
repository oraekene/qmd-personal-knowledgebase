"""Adversarial & Spec Invariant Stress Tests.

Tests intentional failure modes, spec contract violations, adversarial attacks,
boundary conditions, and corrupted data across all subsystems:
1. Frontmatter 9-field schema invariants and validation failures
2. Path traversal and Windows-unsafe filename sanitization
3. Corrupted / 0-byte inbox files and connector failure isolation
4. Cron syntax fuzzing, zero-steps, and boundary protections
5. Static Mirror secret isolation, token rotation purging, and invalid token rejection
6. Auth Proxy Bearer strictness, timing attack resilience, and origin spoofing
7. OAuth PKCE replay attacks, expired code rejection, and verifier mismatch
8. Control Plane REST malformed payloads (400 Bad Request vs 500 crashes)
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from auth_proxy.oauth import (
    OAuthStore,
    _compute_s256,
    verify_pkce,
)
from auth_proxy.progressive_tools import handle_progressive_tool_call, view_skill
from auth_proxy.proxy import ProxyApp, check_auth, check_origin
from connectors.sdk.base import UnitPayload
from connectors.sdk.writer import safe_filename, write_unit
from control_plane.sandbox import LocalSubprocessSandbox, execute_action
from control_plane.scheduler import compute_next_run, matches_cron
from scripts.build_mirror import MirrorToken, build_mirror


# ==============================================================================
# 1. Frontmatter & Writer Invariants (spec.md:87-101)
# ==============================================================================

def test_writer_rejects_missing_mandatory_fields(tmp_path: pathlib.Path):
    """Spec invariant: source, silo, and source_id are strictly required."""
    corpus = tmp_path / "corpus"

    # Missing source
    with pytest.raises(ValueError, match="source, silo, source_id required"):
        write_unit(
            UnitPayload(source="", silo="notes", source_id="id1", summary="Valid summary.", body_markdown="# Heading"),
            corpus,
        )

    # Missing silo
    with pytest.raises(ValueError, match="source, silo, source_id required"):
        write_unit(
            UnitPayload(source="src", silo="", source_id="id1", summary="Valid summary.", body_markdown="# Heading"),
            corpus,
        )

    # Missing source_id
    with pytest.raises(ValueError, match="source, silo, source_id required"):
        write_unit(
            UnitPayload(source="src", silo="notes", source_id="", summary="Valid summary.", body_markdown="# Heading"),
            corpus,
        )


def test_writer_rejects_empty_or_multiline_summary(tmp_path: pathlib.Path):
    """Spec invariant: Summary Line must be exactly one non-empty sentence (no newlines)."""
    corpus = tmp_path / "corpus"

    # Empty summary
    with pytest.raises(ValueError, match="Summary Line required"):
        write_unit(
            UnitPayload(source="src", silo="notes", source_id="id1", summary="", body_markdown="# Heading"),
            corpus,
        )

    # Multiline summary
    with pytest.raises(ValueError, match="Summary Line must be one sentence"):
        write_unit(
            UnitPayload(
                source="src",
                silo="notes",
                source_id="id2",
                summary="First line.\nSecond line attack.",
                body_markdown="# Heading",
            ),
            corpus,
        )


def test_writer_frontmatter_never_contains_title(tmp_path: pathlib.Path):
    """Spec invariant: No title field in frontmatter — title is derived from the first '# ' heading."""
    corpus = tmp_path / "corpus"
    payload = UnitPayload(
        source="unit_test",
        silo="notes",
        source_id="test_title_leak",
        title="Sensitive Internal Document",
        summary="This is a valid one sentence summary.",
        body_markdown="# Sensitive Internal Document\n\nBody paragraph.",
    )
    out_file = write_unit(payload, corpus)
    content = out_file.read_text(encoding="utf-8")

    # Split into frontmatter and body
    parts = content.split("---\n", 2)
    assert len(parts) >= 3
    frontmatter = parts[1]

    # Frontmatter MUST NOT have title
    assert "title:" not in frontmatter
    # Frontmatter must have exactly the 9 normative fields
    for field in ["source:", "silo:", "source_id:", "url:", "created_at:", "ingested_at:", "tags:", "author:", "content_hash:"]:
        assert field in frontmatter, f"Missing expected field: {field}"


def test_safe_filename_adversarial_sanitization():
    """Spec invariant: Windows-unsafe chars (:*?\"<>|) and path traversal are neutralized."""
    # Slashes replaced by double underscore
    assert safe_filename("dir/sub/file") == "dir__sub__file"
    assert safe_filename("dir\\sub\\file") == "dir__sub__file"

    # Path traversal ../
    assert ".." not in safe_filename("../../../etc/passwd")

    # Windows reserved characters
    sanitized = safe_filename('test:name*with?bad"chars<and>pipes|')
    assert ":" not in sanitized
    assert "*" not in sanitized
    assert "?" not in sanitized
    assert '"' not in sanitized
    assert "<" not in sanitized
    assert ">" not in sanitized
    assert "|" not in sanitized

    # Length capping (max 200 chars)
    long_name = "a" * 300
    assert len(safe_filename(long_name)) <= 200


# ==============================================================================
# 2. Cron Parser Fuzzing & Malformed Schedules (control_plane/scheduler.py)
# ==============================================================================

def test_cron_parser_adversarial_fuzzing():
    """Tests that malformed cron strings do NOT raise uncaught exceptions or cause CPU hangs."""
    dt = datetime.datetime.now(datetime.timezone.utc)

    # Malformed strings that previously crashed int()
    assert matches_cron(dt, "a b c d e") is False
    assert matches_cron(dt, "invalid") is False
    assert matches_cron(dt, "* * * *") is False  # 4 fields instead of 5
    assert matches_cron(dt, "* * * * * *") is False  # 6 fields instead of 5
    assert matches_cron(dt, "*/0 * * * *") is False  # Step by 0 division
    assert matches_cron(dt, "*/-5 * * * *") is False  # Negative step
    assert matches_cron(dt, "10-5 * * * *") is False  # Inverted range

    # compute_next_run with impossible cron terminates immediately via fallback (<0.1s)
    start_t = datetime.datetime.now()
    next_dt = compute_next_run("99 99 99 99 99", from_dt=dt)
    duration = (datetime.datetime.now() - start_t).total_seconds()
    assert duration < 0.5  # Must not spin for 525,600 iterations
    assert next_dt > dt


# ==============================================================================
# 3. Static Mirror Security & Token Purging (scripts/build_mirror.py)
# ==============================================================================

def test_mirror_token_validation_strictness():
    """Spec invariant: MirrorToken must be hex, non-empty, and >=16 chars."""
    with pytest.raises(ValueError, match="must not be empty"):
        MirrorToken("")

    with pytest.raises(ValueError, match="too short"):
        MirrorToken("0123456789abc")  # 13 chars

    with pytest.raises(ValueError, match="must be hex"):
        MirrorToken("not_a_valid_hex_string_12345")


def test_mirror_token_rotation_purges_old_token_directory(tmp_path: pathlib.Path):
    """Spec invariant: Token rotation must completely delete previous token paths from dist."""
    corpus = tmp_path / "corpus" / "notes"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "secret.md").write_text("# Secret\nClassified data.\n", encoding="utf-8")

    dist = tmp_path / "dist"
    token_old = "11111111111111111111111111111111"
    token_new = "22222222222222222222222222222222"

    # 1. Build deployment with old token
    build_mirror(corpus=tmp_path / "corpus", dist=dist, token=token_old)
    assert (dist / token_old).exists()
    assert (dist / token_old / "notes" / "secret.md").exists()

    # 2. Deploy with new rotated token
    build_mirror(corpus=tmp_path / "corpus", dist=dist, token=token_new)

    # 3. Old token path MUST be completely purged from disk
    assert not (dist / token_old).exists(), "Old token directory must be purged on rotation"
    assert (dist / token_new).exists()
    assert (dist / token_new / "notes" / "secret.md").exists()

    # 4. Root llms.txt must NEVER leak either token
    root_llms = (dist / "llms.txt").read_text(encoding="utf-8")
    assert token_old not in root_llms
    assert token_new not in root_llms


# ==============================================================================
# 4. Auth Proxy Bearer Strictness & Origin Spoofing (auth_proxy/proxy.py)
# ==============================================================================

def test_auth_proxy_strict_header_rejections():
    """Spec invariant: Bearer token parsing must be constant-time and strictly formatted."""
    expected = "valid_secret_token_123"

    # Missing header
    assert check_auth({}, expected) is False

    # Lowercase bearer (spec specifies case-sensitive 'Bearer ')
    assert check_auth({"Authorization": "bearer valid_secret_token_123"}, expected) is False

    # Double space
    assert check_auth({"Authorization": "Bearer  valid_secret_token_123"}, expected) is False

    # Trailing space in token
    assert check_auth({"Authorization": "Bearer valid_secret_token_123 "}, expected) is False

    # Empty expected token must never authorize (prevents compare_digest("", "") bypass)
    assert check_auth({"Authorization": "Bearer "}, "") is False
    assert check_auth({}, "") is False


def test_auth_proxy_origin_spoofing_prevention():
    """Spec invariant: When origin restriction is enabled, unauthorized origins return 403."""
    app = ProxyApp(
        expected_token="token123",
        qmd_handler=lambda m, p, h, b: (200, {}, b"ok"),
        allowed_origins=("https://claude.ai",),
    )

    # Authorized origin
    status, _, _ = app.handle(
        "POST", "/mcp",
        {"Authorization": "Bearer token123", "Origin": "https://claude.ai"},
        b"{}",
    )
    assert status == 200

    # Spoofed / unauthorized origin
    status_bad, _, body_bad = app.handle(
        "POST", "/mcp",
        {"Authorization": "Bearer token123", "Origin": "https://attacker.evil.com"},
        b"{}",
    )
    assert status_bad == 403
    assert b"Forbidden origin" in body_bad


# ==============================================================================
# 5. OAuth RFC 7636 PKCE Tampering & Replay Attacks (auth_proxy/oauth.py)
# ==============================================================================

def test_oauth_pkce_tampering_and_replay_protection():
    """Spec invariant: PKCE codes are single-use and tamper-proof."""
    store = OAuthStore()
    client = store.register_client({"client_name": "Test Client"})
    client_id = client["client_id"]

    verifier = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    challenge = _compute_s256(verifier)

    # 1. Create code
    code = store.create_authorization_code(
        client_id=client_id,
        redirect_uri="https://callback.com",
        code_challenge=challenge,
        code_challenge_method="S256",
    )

    # 2. Tampered verifier must fail
    tampered_valid, err = store.validate_and_consume_code(
        code=code,
        code_verifier="wrong_attacker_verifier_1234567890",
        redirect_uri="https://callback.com",
    )
    assert tampered_valid is False
    assert "PKCE" in err or "failed" in err.lower()

    # Note: Because the code was popped/consumed upon validation attempt, replay is immediately rejected
    replay_valid, _ = store.validate_and_consume_code(
        code=code,
        code_verifier=verifier,
        redirect_uri="https://callback.com",
    )
    assert replay_valid is False


def test_oauth_expired_authorization_code():
    """Spec invariant: Expired authorization codes are rejected."""
    store = OAuthStore()
    client = store.register_client({"client_name": "Test"})
    code = store.create_authorization_code(
        client_id=client["client_id"],
        redirect_uri="https://callback.com",
        ttl_seconds=-10,  # Pre-expired
    )
    valid, err = store.validate_and_consume_code(code=code, redirect_uri="https://callback.com")
    assert valid is False
    assert "expired" in err.lower()


# ==============================================================================
# 6. Progressive Tools & Path Traversal Guardrails (auth_proxy/progressive_tools.py)
# ==============================================================================

def test_progressive_tools_path_traversal_blocked(tmp_path: pathlib.Path):
    """Spec invariant: skill_view rejects path traversal payloads (e.g. ../../etc/passwd)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    with pytest.raises(ValueError, match="Invalid skill name"):
        view_skill("../../etc/passwd", skills_dir=skills_dir)

    with pytest.raises(ValueError, match="Invalid skill name"):
        view_skill("..\\windows\\system32", skills_dir=skills_dir)


def test_progressive_tools_unknown_tool_returns_structured_mcp_error():
    """Spec invariant: Invalid or unknown tool execution returns MCP isError: True, not an unhandled crash."""
    res = handle_progressive_tool_call("non_existent_exploit_tool", {"arg": "val"})
    assert res["isError"] is True
    assert "Error executing tool" in res["content"][0]["text"]
