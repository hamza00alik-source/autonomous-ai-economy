import sqlite3
from pathlib import Path

import pytest


MIGRATIONS = [
    Path(__file__).resolve().parents[1] / "cloudflare" / "worker" / "migrations" / name
    for name in (
        "0006_financial_control_foundation.sql",
        "0007_financial_control_enforcement.sql",
        "0008_owner_key_enrollment.sql",
        "0009_agent_receiving_wallets.sql",
        "0010_receiving_payment_observations.sql",
        "0011_asset_aware_receiving_ledger.sql",
    )
]


def database():
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    for path in MIGRATIONS:
        db.executescript(path.read_text(encoding="utf-8"))
    db.execute("INSERT INTO financial_participants(participant_id,participant_type,status,created_at,updated_at) VALUES('owner-01','owner','active','now','now')")
    db.execute("INSERT INTO financial_participants(participant_id,participant_type,status,owner_id,created_at,updated_at) VALUES('operator-01','operator','active','owner-01','now','now')")
    db.execute("INSERT INTO financial_participants(participant_id,participant_type,status,owner_id,operator_id,created_at,updated_at) VALUES('agent-01','agent','active','owner-01','operator-01','now','now')")
    db.execute("""INSERT INTO financial_agent_receiving_wallets
      (wallet_id,owner_id,agent_id,network,chain_id,asset_code,token_contract,token_decimals,receiving_address,status,signer_key_fingerprint,registration_payload_hash,registration_signature,created_at,updated_at)
      VALUES('wallet-01','owner-01','agent-01','base-mainnet',8453,'USDC','0x833589fcd6ed6e08f4c7c32d4f71b54bda02913',6,'0x1111111111111111111111111111111111111111','active','fingerprint','payload-hash','signature','now','now')""")
    db.execute("""INSERT INTO financial_receiving_invoices
      (invoice_id,owner_id,agent_id,wallet_id,order_id,amount_minor,asset_code,network,chain_id,token_contract,receiving_address,payment_uri,description,status,expires_at,created_at,updated_at)
      VALUES('invoice-01','owner-01','agent-01','wallet-01','order-01',2500000,'USDC','base-mainnet',8453,'0x833589fcd6ed6e08f4c7c32d4f71b54bda02913','0x1111111111111111111111111111111111111111','ethereum:...','test item','awaiting_payment','2099-01-01T00:00:00Z','now','now')""")
    db.execute("""INSERT INTO financial_receiving_payment_observations
      (observation_id,owner_id,agent_id,invoice_id,network,tx_hash,block_number,block_hash,amount_minor,matched_log_indices_json,status,evidence_json,observed_at)
      VALUES('observation-01','owner-01','agent-01','invoice-01','base-mainnet',?,100,?,2500000,'[1]','confirmed','{}','now')""",
      ("0x" + "a" * 64, "0x" + "b" * 64))
    return db


def test_all_asset_ledger_migrations_apply_and_confirmed_receipt_can_be_journaled():
    db = database()
    db.execute("""INSERT INTO financial_asset_accounts
      (account_id,owner_id,agent_id,wallet_id,account_type,network,chain_id,asset_code,token_contract,token_decimals,status,created_at,updated_at)
      VALUES('pending-wallet','owner-01','agent-01','wallet-01','agent_pending_custody','base-mainnet',8453,'USDC','0x833589fcd6ed6e08f4c7c32d4f71b54bda02913',6,'active','now','now')""")
    db.execute("""INSERT INTO financial_asset_accounts
      (account_id,owner_id,agent_id,wallet_id,account_type,network,chain_id,asset_code,token_contract,token_decimals,status,created_at,updated_at)
      VALUES('pending-revenue','owner-01','agent-01',NULL,'agent_pending_revenue','base-mainnet',8453,'USDC','0x833589fcd6ed6e08f4c7c32d4f71b54bda02913',6,'active','now','now')""")
    db.execute("""INSERT INTO financial_asset_journal_transactions
      (transaction_id,owner_id,idempotency_key,payload_hash,source_type,source_reference,network,chain_id,asset_code,token_contract,token_decimals,status,description,created_at)
      VALUES('asset-txn-01','owner-01','receiving-payment:invoice-01','hash','receiving_payment','invoice-01','base-mainnet',8453,'USDC','0x833589fcd6ed6e08f4c7c32d4f71b54bda02913',6,'posted','confirmed receipt','now')""")
    db.executemany("""INSERT INTO financial_asset_journal_postings
      (transaction_id,line_number,account_id,direction,amount_minor,network,chain_id,asset_code,token_contract,token_decimals,created_at)
      VALUES('asset-txn-01',?,?,?,?,8453,'USDC','0x833589fcd6ed6e08f4c7c32d4f71b54bda02913',6,'now')""",
      [(1,'pending-wallet','debit',2500000,'base-mainnet'),(2,'pending-revenue','credit',2500000,'base-mainnet')])
    postings = db.execute("SELECT direction,amount_minor FROM financial_asset_journal_postings ORDER BY line_number").fetchall()
    assert postings == [('debit', 2500000), ('credit', 2500000)]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE financial_asset_journal_transactions SET description='tampered' WHERE transaction_id='asset-txn-01'")


def test_receiving_payment_asset_journal_rejects_unconfirmed_or_mismatched_evidence():
    db = database()
    db.execute("UPDATE financial_receiving_payment_observations SET status='review' WHERE invoice_id='invoice-01'")
    with pytest.raises(sqlite3.IntegrityError, match="confirmed chain payment evidence required"):
        db.execute("""INSERT INTO financial_asset_journal_transactions
          (transaction_id,owner_id,idempotency_key,payload_hash,source_type,source_reference,network,chain_id,asset_code,token_contract,token_decimals,status,description,created_at)
          VALUES('asset-txn-02','owner-01','receiving-payment:invoice-01','hash','receiving_payment','invoice-01','base-mainnet',8453,'USDC','0x833589fcd6ed6e08f4c7c32d4f71b54bda02913',6,'posted','bad','now')""")
