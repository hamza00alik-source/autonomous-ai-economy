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


def verify_artifact_digests(paths: list[str | Path], expected_digests: list[str]) -> list[dict[str, Any]]:
    """Verify every expected artifact digest against exactly one supplied local file."""
    if not isinstance(expected_digests, list) or any(
        not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item)
        for item in expected_digests
    ):
        raise ValueError("expected artifact digests must be lowercase SHA-256 values")
    expected = set(expected_digests)
    if len(expected) != len(expected_digests):
        raise ValueError("duplicate expected artifact digests are not allowed")
    found: dict[str, dict[str, Any]] = {}
    for raw_path in paths:
        artifact = Path(raw_path)
        if artifact.is_symlink() or not artifact.is_file():
            raise ValueError("each artifact must be a regular, non-symlink local file")
        size = artifact.stat().st_size
        if size > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact exceeds the maximum verification size")
        digest = hashlib.sha256()
        with artifact.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        value = digest.hexdigest()
        if value not in expected:
            raise ValueError(f"supplied artifact does not match a receipt digest: {artifact.name}")
        if value in found:
            raise ValueError("multiple supplied files match the same receipt artifact digest")
        found[value] = {"sha256": value, "size_bytes": size, "path_name": artifact.name}
    missing = expected - set(found)
    if missing:
        raise ValueError("missing locally verified receipt artifacts: " + ", ".join(sorted(missing)))
    if set(found) != expected:
        raise ValueError("supplied artifacts do not exactly match receipt artifact digests")
    return [found[digest] for digest in sorted(found)]
