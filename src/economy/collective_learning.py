"""Outcome-backed collective learning; repeated observations create proposals, never approvals."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .shared_brain import SharedBrain


OUTCOME_LABELS = {"worked", "failed", "mixed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollectiveLearningEngine:
    """Stores observed outcomes and proposes cautious lessons from repeated patterns."""

    def __init__(self, path: str | Path, brain: SharedBrain, min_observations: int = 2) -> None:
        if not 2 <= min_observations <= 20:
            raise ValueError("min_observations must be between 2 and 20")
        self.path = str(path)
        self.brain = brain
        self.min_observations = min_observations
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS outcome_observations (
                    observation_id TEXT PRIMARY KEY,
                    pattern_key TEXT NOT NULL,
                    outcome_label TEXT NOT NULL CHECK(outcome_label IN ('worked','failed','mixed')),
                    observation TEXT NOT NULL,
                    observed_by TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_outcomes_pattern
                    ON outcome_observations(pattern_key, outcome_label);
                CREATE TABLE IF NOT EXISTS learning_emissions (
                    pattern_key TEXT NOT NULL,
                    outcome_label TEXT NOT NULL,
                    memory_id TEXT NOT NULL,
                    emitted_at TEXT NOT NULL,
                    PRIMARY KEY(pattern_key, outcome_label)
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def record_outcome(
        self, *, pattern_key: str, outcome_label: str, observation: str,
        observed_by: str, evidence_refs: list[str],
    ) -> dict[str, Any]:
        pattern_key, observation, observed_by = (
            value.strip() for value in (pattern_key, observation, observed_by)
        )
        if not all((pattern_key, observation, observed_by)):
            raise ValueError("pattern_key, observation, and observed_by are required")
        if outcome_label not in OUTCOME_LABELS:
            raise ValueError("outcome_label must be worked, failed, or mixed")
        refs = [str(ref).strip() for ref in evidence_refs if str(ref).strip()]
        if not refs:
            raise ValueError("at least one evidence reference is required")
        observation_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute(
                """INSERT INTO outcome_observations
                (observation_id,pattern_key,outcome_label,observation,observed_by,evidence_refs_json,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (observation_id, pattern_key, outcome_label, observation, observed_by,
                 json.dumps(refs), _now()),
            )
        proposal = self._maybe_propose(pattern_key, outcome_label)
        return {
            "observation_id": observation_id,
            "pattern_key": pattern_key,
            "outcome_label": outcome_label,
            "learning_proposal": proposal,
        }

    def _maybe_propose(self, pattern_key: str, outcome_label: str) -> dict[str, Any] | None:
        with self._connect() as db:
            emitted = db.execute(
                "SELECT memory_id FROM learning_emissions WHERE pattern_key=? AND outcome_label=?",
                (pattern_key, outcome_label),
            ).fetchone()
            if emitted:
                return self.brain.get(emitted["memory_id"])
            rows = db.execute(
                """SELECT * FROM outcome_observations
                WHERE pattern_key=? AND outcome_label=? ORDER BY created_at""",
                (pattern_key, outcome_label),
            ).fetchall()
        if len(rows) < self.min_observations:
            return None

        # Preserve exact recorded observations and all references; do not invent a causal claim.
        observations = [dict(row) for row in rows]
        refs = sorted({ref for row in observations for ref in json.loads(row["evidence_refs_json"])})
        details = " | ".join(row["observation"] for row in observations)
        lesson = (
            f"Repeated observed pattern '{pattern_key}' was labelled '{outcome_label}' "
            f"in {len(observations)} recorded case(s). Observations: {details}. "
            "This is a hypothesis from recorded cases, not proof of causation or a guaranteed result."
        )
        confidence = min(0.9, len(observations) / (len(observations) + 2))
        memory = self.brain.propose(
            title=f"Outcome pattern: {pattern_key}",
            lesson=lesson,
            category="observed_outcome_pattern",
            created_by="collective-learning-engine",
            tags=["outcome", outcome_label, "needs-owner-review"],
            source_refs=refs,
            confidence=confidence,
        )
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO learning_emissions(pattern_key,outcome_label,memory_id,emitted_at) VALUES(?,?,?,?)",
                (pattern_key, outcome_label, memory["memory_id"], _now()),
            )
            emitted = db.execute(
                "SELECT memory_id FROM learning_emissions WHERE pattern_key=? AND outcome_label=?",
                (pattern_key, outcome_label),
            ).fetchone()
        # If two workers race, return the single proposal recorded in the emission table.
        return self.brain.get(emitted["memory_id"]) if emitted else memory

    def summarize(self) -> dict[str, Any]:
        with self._connect() as db:
            total = db.execute("SELECT COUNT(*) AS n FROM outcome_observations").fetchone()["n"]
            patterns = db.execute(
                "SELECT pattern_key,outcome_label,COUNT(*) AS observations "
                "FROM outcome_observations GROUP BY pattern_key,outcome_label "
                "ORDER BY pattern_key,outcome_label"
            ).fetchall()
            emissions = db.execute("SELECT COUNT(*) AS n FROM learning_emissions").fetchone()["n"]
        return {
            "observations_recorded": total,
            "learning_proposals_emitted": emissions,
            "minimum_observations_per_pattern": self.min_observations,
            "patterns": [dict(row) for row in patterns],
            "automatic_approval": False,
        }
