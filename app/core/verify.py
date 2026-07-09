"""Checksum helpers: hash a finished file and compare it to an expected value."""

from __future__ import annotations

import hashlib
from pathlib import Path

ALGORITHMS = ("sha256", "md5", "sha1")
_CHUNK = 1 << 20


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    """Streaming hex digest of ``path`` (never loads the whole file)."""
    if algorithm not in ALGORITHMS:
        raise ValueError(f"unsupported algorithm: {algorithm}")
    digest = hashlib.new(algorithm)
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def guess_algorithm(expected: str) -> str:
    """Pick the algorithm implied by a hex digest's length."""
    return {32: "md5", 40: "sha1", 64: "sha256"}.get(len(expected.strip()), "sha256")


def verify_file(path: Path, expected: str, algorithm: str | None = None) -> bool:
    """True if ``path``'s digest equals ``expected`` (case-insensitive)."""
    expected = expected.strip().lower()
    algorithm = algorithm or guess_algorithm(expected)
    return hash_file(path, algorithm).lower() == expected
