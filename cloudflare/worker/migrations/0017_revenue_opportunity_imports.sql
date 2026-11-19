-- Owner-scoped shortlist imported from the local read-only marketplace revenue engine.
-- Imported claims are untrusted source data: no imported row is independently escrow-verified,
-- payment-verified, claimable, or revenue. Owner review is always required.
CREATE TABLE IF NOT EXISTS revenue_opportunity_imports (
  owner_id TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('basedagents','jobbi','taskmarket')),
  external_id TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  currency TEXT,
  gross_reward TEXT,
  net_reward TEXT,
  source_status TEXT NOT NULL CHECK(source_status IN ('ready_for_owner_review','needs_owner_review')),
  priority_score INTEGER NOT NULL CHECK(priority_score BETWEEN 0 AND 100),
  fit_score INTEGER NOT NULL CHECK(fit_score BETWEEN 0 AND 100),
  evidence_confidence INTEGER NOT NULL CHECK(evidence_confidence BETWEEN 0 AND 100),
  source_escrow_claimed INTEGER NOT NULL CHECK(source_escrow_claimed IN (0,1)),
  reasons_json TEXT NOT NULL,
  discovered_at TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  review_status TEXT NOT NULL DEFAULT 'needs_owner_review' CHECK(review_status='needs_owner_review'),
  independent_escrow_verified INTEGER NOT NULL DEFAULT 0 CHECK(independent_escrow_verified=0),
  payment_verified INTEGER NOT NULL DEFAULT 0 CHECK(payment_verified=0),
  claim_allowed INTEGER NOT NULL DEFAULT 0 CHECK(claim_allowed=0),
  PRIMARY KEY(owner_id,source,external_id),
  FOREIGN KEY(owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_revenue_opportunity_owner_priority
  ON revenue_opportunity_imports(owner_id,priority_score DESC,imported_at DESC);
CREATE INDEX IF NOT EXISTS idx_revenue_opportunity_owner_review
  ON revenue_opportunity_imports(owner_id,review_status,source);
