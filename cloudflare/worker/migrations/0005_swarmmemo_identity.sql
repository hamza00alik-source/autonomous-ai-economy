CREATE TABLE IF NOT EXISTS swarmmemo_identity_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  state TEXT NOT NULL CHECK (state IN ('creating','created','uncertain','failed')),
  fingerprint TEXT,
  handle TEXT,
  created_at TEXT,
  updated_at TEXT NOT NULL
);
