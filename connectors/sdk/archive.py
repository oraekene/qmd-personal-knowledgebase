"""Safe archive handling and decompression bomb defenses.

Defends against:
1. High-compression-ratio zip bombs (e.g., 42KB -> 10GB).
2. Huge uncompressed file sizes exceeding memory limits.
3. Total cumulative volume exhaustion (inode or disk DOS).
4. Path traversal vulnerabilities inside archive entry filenames (e.g., ../ or absolute paths).
5. Metadata spoofing (forged uncompressed size in zip header).
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path
from typing import BinaryIO, Union

# Security bounds
MAX_ENTRY_COUNT = 2000
MAX_UNCOMPRESSED_FILE_SIZE = 50 * 1024 * 1024  # 50 MB per file
MAX_TOTAL_UNCOMPRESSED_SIZE = 150 * 1024 * 1024  # 150 MB total archive
MAX_COMPRESSION_RATIO = 100.0  # Max 100:1 ratio for files > 1 MB
CHUNK_SIZE = 64 * 1024  # 64 KB streaming buffer


class UnsafeArchiveError(ValueError):
    """Raised when an archive contains malicious structure (e.g., path traversal, entry explosion)."""
    pass


class DecompressionBombError(ValueError):
    """Raised when an archive violates decompression size or compression ratio safety limits."""
    pass


def validate_zip_archive(zf: zipfile.ZipFile) -> None:
    """Validate archive structure against zip bombs, inode exhaustion, and path traversal."""
    entries = zf.infolist()
    if len(entries) > MAX_ENTRY_COUNT:
        raise UnsafeArchiveError(
            f"Archive contains {len(entries)} entries, exceeding maximum safe limit of {MAX_ENTRY_COUNT}"
        )

    total_uncompressed = 0
    for info in entries:
        raw_name = info.filename

        # 1. Path traversal and absolute path detection
        if (
            ".." in raw_name
            or raw_name.startswith("/")
            or raw_name.startswith("\\")
            or re.match(r"^[a-zA-Z]:", raw_name)
        ):
            raise UnsafeArchiveError(f"Directory traversal detected in archive path: {raw_name!r}")

        # 2. Per-file size check (from header)
        if info.file_size > MAX_UNCOMPRESSED_FILE_SIZE:
            raise DecompressionBombError(
                f"File '{raw_name}' uncompressed size ({info.file_size} bytes) exceeds limit of {MAX_UNCOMPRESSED_FILE_SIZE} bytes"
            )

        total_uncompressed += info.file_size
        if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_SIZE:
            raise DecompressionBombError(
                f"Total uncompressed archive size ({total_uncompressed} bytes) exceeds limit of {MAX_TOTAL_UNCOMPRESSED_SIZE} bytes"
            )

        # 3. Compression ratio check (for files > 1MB)
        if info.file_size > 1024 * 1024 and info.compress_size > 0:
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                raise DecompressionBombError(
                    f"Compression ratio {ratio:.1f}:1 for '{raw_name}' exceeds safety threshold of {MAX_COMPRESSION_RATIO}:1"
                )


def safe_read_zip_entry(
    zf: zipfile.ZipFile,
    name_or_info: Union[str, zipfile.ZipInfo],
    max_bytes: int = MAX_UNCOMPRESSED_FILE_SIZE,
) -> bytes:
    """Stream-read a zip entry in chunks up to max_bytes to protect against forged zip headers."""
    buf = io.BytesIO()
    total_read = 0

    with zf.open(name_or_info, "r") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > max_bytes:
                raise DecompressionBombError(
                    f"Decompressed stream exceeded safe limit of {max_bytes} bytes"
                )
            buf.write(chunk)

    return buf.getvalue()
