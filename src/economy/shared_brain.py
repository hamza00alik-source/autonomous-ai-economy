"""Shared, auditable team memory with owner-reviewed learning promotion."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MEMORY_STATUSES = {"proposed", "approved", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _terms(value: str) -> set[str]:
    return {part.casefold() for part in re.findall(r"[A-Za-z0-9_'-]{2,}", value)}


class SharedBrain:
    """One shared SQLite brain. Proposed lessons are invisible to normal recall."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    category TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_by TEXT NOT NULL,
                    status TEXT NOT NULL,
                    review_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    note TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memories(memory_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def propose(
        self, *, title: str, lesson: str, category: str, created_by: str,
        tags: list[str] | None = None, source_refs: list[str] | None = None,
        confidence: float = 0.5,
    ) -> dict[str, Any]:
        title, lesson, category, created_by = (v.strip() for v in (title, lesson, category, created_by))
        if not all((title, lesson, category, created_by)):
            raise ValueError("title, lesson, category, and created_by are required")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        clean_tags = sorted({str(t).strip().casefold() for t in (tags or []) if str(t).strip()})
        refs = [str(ref).strip() for ref in (source_refs or []) if str(ref).strip()]
        memory_id = str(uuid.uuid4())
        created_at = _now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO memories
                (memory_id,title,lesson,category,tags_json,source_refs_json,confidence,created_by,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (memory_id, title, lesson, category, json.dumps(clean_tags), json.dumps(refs),
                 float(confidence), created_by, "proposed", created_at),
            )
            db.execute(
                "INSERT INTO memory_events(memory_id,event_type,actor,note,occurred_at) VALUES(?,?,?,?,?)",
                (memory_id, "proposed", created_by, "Awaiting owner review", created_at),
            )
        return self.get(memory_id)

    def review(self, memory_id: str, *, decision: str, reviewer: str, note: str) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        reviewer, note = reviewer.strip(), note.strip()
        if not reviewer or not note:
            raise ValueError("reviewer and review note are required")
        now = _now()
        with self._connect() as db:
            row = db.execute("SELECT status FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
            if row is None:
                raise KeyError(memory_id)
            if row["status"] != "proposed":
                raise ValueError("only proposed memories can be reviewed; decisions are immutable")
            db.execute(
                "UPDATE memories SET status=?,review_note=?,reviewed_at=? WHERE memory_id=?",
                (decision, note, now, memory_id),
            )
            db.execute(
                "INSERT INTO memory_events(memory_id,event_type,actor,note,occurred_at) VALUES(?,?,?,?,?)",
                (memory_id, decision, reviewer, note, now),
            )
        return self.get(memory_id)

    def get(self, memory_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        if row is None:
            raise KeyError(memory_id)
        return self._decode(row)

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["tags"] = json.loads(item.pop("tags_json"))
        item["source_refs"] = json.loads(item.pop("source_refs_json"))
        return item

    def list_memories(self, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in MEMORY_STATUSES:
            raise ValueError("invalid memory status")
        with self._connect() as db:
            if status:
                rows = db.execute("SELECT * FROM memories WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM memories ORDER BY created_at DESC").fetchall()
        return [self._decode(row) for row in rows]

    def recall(self, query: str, *, limit: int = 8, include_proposed: bool = False) -> list[dict[str, Any]]:
        """Keyword recall; approved lessons only by default."""
        query_terms = _terms(query)
        if not query_terms:
            return []
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        statuses = ("approved", "proposed") if include_proposed else ("approved",)
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM memories WHERE status IN ({placeholders}) ORDER BY created_at DESC",
                statuses,
            ).fetchall()
        scored = []
        for row in rows:
            item = self._decode(row)
            haystack = " ".join([item["title"], item["lesson"], item["category"], *item["tags"]])
            overlap = query_terms & _terms(haystack)
            if overlap:
                item["recall_match_terms"] = sorted(overlap)
                item["recall_score"] = len(overlap) / len(query_terms)
                scored.append(item)
        scored.sort(key=lambda item: (-item["recall_score"], -item["confidence"], item["created_at"]))
        return scored[:limit]

    def events(self, memory_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT event_type,actor,note,occurred_at FROM memory_events WHERE memory_id=? ORDER BY event_id",
                (memory_id,),
            ).fetchall()
        return [dict(row) for row in rows]


class SharedBrainContext:
    """Small injectable adapter any agent can use to read and propose team lessons."""

    def __init__(self, brain: SharedBrain, agent_id: str) -> None:
        if not agent_id.strip():
            raise ValueError("agent_id is required")
        self.brain = brain
        self.agent_id = agent_id

    def recall(self, objective: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return self.brain.recall(objective, limit=limit)

    def propose_learning(
        self, *, title: str, lesson: str, category: str,
        source_refs: list[str] | None = None, tags: list[str] | None = None,
        confidence: float = 0.5,
    ) -> dict[str, Any]:
        return self.brain.propose(
            title=title, lesson=lesson, category=category, created_by=self.agent_id,
            source_refs=source_refs, tags=tags, confidence=confidence,
        )
