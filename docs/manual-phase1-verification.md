# Phase 1 Manual Verification Guide

This document verifies the Phase 1 workflow end-to-end against a real公众号账号。

## Scope

Covers:
- default domain bootstrap
- subscribe into `医疗信息`
- sync article list
- normalize with profile-aware cleaning
- OCR persistence checks
- stored metadata inspection

Repository rule: any manual verification artifacts created during testing should go under:
- `.tmp/test-output/`

---

## 1. Prepare a clean test database

```bash
mkdir -p .tmp/test-output
rm -f .tmp/test-output/phase1-manual.db
```

Use this DB path for all commands below:
- `.tmp/test-output/phase1-manual.db`

---

## 2. Bootstrap the default domain

Run:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db bootstrap --output-json
```

Expected:
- command succeeds
- `default_domain.name == "医疗信息"`
- `domains` contains exactly one default domain on first run
- re-running returns the same domain rather than creating duplicates

---

## 3. Log in or set MP auth

### Option A: QR login

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db auth login
```

### Option B: manually set token + cookie

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db auth set --token "<TOKEN>" --cookie-file /path/to/cookie.txt
```

Verify auth state:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db auth show --output-json
```

Expected:
- `configured == true`
- token present
- cookie length > 0

---

## 4. Subscribe a medical account into the default domain

Example using account name:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db subscribe "CHIMA" --domain "医疗信息" --output-json
```

Example using article URL:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db subscribe "https://mp.weixin.qq.com/s/<ARTICLE_ID>" --domain "医疗信息" --output-json
```

Expected:
- command succeeds
- response includes account nickname/fakeid
- domain is `医疗信息`

List subscriptions:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db subscriptions --domain "医疗信息" --output-json
```

Expected:
- subscribed account is listed
- `article_count` initially may be 0 before sync

---

## 5. Check profile resolution

List profiles:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db profile list --output-json
```

Show resolved profile for the subscribed account:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db profile show "CHIMA" --output-json
```

Expected:
- `default` exists
- `chima` exists
- `CHIMA` resolves to `chima` unless explicitly rebound

Optional explicit bind test:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db profile bind "CHIMA" --profile default --output-json
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db profile show "CHIMA" --output-json
```

Expected:
- resolved profile changes to `default`

If you changed it for testing, bind it back:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db profile bind "CHIMA" --profile chima --output-json
```

---

## 6. Sync article metadata

Sync a subscribed account:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db sync "CHIMA" --max-pages 1 --output-json
```

Or sync all accounts in the domain:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db sync --all --domain "医疗信息" --max-pages 1 --output-json
```

Expected:
- result contains `pages`, `new_articles`, `updated_articles`, `synced_articles`
- at least one article row is stored if the account has publish history accessible

---

## 7. Normalize content without OCR

Run:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db normalize-account "CHIMA" --limit 1 --output-json -o .tmp/test-output/articles
```

Expected:
- `success >= 1` for accessible article(s)
- `unavailable` only for real unavailable pages
- output files written under `.tmp/test-output/articles/`

---

## 8. Normalize content with OCR

Run:

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db normalize-account "CHIMA" --limit 1 --image-ocr --output-json -o .tmp/test-output/articles
```

Expected:
- command succeeds even if OCR yields no fragments
- for image-heavy article(s), OCR-enriched text may be persisted

Note:
- OCR depends on MinerU availability/configuration
- if OCR service is unavailable, verify the non-OCR normalization path still works

---

## 9. Inspect persisted data fields

Use Python + sqlite3, or inspect with your preferred SQLite tool.

Example Python snippet:

```bash
python - <<'PY'
import sqlite3
conn = sqlite3.connect('.tmp/test-output/phase1-manual.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('''
SELECT link, title, fetch_status, extraction_profile, extraction_profile_version,
       normalization_notes, ocr_applied, ocr_summary, substr(cleaned_text, 1, 200) AS cleaned_preview
FROM article_contents
ORDER BY updated_at DESC
LIMIT 5
''').fetchall()
for row in rows:
    print(dict(row))
PY
```

Verify these fields:
- `fetch_status`
- `extraction_profile`
- `extraction_profile_version`
- `normalization_notes`
- `ocr_applied`
- `ocr_summary`
- `cleaned_text`

Expected:
- normalized CHIMA article uses `chima` unless explicitly rebound
- `normalization_notes` is non-empty JSON text
- `ocr_applied == 1` only when OCR fragments were merged
- `ocr_summary` is present only when OCR contributed data

---

## 10. Regression checks to perform manually

### A. Template hints should not mark a real article unavailable
Look at a real article containing phrases such as:
- `轻触阅读原文`
- `微信扫一扫可打开此内容`
- `使用完整服务`

Expected:
- if正文 exists, article should remain `fetch_status=normalized`

### B. Mid-article disclaimer should not truncate real following paragraphs
Choose or simulate an article where:
- a quote or block contains `免责声明`
- real正文 continues after that block

Expected:
- later正文 remains in `cleaned_text`

### C. Profile-based noise removal should work
For CHIMA-like article layout, verify that obvious noise such as:
- follow prompts
- ad block
- repeated recommendations

is absent from `cleaned_text`

---

## 11. Completion criteria

Phase 1 manual verification is complete when all of the following are true:

- [ ] `bootstrap` creates or reuses `医疗信息`
- [ ] subscription into `医疗信息` succeeds
- [ ] profile resolution works for the subscribed account
- [ ] sync stores article metadata
- [ ] normalize stores article content
- [ ] profile metadata is persisted in `article_contents`
- [ ] OCR fields are correct when OCR contributes content
- [ ] template hint pages with real正文 are not marked unavailable
- [ ] mid-article disclaimer markers do not remove real following正文

---

## 12. Recommended commands summary

```bash
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db bootstrap --output-json
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db auth show --output-json
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db subscribe "CHIMA" --domain "医疗信息" --output-json
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db profile show "CHIMA" --output-json
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db sync "CHIMA" --max-pages 1 --output-json
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db normalize-account "CHIMA" --limit 1 --output-json -o .tmp/test-output/articles
python -m wespy.main --db-path .tmp/test-output/phase1-manual.db normalize-account "CHIMA" --limit 1 --image-ocr --output-json -o .tmp/test-output/articles
```
