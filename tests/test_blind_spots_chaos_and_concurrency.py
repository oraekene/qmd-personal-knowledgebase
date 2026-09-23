"""Adversarial Blind Spots Test Suite: Decompression Bombs, Concurrency Race Conditions, and Socket Chaos.

Validates that the QMD Personal Knowledgebase codebase survives:
1. Malicious archives: Zip bombs (>100:1 ratio), path traversal (../../), inode floods, and forged metadata.
2. High-concurrency operations: Multi-threaded write_unit(), concurrent SchedulerStore mutations,
   multithreaded SystemLogger, and concurrent mirror builds without file corruption or deadlocks.
3. Socket-level chaos: Raw TCP garbage injection, abrupt client TCP RST aborts, and slowloris half-open drops.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import socket
import struct
import sys
import threading
import time
import urllib.request
import zipfile
import zlib
from typing import Generator

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from auth_proxy.server import ThreadingHTTPServer, make_handler
from connectors.chats import ChatsConnector
from connectors.notes import NotesConnector
from connectors.sdk.archive import (
    CHUNK_SIZE,
    MAX_ENTRY_COUNT,
    MAX_UNCOMPRESSED_FILE_SIZE,
    DecompressionBombError,
    UnsafeArchiveError,
    safe_read_zip_entry,
    validate_zip_archive,
)
from connectors.sdk.base import UnitPayload
from connectors.sdk.writer import atomic_write_text, write_unit
from control_plane.scheduler import AutomationJob, SchedulerStore
from control_plane.server import SystemLogger, make_control_plane_handler
from scripts.build_mirror import build_mirror


# ======================================================================
# 1. DECOMPRESSION BOMBS & ARCHIVE ATTACKS
# ======================================================================

def test_zip_bomb_compression_ratio_rejection():
    """Verify that high-compression ratio archives (>100:1) are rejected as DecompressionBombError."""
    buf = io.BytesIO()
    # 2MB of zeroes compresses to under 2KB, giving a ratio > 1000:1
    uncompressed_data = b"0" * (2 * 1024 * 1024)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("huge_zeroes.txt", uncompressed_data)
    
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        with pytest.raises(DecompressionBombError) as exc_info:
            validate_zip_archive(zf)
        assert "exceeds safety threshold" in str(exc_info.value)


def test_zip_path_traversal_rejection():
    """Verify that entries containing directory traversal paths are rejected with UnsafeArchiveError."""
    for evil_path in ["../../evil.sh", "../secret.txt", "/etc/passwd", "\\windows\\system32\\calc.exe", "C:foo.txt"]:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(evil_path, b"malicious content")
        buf.seek(0)
        with zipfile.ZipFile(buf, "r") as zf:
            with pytest.raises(UnsafeArchiveError) as exc_info:
                validate_zip_archive(zf)
            assert "Directory traversal detected" in str(exc_info.value)


def test_zip_entry_count_explosion():
    """Verify that archives with excessive file entries (>2000) are rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(2005):
            zf.writestr(f"file_{i}.txt", b"x")
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        with pytest.raises(UnsafeArchiveError) as exc_info:
            validate_zip_archive(zf)
        assert "exceeding maximum safe limit" in str(exc_info.value)


def test_zip_spoofed_metadata_stream_safety():
    """Verify safe_read_zip_entry enforces max_bytes even if metadata or stream is oversized."""
    buf = io.BytesIO()
    payload = b"A" * 4096
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test.txt", payload)
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        # Cap read at 1024 bytes; payload is 4096
        with pytest.raises(DecompressionBombError) as exc_info:
            safe_read_zip_entry(zf, "test.txt", max_bytes=1024)
        assert "exceeded safe limit" in str(exc_info.value)


def test_fuzzed_corrupted_binaries_in_connectors(tmp_path: pathlib.Path):
    """Verify that corrupt or random binary zip files in inbox do not crash connectors."""
    inbox_chats = tmp_path / "inbox" / "chats"
    inbox_notes = tmp_path / "inbox" / "notes"
    inbox_chats.mkdir(parents=True)
    inbox_notes.mkdir(parents=True)

    # 1. Random garbage binary
    (inbox_chats / "claude_fuzzed.zip").write_bytes(os.urandom(1024))
    (inbox_notes / "simplenote_fuzzed.zip").write_bytes(os.urandom(1024))

    # 2. Truncated zip header
    (inbox_chats / "chatgpt_truncated.zip").write_bytes(b"PK\x03\x04\x14\x00\x00\x00")
    (inbox_notes / "keep_truncated.zip").write_bytes(b"PK\x03\x04\x14\x00\x00\x00")

    # 3. Zip bomb in inbox
    bomb_buf = io.BytesIO()
    with zipfile.ZipFile(bomb_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("conversations.json", b"0" * (2 * 1024 * 1024))
    (inbox_chats / "claude_bomb.zip").write_bytes(bomb_buf.getvalue())

    # Execute ChatsConnector — must not crash
    chats_conn = ChatsConnector(inbox_dir=tmp_path / "inbox")
    since = time.time() - 3600
    from datetime import datetime, timezone
    since_dt = datetime.fromtimestamp(since, tz=timezone.utc)
    units_chats = list(chats_conn.fetch_recent(since_dt))
    assert isinstance(units_chats, list)

    # Execute NotesConnector — must not crash
    notes_conn = NotesConnector(inbox_dir=inbox_notes)
    units_notes = list(notes_conn.fetch_recent(since_dt))
    assert isinstance(units_notes, list)


# ======================================================================
# 2. HIGH-CONCURRENCY RACE CONDITIONS
# ======================================================================

def test_concurrent_write_unit_race_condition(tmp_path: pathlib.Path):
    """Verify 50 threads concurrently writing to the exact same file path produce zero corruption."""
    corpus_root = tmp_path / "corpus"
    errors = []

    def writer_task(thread_id: int):
        try:
            payload = UnitPayload(
                source="test",
                silo="notes",
                source_id="concurrent_target",
                url="https://example.com/target",
                title=f"Concurrent Note Thread {thread_id}",
                summary=f"Summary for thread {thread_id}.",
                body_markdown=f"# Concurrent Note\n\nContent generated by thread {thread_id}.\n",
            )
            write_unit(payload, corpus_root)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer_task, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent write_unit failed with errors: {errors}"
    target_file = corpus_root / "notes" / "concurrent_target.md"
    assert target_file.exists()
    content = target_file.read_text(encoding="utf-8")
    assert "---" in content
    assert "source_id: concurrent_target" in content
    assert "content_hash:" in content
    assert "# Concurrent Note" in content


def test_concurrent_scheduler_store_mutations(tmp_path: pathlib.Path):
    """Verify SchedulerStore survives 30 threads performing simultaneous upserts and deletions."""
    store_file = tmp_path / "automations.json"
    store = SchedulerStore(store_file)
    errors = []

    def worker(worker_id: int):
        try:
            job = AutomationJob(
                id=f"job_{worker_id}",
                name=f"Job {worker_id}",
                action="reindex",
                schedule="0 * * * *",
                params={"worker": worker_id},
            )
            store.upsert_job(job)
            time.sleep(0.005)
            loaded = store.get_job(f"job_{worker_id}")
            assert loaded is not None
            assert loaded.name == f"Job {worker_id}"

            # Even-numbered workers delete their job
            if worker_id % 2 == 0:
                store.delete_job(f"job_{worker_id}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"SchedulerStore concurrency errors: {errors}"
    jobs = store.load_jobs()
    # Odd-numbered jobs should remain
    odd_ids = {f"job_{i}" for i in range(1, 30, 2)}
    remaining_ids = {j.id for j in jobs}
    for oid in odd_ids:
        assert oid in remaining_ids


def test_concurrent_system_logger(tmp_path: pathlib.Path):
    """Verify SystemLogger under 30 threads logging simultaneously maintains monotonic order and valid JSON."""
    logger = SystemLogger(tmp_path, max_entries=5000)
    errors = []

    def logger_task(thread_id: int):
        try:
            for j in range(20):
                logger.log("WORKER", f"Thread {thread_id} step {j}", level="INFO")
                logger.log_user_action("MUTATE_CONFIG", {"thread": thread_id, "step": j})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=logger_task, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"SystemLogger concurrency errors: {errors}"
    assert logger.count() == 30 * 20 * 2  # 1200 entries total
    all_logs = logger.get_logs()
    # Assert monotonic IDs
    ids = [entry["id"] for entry in all_logs]
    assert ids == list(range(1, 1201))


def test_concurrent_mirror_build_and_rotation(tmp_path: pathlib.Path):
    """Verify concurrent build_mirror executions on the same dist directory do not crash or corrupt output."""
    corpus = tmp_path / "corpus" / "notes"
    corpus.mkdir(parents=True)
    (corpus / "sample.md").write_text("# Sample Note\n\n> Summary sentence.\n\nBody content.", encoding="utf-8")

    dist = tmp_path / "dist"
    errors = []

    def builder_task(token_prefix: str):
        try:
            token = (token_prefix * 16)[:32]
            build_mirror(tmp_path / "corpus", dist, token=token)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=builder_task, args=("a",)),
        threading.Thread(target=builder_task, args=("b",)),
        threading.Thread(target=builder_task, args=("c",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent build_mirror failed: {errors}"
    assert (dist / "llms.txt").exists()
    assert (dist / "404.html").exists()


# ======================================================================
# 3. SOCKET-LEVEL CHAOS & NETWORK RESILIENCY
# ======================================================================

@pytest.fixture
def running_control_plane(tmp_path: pathlib.Path) -> Generator[dict, None, None]:
    """Launch an ephemeral Control Plane server on an available localhost port."""
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<h1>OK</h1>", encoding="utf-8")

    handler_cls = make_control_plane_handler(tmp_path, static_dir)
    # Find free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)

    yield {"port": port, "base_url": f"http://127.0.0.1:{port}"}

    server.shutdown()
    server.server_close()


def test_socket_chaos_garbage_injection_and_rst(running_control_plane: dict):
    """Send arbitrary binary garbage followed by abrupt TCP RST; verify server survives unharmed."""
    port = running_control_plane["port"]
    base_url = running_control_plane["base_url"]

    # 1. Inject raw binary garbage
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect(("127.0.0.1", port))
        sock.sendall(b"\x00\xff\xfe\x13\xde\xad\xbe\xef\x00\x00\n\n\n\r\n")
        # Force hard TCP RST via SO_LINGER timeout 0
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

    time.sleep(0.05)

    # 2. Subsequent valid HTTP request must succeed
    req = urllib.request.Request(f"{base_url}/api/status")
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "services" in data


def test_socket_chaos_slowloris_half_open(running_control_plane: dict):
    """Simulate slowloris/half-open client that disconnects mid-header; verify server continues normally."""
    port = running_control_plane["port"]
    base_url = running_control_plane["base_url"]

    # Open socket, send incomplete headers, abruptly drop
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect(("127.0.0.1", port))
        sock.sendall(b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        time.sleep(0.05)
        # Drop without terminating headers

    time.sleep(0.05)

    # Server must still be responsive
    req = urllib.request.Request(f"{base_url}/")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        assert b"OK" in resp.read()


def test_auth_proxy_socket_chaos():
    """Verify Auth Proxy handler survives raw TCP garbage and hard disconnects."""
    handler_cls = make_handler("test_token_1234567890abcdef", "http://127.0.0.1:8181")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    proxy_server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    t = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)

    try:
        # Send raw garbage with RST
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", port))
            sock.sendall(b"\x99\x88\x77\x66\x55\x44\x33\x22\x11\n\n")
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

        time.sleep(0.05)

        # Send valid request — should receive 401 Unauthorized (since no Bearer token sent)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp")
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTP 401"
        except urllib.error.HTTPError as err:
            assert err.code == 401
    finally:
        proxy_server.shutdown()
        proxy_server.server_close()
