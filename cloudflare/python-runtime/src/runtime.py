"""Fixed, authenticated product-build capability for the private Python Worker."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from economy.game_asset_pack import build_game_asset_pack

MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
JOB_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
OWNER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$")
EXPECTED_FILES = {
    "assets/mana_crystal.glb", "assets/health_vial.glb",
    "assets/rune_altar.glb", "assets/supply_chest.glb",
    "assets/coin_stack.glb", "preview.glb",
    "godot/MOBAObjectiveProps.tscn", "project.godot",
    "manifest.json", "README.md", "LICENSE.txt", "listing-copy.md",
}


def verify_execution_request(raw_body: bytes, timestamp: str, signature: str, secret: str, *, now: int | None = None) -> dict:
    """Verify a short-lived HMAC envelope and the one exact internal capability."""
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise ValueError("execution bridge secret is not configured")
    try:
        issued = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid execution timestamp") from exc
    current = int(time.time()) if now is None else int(now)
    if abs(current - issued) > 300:
        raise ValueError("execution request expired")
    expected = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"\n" + raw_body, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
        raise ValueError("invalid execution request signature")
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid execution request JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"job_id", "owner_id", "execution_spec"}:
        raise ValueError("execution request schema mismatch")
    if not isinstance(payload["job_id"], str) or not JOB_ID.fullmatch(payload["job_id"]):
        raise ValueError("invalid execution job ID")
    if not isinstance(payload["owner_id"], str) or not OWNER_ID.fullmatch(payload["owner_id"]):
        raise ValueError("invalid owner ID")
    if payload["execution_spec"] != {"kind": "moba_objective_props_v1"}:
        raise ValueError("execution capability is not allowlisted")
    return payload


def build_verified_artifact() -> tuple[bytes, str, dict]:
    """Run the built-in producer in ephemeral storage and return a verified ZIP."""
    with tempfile.TemporaryDirectory(prefix="aae-product-") as directory:
        output = Path(directory) / "moba-objective-props.zip"
        build_game_asset_pack(output)
        if not output.is_file():
            raise ValueError("product producer did not create an artifact")
        size = output.stat().st_size
        if size <= 0 or size > MAX_ARCHIVE_BYTES:
            raise ValueError("product artifact size is outside the allowed limit")
        archive_bytes = output.read_bytes()
        digest = hashlib.sha256(archive_bytes).hexdigest()
        with zipfile.ZipFile(output) as archive:
            entries = archive.infolist()
            names = {item.filename for item in entries}
            if len(names) != len(entries):
                raise ValueError("product archive contains duplicate paths")
            for item in entries:
                name = PurePosixPath(item.filename)
                if name.is_absolute() or ".." in name.parts or "\\" in item.filename:
                    raise ValueError("product archive contains an unsafe path")
                if item.file_size > MAX_ARCHIVE_BYTES:
                    raise ValueError("product archive member exceeds the allowed size")
            missing = sorted(EXPECTED_FILES - names)
            if missing:
                raise ValueError("product archive is missing required files: " + ", ".join(missing))
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("schema") != "aae.game-asset-pack/v1":
                raise ValueError("product manifest schema is invalid")
            checked = 0
            glb_count = 0
            for item in manifest.get("files", []):
                path = item.get("path") if isinstance(item, dict) else None
                if path not in names or path == "manifest.json":
                    raise ValueError("product manifest references an invalid path")
                data = archive.read(path)
                if len(data) != item.get("size_bytes") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
                    raise ValueError("product manifest integrity check failed")
                if path.endswith(".glb"):
                    if len(data) < 20 or data[:4] != b"glTF" or int.from_bytes(data[4:8], "little") != 2:
                        raise ValueError("product contains an invalid GLB file")
                    glb_count += 1
                checked += 1
            if checked < 10 or glb_count != 6:
                raise ValueError("product manifest did not verify the expected model files")
        return archive_bytes, digest, {
            "qa_passed": True,
            "archive_size_bytes": size,
            "archive_sha256": digest,
            "checked_manifest_files": checked,
            "glb_models": glb_count,
            "visual_review": "not_performed",
        }
