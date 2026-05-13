CREATE TABLE IF NOT EXISTS d1_legislators (
  personid INTEGER PRIMARY KEY,
  employeeno INTEGER,
  firstname TEXT,
  lastname TEXT,
  middlename TEXT,
  legislativebody TEXT,
  active INTEGER,
  seatno TEXT,
  countycode TEXT,
  district TEXT,
  party TEXT,
  address TEXT,
  address2 TEXT,
  city TEXT,
  zipcode TEXT,
  emailaddress TEXT,
  gendercode TEXT,
  secretaryid INTEGER,
  database_name TEXT
);

CREATE INDEX IF NOT EXISTS idx_d1_legislators_body
ON d1_legislators (legislativebody);

CREATE INDEX IF NOT EXISTS idx_d1_legislators_district
ON d1_legislators (district);

CREATE INDEX IF NOT EXISTS idx_d1_legislators_city
ON d1_legislators (city);

CREATE INDEX IF NOT EXISTS idx_d1_legislators_employee
ON d1_legislators (employeeno);