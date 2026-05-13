CREATE TABLE IF NOT EXISTS d1_district_mapping (
  body TEXT NOT NULL,
  county INTEGER,
  district INTEGER NOT NULL,
  district_label TEXT NOT NULL,
  communities_represented TEXT NOT NULL,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (body, county, district)
);

CREATE INDEX IF NOT EXISTS idx_d1_district_mapping_label
ON d1_district_mapping (district_label);

CREATE INDEX IF NOT EXISTS idx_d1_district_mapping_body_district
ON d1_district_mapping (body, district);