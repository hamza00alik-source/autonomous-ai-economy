import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


MIGRATIONS = [
    Path(__file__).resolve().parents[1] / "cloudflare" / "worker" / "migrations" / name
    for name in ("0006_financial_control_foundation.sql", "0007_financial_control_enforcement.sql")
]


def _database():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    for migration in MIGRATIONS:
        connection.executescript(migration.read_text(encoding="utf-8"))
    return connection


def _participants(db):
    db.execute(
        "INSERT INTO financial_participants "
        "(participant_id,participant_type,status,created_at,updated_at) "
        "VALUES ('owner-01','owner','active','now','now')"
    )
    db.execute(
        "INSERT INTO financial_participants "
        "(participant_id,participant_type,status,owner_id,created_at,updated_at) "
        "VALUES ('operator-01','operator','active','owner-01','now','now')"
    )
    db.execute(
        "INSERT INTO financial_participants "
        "(participant_id,participant_type,status,owner_id,operator_id,created_at,updated_at) "
        "VALUES ('agent-01','agent','active','owner-01','operator-01','now','now')"
    )


def _accounts(db):
    db.executemany(
        "INSERT INTO financial_accounts "
        "(account_id,owner_id,agent_id,account_type,currency,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'active','now','now')",
        [
            ("agent-account", "owner-01", "agent-01", "agent_operating", "USD"),
            ("expense-account", "owner-01", None, "operating_expense", "USD"),
            ("eur-account", "owner-01", None, "operating_expense", "EUR"),
        ],
    )


def _journal(db):
    db.execute(
        "INSERT INTO financial_journal_transactions "
        "(transaction_id,owner_id,idempotency_key,payload_hash,source_type,source_reference,currency,status,description,created_at) "
        "VALUES ('txn-01','owner-01','idem-0001','hash','expense','expense-01','USD','posted','test expense','now')"
    )


def _policy(db, version=1, per_transaction_limit=1000, daily_spend_limit=5000):
    db.execute(
        "INSERT INTO financial_policies "
        "(policy_id,version,owner_id,agent_id,signer_id,currency,per_transaction_limit_minor,"
        "daily_spend_limit_minor,allowed_destinations_json,canonical_payload,signature_base64url,"
        "signer_key_fingerprint,status,created_at,updated_at) "
        "VALUES ('policy-01',?,'owner-01','agent-01','operator-01','USD',?,?, '[\"provider:exact\"]',"
        "'{}','signature','fingerprint','active','now','now')",
        (version, per_transaction_limit, daily_spend_limit),
    )


def test_cloud_financial_migration_creates_owner_bound_policy_and_ledger_schema():
    db = _database()
    _participants(db)
    _accounts(db)
    _policy(db)
    _journal(db)
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'financial_%'"
        )
    }
    assert {
        "financial_participants",
        "financial_accounts",
        "financial_journal_transactions",
        "financial_journal_postings",
        "financial_settlement_receipts",
        "financial_policies",
        "financial_budget_reservations",
        "financial_expense_schedules",
        "financial_audit_events",
    } <= tables


@pytest.mark.parametrize(
    "participant_type,owner_id,operator_id",
    [
        ("owner", "owner-01", None),
        ("operator", None, None),
        ("agent", "owner-01", None),
    ],
)
def test_participant_relationship_shape_is_constrained(participant_type, owner_id, operator_id):
    db = _database()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO financial_participants "
            "(participant_id,participant_type,status,owner_id,operator_id,created_at,updated_at) "
            "VALUES ('bad-01',?,'active',?,?,'now','now')",
            (participant_type, owner_id, operator_id),
        )


def test_posting_trigger_requires_active_same_owner_same_currency_account():
    db = _database()
    _participants(db)
    _accounts(db)
    _journal(db)
    db.execute(
        "INSERT INTO financial_journal_postings "
        "(transaction_id,line_number,account_id,direction,amount_minor,currency,created_at) "
        "VALUES ('txn-01',1,'agent-account','debit',100,'USD','now')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="posting currency"):
        db.execute(
            "INSERT INTO financial_journal_postings "
            "(transaction_id,line_number,account_id,direction,amount_minor,currency,created_at) "
            "VALUES ('txn-01',2,'eur-account','credit',100,'USD','now')"
        )
    db.execute("UPDATE financial_accounts SET status='frozen' WHERE account_id='expense-account'")
    with pytest.raises(sqlite3.IntegrityError, match="posting currency"):
        db.execute(
            "INSERT INTO financial_journal_postings "
            "(transaction_id,line_number,account_id,direction,amount_minor,currency,created_at) "
            "VALUES ('txn-01',3,'expense-account','credit',100,'USD','now')"
        )


def test_posted_journal_rows_are_append_only():
    db = _database()
    _participants(db)
    _accounts(db)
    _journal(db)
    db.execute(
        "INSERT INTO financial_journal_postings "
        "(transaction_id,line_number,account_id,direction,amount_minor,currency,created_at) "
        "VALUES ('txn-01',1,'agent-account','debit',100,'USD','now')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE financial_journal_transactions SET description='tampered' WHERE transaction_id='txn-01'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("DELETE FROM financial_journal_postings WHERE transaction_id='txn-01'")


def test_signed_policy_content_is_immutable_and_versions_are_monotonic():
    db = _database()
    _participants(db)
    _policy(db, 1)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE financial_policies SET canonical_payload='tampered' WHERE policy_id='policy-01'")
    with pytest.raises(sqlite3.IntegrityError, match="monotonically"):
        _policy(db, 1)
    db.execute("UPDATE financial_policies SET status='superseded',updated_at='later' WHERE policy_id='policy-01'")
    _policy(db, 2)
    assert db.execute(
        "SELECT version,status FROM financial_policies ORDER BY version"
    ).fetchall() == [(1, "superseded"), (2, "active")]


def test_audit_events_are_owner_scoped_and_append_only():
    db = _database()
    _participants(db)
    db.execute(
        "INSERT INTO financial_audit_events "
        "(event_id,owner_id,actor_id,event_type,target_type,target_id,details_json,created_at) "
        "VALUES ('audit-01','owner-01','operator-01','policy.created','policy','policy-01','{}','now')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE financial_audit_events SET details_json='tampered' WHERE event_id='audit-01'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM financial_audit_events WHERE event_id='audit-01'")
    with pytest.raises(sqlite3.IntegrityError, match="belong to owner"):
        db.execute(
            "INSERT INTO financial_audit_events "
            "(event_id,owner_id,actor_id,event_type,target_type,target_id,details_json,created_at) "
            "VALUES ('audit-02','owner-01','unknown-actor','policy.created','policy','policy-01','{}','now')"
        )


def _fund_agent(db, amount=10000):
    db.execute(
        "INSERT INTO financial_journal_transactions "
        "(transaction_id,owner_id,idempotency_key,payload_hash,source_type,source_reference,currency,status,description,created_at) "
        "VALUES ('allocation-01','owner-01','allocation-idem-01','hash','allocation','receipt-01','USD','posted','fund agent','2026-11-19T00:00:00.000Z')"
    )
    db.executemany(
        "INSERT INTO financial_journal_postings "
        "(transaction_id,line_number,account_id,direction,amount_minor,currency,created_at) VALUES ('allocation-01',?,?,?,?,?,?)",
        [
            (1, "expense-account", "debit", amount, "USD", "2026-11-19T00:00:00.000Z"),
            (2, "agent-account", "credit", amount, "USD", "2026-11-19T00:00:00.000Z"),
        ],
    )


def _unpause(db):
    db.execute(
        "INSERT INTO financial_control_state(owner_id,emergency_paused,pause_reason,changed_at) "
        "VALUES ('owner-01',0,'owner explicitly enabled cloud spending','2026-11-19T00:00:00.000Z')"
    )


def _reservation(db, reservation_id="reservation-01", amount=1000, destination="provider:exact", created_at=None):
    if created_at is None:
        created = datetime.now(timezone.utc)
    else:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    created_at = created.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    expires_at = (created + timedelta(hours=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    db.execute(
        "INSERT INTO financial_budget_reservations "
        "(reservation_id,owner_id,agent_id,policy_id,policy_version,idempotency_key,destination,currency,amount_minor,status,expires_at,created_at,updated_at) "
        "VALUES (?, 'owner-01','agent-01','policy-01',1,?,?, 'USD',?,'reserved',?,?,?)",
        (reservation_id, "idem-" + reservation_id, destination, amount, expires_at, created_at, created_at),
    )


def test_cloud_reservations_fail_closed_without_explicit_owner_unpause():
    db = _database()
    _participants(db)
    _accounts(db)
    _policy(db)
    _fund_agent(db)
    with pytest.raises(sqlite3.IntegrityError, match="pause"):
        _reservation(db)


def test_cloud_reservations_enforce_signed_destination_and_per_transaction_limit():
    db = _database()
    _participants(db)
    _accounts(db)
    _policy(db)
    _fund_agent(db)
    _unpause(db)
    with pytest.raises(sqlite3.IntegrityError, match="authorization"):
        _reservation(db, destination="provider:other")
    with pytest.raises(sqlite3.IntegrityError, match="authorization"):
        _reservation(db, amount=1001)


def test_cloud_reservations_enforce_agent_budget_and_daily_policy_limit():
    db = _database()
    _participants(db)
    _accounts(db)
    _policy(db, per_transaction_limit=4000)
    _fund_agent(db)
    _unpause(db)
    _reservation(db, "reservation-a", 3000)
    with pytest.raises(sqlite3.IntegrityError, match="daily spend limit"):
        _reservation(db, "reservation-b", 2500)

    underfunded = _database()
    _participants(underfunded)
    _accounts(underfunded)
    _policy(underfunded, per_transaction_limit=4000)
    _fund_agent(underfunded, amount=4000)
    _unpause(underfunded)
    _reservation(underfunded, "reservation-c", 3000)
    with pytest.raises(sqlite3.IntegrityError, match="insufficient available agent budget"):
        _reservation(underfunded, "reservation-d", 2500)


def test_cloud_recurring_occurrences_are_policy_bound_and_idempotent():
    db = _database()
    _participants(db)
    _accounts(db)
    _policy(db)
    db.execute(
        "INSERT INTO financial_expense_schedules "
        "(schedule_id,owner_id,agent_id,policy_id,policy_version,destination,currency,amount_minor,interval_seconds,next_due_at,status,created_at,updated_at) "
        "VALUES ('schedule-01','owner-01','agent-01','policy-01',1,'provider:exact','USD',500,3600,'2026-11-19T01:00:00Z','active','now','now')"
    )
    db.execute(
        "INSERT INTO financial_expense_occurrences "
        "(occurrence_id,schedule_id,owner_id,agent_id,policy_id,policy_version,due_at,idempotency_key,status,created_at,updated_at) "
        "VALUES ('occurrence-01','schedule-01','owner-01','agent-01','policy-01',1,'2026-11-19T01:00:00Z','occurrence-idem-01','claimed','now','now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO financial_expense_occurrences "
            "(occurrence_id,schedule_id,owner_id,agent_id,policy_id,policy_version,due_at,idempotency_key,status,created_at,updated_at) "
            "VALUES ('occurrence-02','schedule-01','owner-01','agent-01','policy-01',1,'2026-11-19T01:00:00Z','occurrence-idem-02','claimed','now','now')"
        )
