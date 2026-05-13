CREATE TABLE IF NOT EXISTS d1_districts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  chamber TEXT NOT NULL,
  district_code TEXT NOT NULL,
  district_number TEXT,
  county TEXT,
  district_name TEXT,

  normalized_lookup TEXT,

  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_d1_districts_unique
ON d1_districts (chamber, district_code);

CREATE INDEX IF NOT EXISTS idx_d1_districts_lookup
ON d1_districts (normalized_lookup);