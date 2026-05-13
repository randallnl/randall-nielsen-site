# Legislator Photo Upload Workflow

This document explains how NH Deserves Better uploads legislator photos from a local folder into Cloudflare R2 and automatically syncs them into the production database.

The workflow is:

```txt
Local Photo Folder
        ↓
Cloudflare R2 Upload
        ↓
Worker scans filenames
        ↓
Employee number extracted
        ↓
Matched to d1_legislators
        ↓
d1_legislator_photos updated
        ↓
Frontend/API display photos
```

The matching process is automatic and based on the legislator employee number in the filename.

---

# R2 Bucket

Legislator photos are stored in:

```txt
nhdeservesbetter-legislator-photos
```

---

# Filename Format

Photos MUST follow this naming structure:

```txt
{employeeno}_{lastname}_{firstname}.jpg
```

Examples:

```txt
12345_sullivan_victoria.jpg
67890_smith_john.webp
```

---

# Important Rules

## Required

The filename MUST begin with:

```txt
{employeeno}_
```

The automatic sync process extracts the employee number from the filename.

---

## Recommended

Use:
- lowercase
- underscores
- no spaces
- no punctuation

Good:

```txt
12345_sullivan_victoria.jpg
```

Avoid:

```txt
12345_Sullivan_Victoria.JPG
12345-Victoria Sullivan.jpg
```

---

# Recommended Image Format

Preferred:

```txt
.webp
```

Acceptable:

```txt
.jpg
.jpeg
.png
```

---

# Local Folder Structure

Recommended local structure:

```txt
legislator-photos/
    ├── 12345_sullivan_victoria.webp
    ├── 67890_smith_john.jpg
    └── ...
```

---

# Uploading Photos to R2

## Using Wrangler

From the project root:

```bash
wrangler r2 object put nhdeservesbetter-legislator-photos/12345_sullivan_victoria.webp --file=./photos/legislators/12345_sullivan_victoria.webp
```

---

# Bulk Upload Script

Recommended for many photos.

Create:

```txt
scripts/upload_legislator_photos.sh
```

Contents:

```bash
#!/bin/bash

PHOTO_DIR="./photos/legislators"

for file in "$PHOTO_DIR"/*; do
  filename=$(basename "$file")

  echo "Uploading $filename"

  wrangler r2 object put \
    "nhdeservesbetter-legislator-photos/$filename" \
    --file="$file"
done

echo "Upload complete."
```

Make executable:

```bash
chmod +x scripts/upload_legislator_photos.sh
```

Run:

```bash
./scripts/upload_legislator_photos.sh
```

---

# Verifying Uploads

List bucket contents:

```bash
wrangler r2 object list nhdeservesbetter-legislator-photos
```

---

# Syncing Photos Into D1

After uploads complete:

```bash
curl -X POST https://api.nhdeservesbetter.com/admin/sync-legislator-photos \
  -H "x-admin-secret: YOUR_ADMIN_SECRET"
```

This process:

1. Scans R2 bucket
2. Reads filenames
3. Extracts employee numbers
4. Matches legislators
5. Updates `d1_legislator_photos`

---

# Example Matching

Filename:

```txt
12345_sullivan_victoria.jpg
```

Extracted:

```txt
employeeno = 12345
```

Database lookup:

```sql
SELECT *
FROM d1_legislators
WHERE employeeno = 12345
```

If found:
- photo mapping is created automatically

---

# Verifying Photo Sync

Check synced photos:

```bash
wrangler d1 execute nhdb --remote --command "SELECT employeeno, firstname, lastname, photo_url FROM d1_legislator_photos LIMIT 20;"
```

---

# Photo URL Structure

Photos are publicly served from:

```txt
https://photos.nhdeservesbetter.com/
```

Example:

```txt
https://photos.nhdeservesbetter.com/12345_sullivan_victoria.jpg
```

---

# Frontend Usage

The API returns:

```json
{
  "photo": "https://photos.nhdeservesbetter.com/12345_sullivan_victoria.jpg"
}
```

Frontend example:

```html
<img src={rep.photo} alt={rep.name} />
```

---

# Common Errors

## ERROR

```txt
No matching legislator found
```

## Cause

The employee number in the filename does not exist in:

```txt
d1_legislators
```

## Fix

Verify:
- legislator export is current
- employee number is correct

---

## ERROR

```txt
Filename does not start with employeeno_
```

## Cause

Filename format invalid.

## Fix

Rename file:

Bad:

```txt
victoria_sullivan.jpg
```

Good:

```txt
12345_sullivan_victoria.jpg
```

---

# Recommended Workflow

## 1. Add photos locally

```txt
legislator-photos
```

---

## 2. Bulk upload

```bash
./scripts/upload_legislator_photos.sh
```

---

## 3. Sync mappings

```bash
curl -X POST https://api.nhdeservesbetter.com/admin/sync-legislator-photos \
  -H "x-admin-secret: YOUR_ADMIN_SECRET"
```

---

## 4. Verify D1

```bash
wrangler d1 execute nhdb --remote --command "SELECT COUNT(*) FROM d1_legislator_photos;"
```

---

# Future Improvements

Potential future additions:

- automatic image resizing
- automatic WebP conversion
- fallback placeholder images
- image moderation/review
- committee chair badges
- district overlays
- cached thumbnails
- headshot cropping automation