# Legislator Export & D1 Upload Workflow

This document explains how NH Deserves Better exports legislator data from the local PostgreSQL database and uploads it into Cloudflare D1 for use in the public API and website.

---

# Overview

The workflow is:

```txt
NH General Court SQL Database
        ↓
Local PostgreSQL Sync
        ↓
Legislator Export SQL Generation
        ↓
Cloudflare D1 Upload
        ↓
Public API + Astro Frontend
```

The purpose of this workflow is to:
- maintain a local working copy of legislative data
- selectively publish cleaned legislator data
- support representative lookup tools
- support accountability scoring and vote tracking

---

# Source Table

Legislator data originates from:

```txt
raw.legislators
```

This table is synced locally from the NH General Court SQL database.

---

# Important Schema Notes

The `raw.legislators` table DOES NOT contain:

```txt
sessionyear
```

This is important because:
- filtering legislators by sessionyear will fail
- current legislators should instead be filtered using:

```sql
WHERE active = true
```

---

# Relevant Legislator Columns

| Column | Purpose |
|---|---|
| personid | Primary legislator identity key |
| employeeno | Used for vote joins |
| firstname | Legislator first name |
| lastname | Legislator last name |
| legislativebody | House or Senate |
| district | Legislative district |
| party | Political party |
| city | Legislator city |
| emailaddress | Public contact email |

---

# D1 Legislator Table

Production legislators are stored in:

```txt
d1_legislators
```

---

# Creating the D1 Table

Run:

```bash
wrangler d1 execute nhdb --remote --file=./scripts/d1_legislators_schema.sql
```

Schema:

```sql
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
```

---

# Exporting Legislators

Run:

```bash
python3 scripts/sync_nhdb.py export-legislators
```

This generates:

```txt
scripts/d1_exports/d1_legislators.sql
```

---

# Export Query

The legislator export query intentionally avoids `sessionyear`.

Correct query:

```sql
SELECT
    personid,
    employeeno,
    firstname,
    lastname,
    middlename,
    legislativebody,
    active,
    seatno,
    countycode,
    district,
    party,
    address,
    address2,
    city,
    zipcode,
    emailaddress,
    gendercode,
    secretaryid,
    database_name
FROM raw.legislators
WHERE active = true
ORDER BY legislativebody, lastname, firstname;
```

---

# Uploading Legislators to D1

Run:

```bash
wrangler d1 execute nhdb --remote --file=./scripts/d1_exports/d1_legislators.sql
```

This:
- clears existing production legislators
- uploads fresh legislator data
- updates the production API source

---

# Verifying Upload

Check uploaded legislators:

```bash
wrangler d1 execute nhdb --remote --command "SELECT firstname, lastname, legislativebody, district, party FROM d1_legislators LIMIT 10;"
```

Check Manchester legislators:

```bash
wrangler d1 execute nhdb --remote --command "SELECT firstname, lastname, district, party FROM d1_legislators WHERE LOWER(city) LIKE '%manchester%';"
```

---

# Important Relationships

## Vote History Join

```txt
rollcallhistory.EmployeeNumber
    ↕
legislators.Employeeno
```

This relationship powers:
- legislator vote histories
- accountability scoring
- bill vote displays

---

# Common Errors

## ERROR

```txt
column "sessionyear" does not exist
```

## Cause

The legislators table does not contain a `sessionyear` field.

## Fix

Remove:

```sql
AND sessionyear >= 2025
```

from the export query.

Use:

```sql
WHERE active = true
```

instead.

---

# Recommended Workflow

## 1. Sync latest General Court data

```bash
python3 scripts/sync_nhdb.py sync
```

---

## 2. Export legislators

```bash
python3 scripts/sync_nhdb.py export-legislators
```

---

## 3. Upload to D1

```bash
wrangler d1 execute nhdb --remote --file=./scripts/d1_exports/d1_legislators.sql
```

---

## 4. Verify

```bash
wrangler d1 execute nhdb --remote --command "SELECT COUNT(*) FROM d1_legislators;"
```

---

# Future Improvements

Potential future additions:

- legislator photos
- social media handles
- committee memberships
- accountability scores
- override tables
- manual bio summaries
- district mapping
- contact action links

These should likely be stored separately from raw imported data.