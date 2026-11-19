import hashlib
import hmac
import json
import time

import pytest

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare" / "python-runtime" / "src"))
from runtime import verify_execution_request, build_verified_artifact


SECRET = "test-only-execution-bridge-secret-with-32-bytes"
JOB = "123e4567-e89b-42d3-a456-426614174000"
PAYLOAD = {"job_id": JOB, "owner_id": "owner-001", "execution_spec": {"kind": "moba_objective_props_v1"}}


def signed(payload=PAYLOAD, *, timestamp=None, secret=SECRET):
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(secret.encode(), stamp.encode() + b"\n" + raw, hashlib.sha256).hexdigest()
    return raw, stamp, signature


def test_private_execution_envelope_accepts_only_exact_allowlisted_capability():
    raw, stamp, signature = signed(timestamp=1000)
    assert verify_execution_request(raw, stamp, signature, SECRET, now=1000) == PAYLOAD


@pytest.mark.parametrize("mutation", [
    {"execution_spec": {"kind": "arbitrary_python"}},
    {"execution_spec": {"kind": "moba_objective_props_v1", "extra": True}},
    {"owner_id": "owner-001", "extra": "unexpected"},
    {"job_id": "../escape"},
])
def test_private_execution_envelope_rejects_unapproved_payloads(mutation):
    payload = dict(PAYLOAD)
    payload.update(mutation)
    raw, stamp, signature = signed(payload, timestamp=1000)
    with pytest.raises(ValueError):
        verify_execution_request(raw, stamp, signature, SECRET, now=1000)


def test_private_execution_envelope_rejects_bad_signature_expiry_and_weak_secret():
    raw, stamp, signature = signed(timestamp=1000)
    with pytest.raises(ValueError):
        verify_execution_request(raw, stamp, "0" * 64, SECRET, now=1000)
    with pytest.raises(ValueError):
        verify_execution_request(raw, stamp, signature, SECRET, now=1400)
    with pytest.raises(ValueError):
        verify_execution_request(raw, stamp, signature, "short", now=1000)


def test_cloud_python_producer_builds_structurally_verified_product():
    artifact, digest, qa = build_verified_artifact()
    assert artifact.startswith(b"PK")
    assert hashlib.sha256(artifact).hexdigest() == digest
    assert qa["qa_passed"] is True
    assert qa["glb_models"] == 6
    assert qa["visual_review"] == "not_performed"
