"""Owner-signed exportable checkpoints for the task event hash chain.

Private keys are supplied by the operator and are never generated or persisted here.
A checkpoint only attests that the signer signed a particular chain head at a stated
time; it does not prove the underlying work or the accuracy of local system time.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .task_store import TaskStore

SCHEMA = "autonomous-ai-economy/audit-checkpoint/v1"


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as exc:
        raise RuntimeError("audit checkpoint signing requires the optional identity extra: pip install '.[identity]'") from exc
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def export_checkpoint(store: TaskStore, private_key_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    serialization, private_type, _ = _crypto()
    report = store.verify_event_chain()
    if not report.get("valid"):
        raise ValueError("cannot checkpoint an invalid task event chain")
    key_bytes = Path(private_key_path).read_bytes()
    key = serialization.load_pem_private_key(key_bytes, password=None)
    if not isinstance(key, private_type):
        raise ValueError("checkpoint signing key must be an Ed25519 private key")
    payload = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checked_events": report["checked_events"],
        "head_hash": report["head_hash"],
    }
    signature = base64.b64encode(key.sign(_canonical(payload))).decode("ascii")
    document = {**payload, "signature": signature}
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids silently replacing an earlier audit checkpoint.
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, sort_keys=True, indent=2) + chr(10))
    return {"output": str(destination), **payload, "signature": signature}


def verify_checkpoint(checkpoint_path: str | Path, public_key_path: str | Path,
                      store: TaskStore | None = None) -> dict[str, Any]:
    serialization, _, public_type = _crypto()
    document = json.loads(Path(checkpoint_path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("checkpoint must be a JSON object")
    required = {"schema", "created_at", "checked_events", "head_hash", "signature"}
    if set(document) != required or document.get("schema") != SCHEMA:
        raise ValueError("unsupported or malformed audit checkpoint")
    if (not isinstance(document["checked_events"], int) or document["checked_events"] < 0
            or not isinstance(document["head_hash"], str)
            or len(document["head_hash"]) != 64
            or any(ch not in "0123456789abcdef" for ch in document["head_hash"])):
        raise ValueError("invalid checkpoint event count or head hash")
    datetime.fromisoformat(document["created_at"])
    try:
        signature = base64.b64decode(document["signature"], validate=True)
    except Exception as exc:
        raise ValueError("invalid checkpoint signature encoding") from exc
    public_bytes = Path(public_key_path).read_bytes()
    key = serialization.load_pem_public_key(public_bytes)
    if not isinstance(key, public_type):
        raise ValueError("trusted checkpoint key must be an Ed25519 public key")
    payload = {name: document[name] for name in ("schema", "created_at", "checked_events", "head_hash")}
    try:
        key.verify(signature, _canonical(payload))
    except Exception:
        return {"valid": False, "reason": "signature_invalid", "head_hash": document["head_hash"]}
    result = {"valid": True, "reason": None, "head_hash": document["head_hash"],
              "checked_events": document["checked_events"], "created_at": document["created_at"]}
    if store is not None:
        local = store.verify_event_chain()
        result["local_chain_valid"] = bool(local.get("valid"))
        result["matches_local_head"] = bool(
            local.get("valid")
            and local.get("head_hash") == document["head_hash"]
            and local.get("checked_events") == document["checked_events"]
        )
    return result
