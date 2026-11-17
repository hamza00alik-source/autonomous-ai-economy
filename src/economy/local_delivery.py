"""Operator-driven local buyer acceptance after verifying delivered artifact bytes."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Any

from .artifact_evidence import create_manifest, verify_artifact_digests
from .task_agreements import TaskAgreementStore
from .work_records import WorkRecordStore
from .identity import verify_ed25519



def submit_receipt_locally(
    database_path: str | Path,
    task_id: str,
    provider_id: str,
    buyer_id: str,
    summary: str,
    artifact_paths: list[str | Path],
    signer: Callable[[bytes], str],
    verifier: Callable[[str, bytes, str], bool] = verify_ed25519,
) -> dict[str, Any]:
    """Create content-addressed evidence and submit a provider-signed work receipt."""
    if not artifact_paths:
        raise ValueError("at least one local deliverable is required")
    manifests = [create_manifest(path) for path in artifact_paths]
    digests = [item["sha256"] for item in manifests]
    if len(set(digests)) != len(digests):
        raise ValueError("each submitted artifact must have unique content")
    evidence_refs = ["artifact:sha256:" + item for item in digests]
    store = WorkRecordStore(database_path, verifier=verifier)
    signing_bytes = store.submission_signing_bytes(
        task_id=task_id, provider_id=provider_id, buyer_id=buyer_id,
        summary=summary, evidence_refs=evidence_refs,
    )
    signature = signer(signing_bytes)
    if not isinstance(signature, str) or not signature:
        raise ValueError("signer must return a non-empty encoded signature")
    receipt = store.submit(
        task_id=task_id, provider_id=provider_id, buyer_id=buyer_id,
        summary=summary, evidence_refs=evidence_refs, signature=signature,
    )
    return {
        "receipt": receipt,
        "artifact_manifests": manifests,
        "notice": "The provider signed content hashes for local files. This does not prove authorship, delivery, quality, or payment. No payout or transfer was performed.",
    }


def accept_receipt_locally(
    database_path: str | Path,
    receipt_id: str,
    buyer_id: str,
    artifact_paths: list[str | Path],
    signer: Callable[[bytes], str],
    verifier: Callable[[str, bytes, str], bool] = verify_ed25519,
) -> dict[str, Any]:
    """Verify every receipt artifact locally, sign its exact acceptance payload, and accept.

    The caller owns private-key handling. No files are uploaded and no money moves.
    """
    path = Path(database_path)
    # Initialize the agreement schema so a missing/uninitialized store fails through
    # the normal accepted-agreement check rather than an opaque SQLite table error.
    TaskAgreementStore(path)
    store = WorkRecordStore(path, verifier=verifier)
    receipt = store.get_receipt(receipt_id)
    if receipt["buyer_id"] != buyer_id or receipt["status"] != "submitted":
        raise ValueError("submitted receipt not found or buyer is not authorized")
    expected = sorted({
        ref.removeprefix("artifact:sha256:")
        for ref in receipt["evidence_refs"]
        if ref.startswith("artifact:sha256:")
    })
    if not expected:
        raise ValueError("receipt has no content-addressed local artifacts to verify")
    verification = verify_artifact_digests(artifact_paths, expected)
    # Derive bytes from the stored receipt and accepted agreement, never caller input.
    signing_bytes = store.acceptance_signing_bytes(receipt_id, buyer_id=buyer_id)
    signature = signer(signing_bytes)
    if not isinstance(signature, str) or not signature:
        raise ValueError("signer must return a non-empty encoded signature")
    accepted = store.accept(receipt_id, buyer_id=buyer_id, signature=signature)
    return {
        "receipt": accepted,
        "verified_artifacts": verification,
        "notice": "Local byte hashes matched the receipt before buyer signing. This does not prove provenance, delivery channel, authorship, quality, or payment. No payout or transfer was performed.",
    }
