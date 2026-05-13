## Legislative Data Workflow

Sync latest General Court data:

```bash
python3 scripts/sync_nhdb.py sync
```

Export selected bills:

```bash
python3 scripts/sync_nhdb.py export-bills HB699 SB272
```

Upload to D1:

```bash
wrangler d1 execute nhdb --remote --file=./scripts/d1_exports/d1_selected_bills_HB699_SB272.sql
```