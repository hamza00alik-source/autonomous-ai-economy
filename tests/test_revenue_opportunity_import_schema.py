import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ROOT / "cloudflare/worker/migrations/0006_financial_control_foundation.sql",
    ROOT / "cloudflare/worker/migrations/0017_revenue_opportunity_imports.sql",
]


def database():
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    for path in MIGRATIONS:
        db.executescript(path.read_text(encoding="utf-8"))
    db.execute(
        "INSERT INTO financial_participants "
        "(participant_id,participant_type,status,created_at,updated_at) "
        "VALUES ('owner-01','owner','active','now','now')"
    )
    return db


def candidate_values():
    return (
        "owner-01", "taskmarket", "task-001", "Build a small API",
        "https://taskmarket.example/tasks/1", "USDC", "2.00", "1.80",
        "ready_for_owner_review", 90, 80, 100, 1, "[]",
        "2026-11-19T10:00:00.000Z", "2026-11-19T10:05:00.000Z",
    )


def insert_candidate(db, values=None):
    values = values or candidate_values()
    db.execute(
        """
        INSERT INTO revenue_opportunity_imports
          (owner_id,source,external_id,title,url,currency,gross_reward,net_reward,source_status,
           priority_score,fit_score,evidence_confidence,source_escrow_claimed,reasons_json,
           discovered_at,imported_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        values,
    )


def test_imported_opportunities_are_always_unverified_and_unclaimable():
    db = database()
    insert_candidate(db)
    row = db.execute(
        "SELECT review_status,independent_escrow_verified,payment_verified,claim_allowed,source_escrow_claimed "
        "FROM revenue_opportunity_imports WHERE owner_id='owner-01'"
    ).fetchone()
    assert row == ("needs_owner_review", 0, 0, 0, 1)


@pytest.mark.parametrize(
    "changes",
    [
        {"review_status": "ready_for_owner_review"},
        {"independent_escrow_verified": 1},
        {"payment_verified": 1},
        {"claim_allowed": 1},
        {"priority_score": 101},
    ],
)
def test_imported_opportunity_safety_and_score_constraints(changes):
    db = database()
    insert_candidate(db)
    column, value = next(iter(changes.items()))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            f"UPDATE revenue_opportunity_imports SET {column}=? WHERE owner_id='owner-01'",
            (value,),
        )


def test_opportunity_rows_are_owner_scoped_and_idempotent_by_source_id():
    db = database()
    insert_candidate(db)
    updated = list(candidate_values())
    updated[3] = "Updated task title"
    updated[15] = "2026-11-19T11:00:00.000Z"
    db.execute(
        """
        INSERT INTO revenue_opportunity_imports
          (owner_id,source,external_id,title,url,currency,gross_reward,net_reward,source_status,
           priority_score,fit_score,evidence_confidence,source_escrow_claimed,reasons_json,
           discovered_at,imported_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(owner_id,source,external_id) DO UPDATE SET
          title=excluded.title,imported_at=excluded.imported_at
        """,
        updated,
    )
    assert db.execute("SELECT COUNT(*) FROM revenue_opportunity_imports").fetchone()[0] == 1
    assert db.execute("SELECT title FROM revenue_opportunity_imports").fetchone()[0] == "Updated task title"
    with pytest.raises(sqlite3.IntegrityError):
        values = list(candidate_values())
        values[0] = "unknown-owner"
        insert_candidate(db, values)
