"""Bounded execution worker for owner-approved, allowlisted deliverables.

The worker runs built-in Python producers only. It never evaluates task text,
shell commands, downloaded code, plugins, or arbitrary model-generated code.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import zipfile
from typing import Any, Callable

from .fulfillment import FulfillmentError, FulfillmentStore

MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
EXPECTED_ASSETS = {
    "assets/mana_crystal.glb", "assets/health_vial.glb",
    "assets/rune_altar.glb", "assets/supply_chest.glb",
    "assets/coin_stack.glb", "preview.glb",
    "godot/MOBAObjectiveProps.tscn", "project.godot",
    "manifest.json", "README.md", "LICENSE.txt", "listing-copy.md",
}


class ExecutionError(RuntimeError):
    """Raised when an approved job cannot be safely executed or verified."""


class ApprovedExecutionWorker:
    """Execute one approved job using an explicitly allowlisted built-in agent."""

    def __init__(
        self,
        fulfillment: FulfillmentStore,
        artifact_root: str | Path,
        *,
        identity_verifier: Callable[[str, str], bool] | None,
        execution_approval_verifier: Callable[[str, str, str], bool] | None,
    ):
        if identity_verifier is None or execution_approval_verifier is None:
            raise ValueError("identity and execution-approval verifiers are mandatory")
        self.fulfillment = fulfillment
        self.artifact_root = Path(artifact_root).resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.identity_verifier = identity_verifier
        self.execution_approval_verifier = execution_approval_verifier
        self.db_path = self.artifact_root / "execution-runs.sqlite3"
        with sqlite3.connect(self.db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS execution_runs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                artifact_path TEXT,
                artifact_sha256 TEXT,
                result_json TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _verify_glb(data: bytes) -> bool:
        return len(data) >= 20 and data[:4] == b"glTF" and int.from_bytes(data[4:8], "little") == 2

    def _qa_archive(self, archive_path: Path) -> dict[str, Any]:
        if not archive_path.is_file():
            raise ExecutionError("producer did not create an artifact")
        size = archive_path.stat().st_size
        if size <= 0 or size > MAX_ARCHIVE_BYTES:
            raise ExecutionError("artifact size is outside the allowed limit")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                names = {item.filename for item in infos}
                if len(names) != len(infos):
                    raise ExecutionError("archive contains duplicate paths")
                for item in infos:
                    name = PurePosixPath(item.filename)
                    if name.is_absolute() or ".." in name.parts or "\\" in item.filename:
                        raise ExecutionError("archive contains an unsafe path")
                    if item.file_size > MAX_ARCHIVE_BYTES:
                        raise ExecutionError("archive member exceeds the allowed size")
                missing = sorted(EXPECTED_ASSETS - names)
                if missing:
                    raise ExecutionError("archive is missing required product files: " + ", ".join(missing))
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("schema") != "aae.game-asset-pack/v1":
                    raise ExecutionError("unsupported product manifest schema")
                checked = 0
                for item in manifest.get("files", []):
                    path = item.get("path")
                    if path not in names or path == "manifest.json":
                        raise ExecutionError("manifest references an invalid file")
                    data = archive.read(path)
                    if len(data) != item.get("size_bytes") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
                        raise ExecutionError("manifest integrity check failed: " + str(path))
                    if path.endswith(".glb") and not self._verify_glb(data):
                        raise ExecutionError("invalid glTF binary: " + path)
                    checked += 1
                if checked < 10:
                    raise ExecutionError("manifest did not contain enough verified files")
                return {
                    "qa_passed": True,
                    "checked_manifest_files": checked,
                    "glb_models": 6,
                    "archive_size_bytes": size,
                    "archive_sha256": self._sha256(archive_path),
                    "limitations": [
                        "Automated structural QA only; no visual human review.",
                        "Godot headless import/launch is separately covered by CI.",
                        "No sales, marketplace acceptance or customer compatibility is implied.",
                    ],
                }
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            raise ExecutionError("artifact archive or manifest is invalid") from exc

    def execute(self, job_id: str, *, owner_execution_approval: str) -> dict[str, Any]:
        job = self.fulfillment.get(job_id)
        if job is None:
            raise ExecutionError("unknown fulfillment job")
        if job.source != "internal":
            raise ExecutionError("this producer is restricted to internal product jobs")
        if job.agent_id != "game-asset-builder":
            raise ExecutionError("no execution handler is registered for this agent")
        if not self.identity_verifier(job.agent_id, job.agent_key_fingerprint):
            raise ExecutionError("agent identity verification failed")
        if not owner_execution_approval or not self.execution_approval_verifier(
            owner_execution_approval, job_id, "execute"
        ):
            raise ExecutionError("fresh owner approval for execution is required")

        spec = job.payload.get("execution_spec")
        if spec != {"kind": "moba_objective_props_v1"}:
            raise ExecutionError("job does not match the allowlisted execution specification")

        with sqlite3.connect(self.db_path, timeout=10, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM execution_runs WHERE job_id=?", (job_id,)).fetchone()
            if row and row[1] == "completed":
                db.execute("COMMIT")
                return json.loads(row[4])
            if row and row[1] == "running":
                db.execute("ROLLBACK")
                raise ExecutionError("execution is already running")
            if job.state != "in_progress":
                db.execute("ROLLBACK")
                raise ExecutionError("job must be owner-approved and in_progress")
            attempts = (row[5] if row else 0) + 1
            if attempts > 2:
                db.execute("ROLLBACK")
                raise ExecutionError("execution retry limit reached")
            db.execute("""INSERT INTO execution_runs(job_id,status,attempts)
                VALUES(?,'running',?) ON CONFLICT(job_id) DO UPDATE SET
                status='running', attempts=excluded.attempts, updated_at=CURRENT_TIMESTAMP""",
                (job_id, attempts))
            db.execute("COMMIT")

        job_dir = (self.artifact_root / job_id).resolve()
        if self.artifact_root not in job_dir.parents:
            raise ExecutionError("artifact path escaped the configured root")
        job_dir.mkdir(parents=True, exist_ok=True)
        target = job_dir / "moba-objective-props.zip"
        try:
            from .game_asset_pack import GameAssetBuilderAgent
            result = GameAssetBuilderAgent().build(target)
            qa = self._qa_archive(target)
            digest = qa["archive_sha256"]
            evidence = {
                "agent_id": job.agent_id,
                "artifact_name": target.name,
                "artifact_sha256": digest,
                "artifact_size_bytes": qa["archive_size_bytes"],
                "qa_passed": True,
                "published": False,
                "submitted": False,
            }
            self.fulfillment.transition(
                job_id, "qa", actor="execution-worker",
                idempotency_key=f"execution-qa:{job_id}",
                evidence=evidence,
            )
            ready = self.fulfillment.transition(
                job_id, "delivery_ready", actor="qa-worker",
                idempotency_key=f"execution-ready:{job_id}",
                evidence=qa,
            )
            final = {
                "job_id": job_id,
                "state": ready.state,
                "agent_id": job.agent_id,
                "artifact_path": str(target),
                "artifact_sha256": digest,
                "artifact_size_bytes": qa["archive_size_bytes"],
                "qa": qa,
                "published": False,
                "submitted": False,
                "sales_verified": False,
            }
            with sqlite3.connect(self.db_path) as db:
                db.execute("""UPDATE execution_runs SET status='completed',
                    artifact_path=?,artifact_sha256=?,result_json=?,updated_at=CURRENT_TIMESTAMP
                    WHERE job_id=?""",
                    (str(target), digest, json.dumps(final, sort_keys=True), job_id))
            return final
        except Exception as exc:
            with sqlite3.connect(self.db_path) as db:
                db.execute("""UPDATE execution_runs SET status='failed',
                    updated_at=CURRENT_TIMESTAMP WHERE job_id=?""", (job_id,))
            if isinstance(exc, (ExecutionError, FulfillmentError)):
                raise
            raise ExecutionError(f"approved agent execution failed: {type(exc).__name__}") from exc
