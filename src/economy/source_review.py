"""Owner-classified review records for retrieved original-source snapshots.

A review is a human assertion about supplied source material, not an automated
fact check. Snapshots remain untrusted and never become validated evidence by
themselves.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

REVIEW_KINDS = {
    "supports_buyer_problem",
    "competitor_offer",
    "cost_reference",
    "legal_policy_reference",
    "market_context",
    "not_relevant",
    "unreliable",
}


def normalize_source_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("reviewed source must be an absolute HTTPS URL without credentials")
    if parsed.port not in (None, 443):
        raise ValueError("only the default HTTPS port is accepted")
    host = parsed.hostname.lower().rstrip(".")
    netloc = f"[{host}]" if ":" in host else host
    path = parsed.path or "/"
    return urlunsplit(("https", netloc, path, parsed.query, ""))


class SourceReviewStore:
    """Stores immutable retrieval snapshots with explicit owner classifications."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS source_reviews (
                    review_id TEXT PRIMARY KEY,
                    normalized_url TEXT NOT NULL UNIQUE,
                    content_sha256 TEXT NOT NULL UNIQUE,
                    publisher_identity TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    classification TEXT NOT NULL CHECK (classification IN
                        ('supports_buyer_problem','competitor_offer','cost_reference',
                         'legal_policy_reference','market_context','not_relevant','unreliable')),
                    finding TEXT NOT NULL,
                    reviewer_note TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def record_review(
        self,
        snapshot: dict,
        *,
        classification: str,
        finding: str,
        reviewer_note: str,
    ) -> dict:
        if classification not in REVIEW_KINDS:
            raise ValueError("unsupported source classification")
        clean_finding = " ".join(finding.split())
        clean_note = " ".join(reviewer_note.split())
        if not clean_finding or not clean_note:
            raise ValueError("an explicit finding and reviewer note are required")
        if snapshot.get("verification_status") != "retrieved_unverified":
            raise ValueError("snapshot must be an explicitly retrieved, unverified source")
        if snapshot.get("buyer_evidence_created") is not False:
            raise ValueError("snapshot must not already claim buyer evidence")
        source_url = snapshot.get("final_url") or snapshot.get("url")
        normalized = normalize_source_url(str(source_url or ""))
        digest = str(snapshot.get("content_sha256") or "").lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("snapshot must include a valid SHA-256 content hash")
        publisher = urlsplit(normalized).hostname or ""
        review_id = hashlib.sha256((normalized + "|" + digest).encode()).hexdigest()[:24]
        reviewed_at = datetime.now(timezone.utc).isoformat()
        snapshot_copy = dict(snapshot)
        # Persist a canonical copy; this workflow never executes page content.
        with self._connect() as conn:
            try:
                conn.execute("""
                    INSERT INTO source_reviews
                    (review_id, normalized_url, content_sha256, publisher_identity,
                     snapshot_json, classification, finding, reviewer_note, reviewed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    review_id, normalized, digest, publisher,
                    json.dumps(snapshot_copy, sort_keys=True), classification,
                    clean_finding[:4000], clean_note[:2000], reviewed_at,
                ))
            except sqlite3.IntegrityError as exc:
                raise ValueError("source URL or content hash was already reviewed; duplicate not counted") from exc
        return self.get(review_id)  # type: ignore[return-value]

    def get(self, review_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM source_reviews WHERE review_id=?", (review_id,)).fetchone()
        return self._as_dict(row) if row else None

    def list_reviews(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM source_reviews ORDER BY reviewed_at").fetchall()
        return [self._as_dict(row) for row in rows]

    @staticmethod
    def _as_dict(row: sqlite3.Row) -> dict:
        return {
            "review_id": row["review_id"],
            "source_url": row["normalized_url"],
            "content_sha256": row["content_sha256"],
            "publisher_identity": row["publisher_identity"],
            "snapshot": json.loads(row["snapshot_json"]),
            "classification": row["classification"],
            "finding": row["finding"],
            "reviewer_note": row["reviewer_note"],
            "reviewed_at": row["reviewed_at"],
            "evidence_created": False,
            "independent_source_claim": False,
            "notice": "Owner-reviewed classification only; not independently verified and not validated buyer evidence.",
        }
