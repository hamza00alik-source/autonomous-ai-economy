-- Fail-closed Base indexer incident latch.
-- A checkpoint mismatch cannot establish a safe reorg depth. Freeze settlement
-- and revoke all automatic delivery until a human reconciles the affected ledger.
ALTER TABLE base_usdc_indexer_state ADD COLUMN halted_at TEXT;
ALTER TABLE base_usdc_indexer_state ADD COLUMN halt_reason TEXT;
