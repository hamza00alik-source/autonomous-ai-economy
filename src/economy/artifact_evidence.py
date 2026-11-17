"""Local verification of operator-supplied work artifact bytes.

This module never fetches URLs. The caller supplies a local file and a manifest.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "autonomous-ai-economy/artifact-manifest/v1"
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema", "sha256", "size_bytes", "media_type"
    }:
        raise ValueError("artifact manifest must contain exactly schema, sha256, size_bytes, media_type")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ValueError("unsupported artifact manifest schema")
    if not isinstance(manifest["sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", manifest["sha256"]
    ):
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    size = manifest["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_ARTIFACT_BYTES:
        raise ValueError(f"size_bytes must be an integer from 0 to {MAX_ARTIFACT_BYTES}")
    media_type = manifest["media_type"]
    if (not isinstance(media_type, str) or not media_type or len(media_type) > 127
            or "/" not in media_type or any(ord(ch) < 33 or ord(ch) > 126 for ch in media_type)):
        raise ValueError("media_type must be a printable type/subtype value")
    return dict(manifest)


def create_manifest(path: str | Path, media_type: str = "application/octet-stream") -> dict[str, Any]:
    """Create a manifest for a local regular file; this is a claim, not provenance."""
    artifact = Path(path)
    if artifact.is_symlink() or not artifact.is_file():
        raise ValueError("artifact must be a regular, non-symlink local file")
    size = artifact.stat().st_size
    if size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact exceeds the maximum manifest size")
    digest = hashlib.sha256()
    with artifact.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return validate_manifest({
        "schema": MANIFEST_SCHEMA, "sha256": digest.hexdigest(),
        "size_bytes": size, "media_type": media_type,
    })


def verify_local_artifact(path: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Hash a local regular file and compare it with a validated manifest.

    No network access occurs. A successful result verifies byte equality only;
    it does not establish provenance, creation time, authorship, or quality.
    """
    expected = validate_manifest(manifest)
    artifact = Path(path)
    if artifact.is_symlink() or not artifact.is_file():
        raise ValueError("artifact must be a regular, non-symlink local file")
    size = artifact.stat().st_size
    if size != expected["size_bytes"]:
        return {"valid": False, "reason": "size_mismatch", "actual_size_bytes": size}
    if size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact exceeds the maximum verification size")
    digest = hashlib.sha256()
    with artifact.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    return {
        "valid": actual == expected["sha256"],
        "reason": "matched" if actual == expected["sha256"] else "sha256_mismatch",
        "sha256": actual,
        "size_bytes": size,
        "media_type": expected["media_type"],
    }
