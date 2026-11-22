ALTER TABLE aae_jobbi_discoveries ADD COLUMN reward_amount TEXT;
ALTER TABLE aae_jobbi_discoveries ADD COLUMN reward_usd_estimate REAL;
ALTER TABLE aae_jobbi_discoveries ADD COLUMN payout_network TEXT;
ALTER TABLE aae_jobbi_discoveries ADD COLUMN payout_region_status TEXT;
ALTER TABLE aae_jobbi_discoveries ADD COLUMN payout_priority INTEGER NOT NULL DEFAULT 99;
CREATE INDEX IF NOT EXISTS idx_jobbi_payout_priority
  ON aae_jobbi_discoveries(payout_priority, payout_grade, last_seen_at);
