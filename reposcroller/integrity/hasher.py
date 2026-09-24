"""Streaming cryptographic hashing for bit-level document identification (ALCOA+ Original/Accurate)."""

import hashlib
from pathlib import Path
from typing import Tuple, Optional
import os


def compute_sha256(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA-256 hash of a file using streaming chunks to handle arbitrary file sizes."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_bytes_sha256(data: bytes) -> str:
    """Compute SHA-256 hash of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_file_stats(file_path: Path) -> Tuple[int, float]:
    """Retrieve file size in bytes and modification timestamp (mtime)."""
    stat = file_path.stat()
    return stat.st_size, stat.st_mtime


def quick_content_probe(file_path: Path, head_size: int = 4096) -> Optional[bytes]:
    """Read file header bytes to verify access and mime signature before full processing."""
    try:
        with open(file_path, "rb") as f:
            return f.read(head_size)
    except (PermissionError, FileNotFoundError, OSError):
        return None
