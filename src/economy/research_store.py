"""Persistent local storage for unverified research discovery leads."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .research_sources import ResearchCandidate


class ResearchCandidateStore:
    """Deduplicates candidates and records explicit owner review decisions.

    Review status is workflow metadata only; it never creates buyer evidence,
    verifies sales, or approves publishing/spending.
    """

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'unverified'
                        CHECK (review_status IN ('unverified', 'owner_reviewed')),
                    review_note TEXT,
                    reviewed_at TEXT
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def save_many(self, candidates: list[ResearchCandidate]) -> dict[str, int]:
        inserted = 0
        existing = 0
        with self._connect() as conn:
            for candidate in candidates:
                payload = json.dumps(asdict(candidate), sort_keys=True)
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO research_candidates
                       (candidate_id, payload, review_status)
                       VALUES (?, ?, 'unverified')""",
                    (candidate.candidate_id, payload),
                )
                if cursor.rowcount:
                    inserted += 1
                else:
                    existing += 1
        return {"inserted": inserted, "already_present": existing}

    def list_candidates(self, review_status: str | None = None) -> list[dict]:
        if review_status not in (None, "unverified", "owner_reviewed"):
            raise ValueError("invalid review status")
        with self._connect() as conn:
            if review_status:
                rows = conn.execute(
                    "SELECT * FROM research_candidates WHERE review_status=? ORDER BY rowid",
                    (review_status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_candidates ORDER BY rowid"
                ).fetchall()
        return [self._row_dict(row) for row in rows]

    def get(self, candidate_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        return self._row_dict(row) if row else None

    def mark_owner_reviewed(self, candidate_id: str, note: str) -> dict:
        clean_note = " ".join(note.split())
        if not clean_note:
            raise ValueError("a non-empty owner review note is required")
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE research_candidates
                   SET review_status='owner_reviewed', review_note=?,
                       reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                   WHERE candidate_id=? AND review_status='unverified'""",
                (clean_note[:2000], candidate_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("candidate not found or already reviewed")
        result = self.get(candidate_id)
        assert result is not None
        return result

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict:
        return {
            "candidate": json.loads(row["payload"]),
            "review_status": row["review_status"],
            "review_note": row["review_note"],
            "reviewed_at": row["reviewed_at"],
        }
