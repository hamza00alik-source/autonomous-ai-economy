ALTER TABLE aae_execution_jobs ADD COLUMN owner_approved INTEGER NOT NULL DEFAULT 0 CHECK(owner_approved IN (0,1));
