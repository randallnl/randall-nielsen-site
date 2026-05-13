# NH Deserves Better Setup

This document explains how to set up the NH Deserves Better development environment locally.

The project consists of:

- Astro frontend
- Cloudflare Worker API
- Cloudflare D1 production database
- Local PostgreSQL analysis database
- NH General Court sync tooling

# Required Software

Install the following:

- Node.js 20+
- Python 3.11+
- PostgreSQL 15+
- ODBC Driver 18 for SQL Server
- Wrangler CLI

Mac:

```bash
brew install node
brew install postgresql
brew install unixodbc
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18
```

# Install Dependencies

## Frontend

```bash
npm install
```

## Python

```bash
pip3 install pandas pyodbc python-dotenv sqlalchemy psycopg2-binary
```

## Wrangler

```bash
npm install -g wrangler
```

# Environment Variables

Create:

```txt
.env.local
```

Example contents:

```txt
POSTGRES_URL=postgresql+psycopg2://USERNAME@localhost:5432/nhdb
START_SESSION_YEAR=2025
```

The General Court SQL credentials are currently public:

```txt
SERVER=66.211.150.69
DATABASE=NHLegislatureDB
USERNAME=publicuser
PASSWORD=PublicAccess
```

# PostgreSQL Setup

Create the database:

```bash
createdb nhdb
```

Verify connection:

```bash
psql nhdb
```

# Cloudflare Setup

Login:

```bash
wrangler login
```

Create D1 database:

```bash
wrangler d1 create nhdb
```

Apply schema:

```bash
python3 scripts/sync_nhdb.py schema > scripts/d1_schema.sql

wrangler d1 execute nhdb --remote --file=./scripts/d1_schema.sql
```

# Sync General Court Data

```bash
python3 scripts/sync_nhdb.py sync
```

This imports:
- docket
- legislators
- sponsors
- roll calls
- testimony
- committees

for 2025-current only.

# Export Bills

Example:

```bash
python3 scripts/sync_nhdb.py export-bills HB699 SB272
```

Uploads are generated in:

```txt
scripts/d1_exports/
```

# Upload to D1

```bash
wrangler d1 execute nhdb --remote --file=./scripts/d1_exports/d1_selected_bills_HB699_SB272.sql
```

# Run Astro Frontend

```bash
npm run dev
```

Frontend:

```txt
http://localhost:4321
```

# Deployment

Push changes to GitHub:

```bash
git add .
git commit -m "Update"
git push
```

Cloudflare Pages automatically deploys the Astro frontend.

# Additional Documentation

- docs/legislative-data-workflow.md
- docs/source-schema-reference.md
- docs/api-architecture.md
- docs/known-data-issues.md