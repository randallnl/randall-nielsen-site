CREATE TABLE IF NOT EXISTS d1_legislator_photos (
  employeeno INTEGER PRIMARY KEY,
  personid INTEGER,
  firstname TEXT,
  lastname TEXT,
  filename TEXT NOT NULL,
  photo_url TEXT NOT NULL,
  source TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_d1_legislator_photos_personid
ON d1_legislator_photos (personid);

CREATE INDEX IF NOT EXISTS idx_d1_legislator_photos_name
ON d1_legislator_photos (lastname, firstname);