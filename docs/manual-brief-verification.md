# Brief Manual Verification Guide

This document verifies the brief generation workflow end-to-end against real or testable公众号数据 already stored in SQLite.

## Scope

Covers:
- brief prerequisite data checks
- single-account normalization to brief flow
- domain-level normalization to brief flow
- Markdown brief output inspection
- JSON brief output inspection
- overview / section summary / item summary verification
- persisted metadata checks used by brief generation

Repository rule: any manual verification artifacts created during testing should go under:
- `.tmp/test-output/`

---

## 1. Prepare a clean test database

```bash
mkdir -p .tmp/test-output
rm -f .tmp/test-output/brief-manual.db
rm -rf .tmp/test-output/brief-articles
```

Use these paths for all commands below:
- DB: `.tmp/test-output/brief-manual.db`
- output dir: `.tmp/test-output/brief-articles`

---

## 2. Bootstrap the default domain

Run:

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db bootstrap --output-json
```

Expected:
- command succeeds
- `default_domain.name == "医疗信息"`
- database is initialized and reusable for later brief commands

---

## 3. Ensure auth is ready if you plan to use real sync/normalize

If the database already has valid MP auth, confirm it:

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db auth show --output-json
```

Expected:
- `configured == true`
- token present
- cookie length > 0

If not configured, complete one of:

### Option A: QR login

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db auth login
```

### Option B: manually set token + cookie

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db auth set --token "<TOKEN>" --cookie-file /path/to/cookie.txt
```

---

## 4. Subscribe one or more accounts into `医疗信息`

Example single-account subscription:

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db subscribe "CHIMA" --domain "医疗信息" --output-json
```

Optional second account for domain aggregation verification:

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db subscribe "国家医保局" --domain "医疗信息" --output-json
```

List subscriptions:

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db subscriptions --domain "医疗信息" --output-json
```

Expected:
- subscribed account(s) are listed
- domain is `医疗信息`
- fakeid/nickname are persisted

---

## 5. Sync article metadata

### Option A: sync one account

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db sync "CHIMA" --max-pages 1 --output-json
```

### Option B: sync all accounts in the domain

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db sync --all --domain "医疗信息" --max-pages 1 --output-json
```

Expected:
- result contains `pages`, `new_articles`, `updated_articles`, `synced_articles`
- at least one article row is stored for the account(s) you will use in brief verification

Recommended spot check:

```bash
python - <<'PY'
import sqlite3
conn = sqlite3.connect('.tmp/test-output/brief-manual.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('''
SELECT a.fakeid, acc.nickname, a.title, a.create_time, a.download_status
FROM articles a
JOIN accounts acc ON acc.fakeid = a.fakeid
ORDER BY a.create_time DESC
LIMIT 10
''').fetchall()
for row in rows:
    print(dict(row))
PY
```

Expected:
- target article rows exist in `articles`
- `download_status` is usually `pending` before normalization

---

## 6. Normalize content for brief input

Brief quality is best when `article_contents.cleaned_text` is already populated by normalization.

### Option A: normalize a single account

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db normalize-account "CHIMA" --limit 2 --output-json -o .tmp/test-output/brief-articles
```

### Option B: normalize the whole domain

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db normalize-domain --domain "医疗信息" --limit 1 --output-json -o .tmp/test-output/brief-articles
```

Expected:
- command succeeds
- `success >= 1` for accessible article(s)
- output files are written under `.tmp/test-output/brief-articles`
- normalized articles are persisted into `article_contents`

Optional OCR variant:

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db normalize-account "CHIMA" --limit 1 --image-ocr --output-json -o .tmp/test-output/brief-articles
```

Expected:
- command still succeeds if OCR returns no fragments
- OCR-enriched text may appear in `cleaned_text` and `ocr_summary`

---

## 7. Inspect persisted fields used by brief generation

Run:

```bash
python - <<'PY'
import sqlite3
conn = sqlite3.connect('.tmp/test-output/brief-manual.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('''
SELECT ac.link,
       ac.title,
       ac.fetch_status,
       ac.extraction_profile,
       ac.extraction_profile_version,
       ac.ocr_applied,
       ac.ocr_summary,
       substr(ac.cleaned_text, 1, 200) AS cleaned_preview,
       a.download_status,
       acc.nickname
FROM article_contents ac
JOIN articles a ON a.link = ac.link
JOIN accounts acc ON acc.fakeid = ac.fakeid
ORDER BY ac.updated_at DESC
LIMIT 10
''').fetchall()
for row in rows:
    print(dict(row))
PY
```

Verify:
- `fetch_status == "normalized"` for articles you expect to enter the brief
- `cleaned_text` is non-empty and looks like正文, not just template noise
- `extraction_profile` / `extraction_profile_version` are populated
- `ocr_applied` and `ocr_summary` are correct if OCR was used
- `download_status` on article row is `normalized`

---

## 8. Generate the brief in Markdown mode

Run:

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db brief generate --domain "医疗信息" --date yesterday
```

Or pin a specific date:

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db brief generate --domain "医疗信息" --date 2026-04-21
```

Expected output structure:
- title line: `# 医疗信息 每日简报`
- date line
- candidate/selected counts
- top-level `今日总览`
- one or more section headings such as:
  - `## 政策规范`
  - `## 会议讲座`
  - `## 研究论文`
- each item includes:
  - 来源
  - 摘要
  - 关注点
  - 链接

Manual checks:
- overview should read like a high-level summary, not raw JSON
- section summary should read like栏目导读, not just “共收录几篇”
- article summary should prefer cleaned正文 over digest/title-only fallback when normalized data exists
- `why_it_matters` should be category-specific when applicable

---

## 9. Generate the brief in JSON mode

Run:

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db brief generate --domain "医疗信息" --date yesterday --output-json
```

Expected top-level fields:
- `ok == true`
- `command == "brief.generate"`
- `domain`
- `brief_date`
- `total_candidates`
- `total_selected`
- `overview`
- `sections`
- `markdown`

Manual JSON checks:
- `overview` is non-empty when there are selected items
- `sections` is a mapping keyed by section name
- each section has:
  - `section_summary`
  - `items`
- each item should include:
  - `title`
  - `source_account`
  - `fetch_status`
  - `summary`
  - `why_it_matters`
  - `link`

---

## 10. Single-account brief verification checklist

Use this when you normalized only one account.

Suggested scenario:
- choose one account with at least one real accessible article on the verification date

Verify:
- the selected article appears in the brief
- its `fetch_status` is `normalized`
- summary clearly reflects正文 instead of only article title/digest
- if article is meeting-like, brief should place it under `会议讲座`
- if article is policy-like, brief should place it under `政策规范`
- overview and section summary remain coherent even with only one section or one item

---

## 11. Domain aggregation verification checklist

Use this when you normalized multiple accounts in the same domain.

Suggested scenario:
- one policy-like account/article
- one meeting-like or research-like account/article

Verify:
- brief contains multiple sections when article categories differ
- overview mentions more than one signal when multiple categories exist
- higher-value normalized content appears before lower-value content within a section
- dedupe does not remove unrelated articles from different accounts

If possible, include one pair of nearly duplicate titles across accounts and verify:
- only one item survives if they are genuine duplicates
- preferred retained version comes from better source / newer or better-ranked metadata

---

## 12. Manual regression checks

### A. Brief should still work when only metadata exists
Choose a date/domain with article metadata present but limited normalization coverage.

Expected:
- brief still renders
- title-only or digest-based fallback works
- no crash due to missing `cleaned_text`

### B. Template noise should not dominate summary
Choose a normalized article whose original content contained phrases like:
- `欢迎关注`
- `扫码`
- `联系我们`
- `推荐阅读`

Expected:
- these phrases do not dominate the final summary
- summary prioritizes real policy / meeting / research content

### C. Overview should not disappear when sections exist
Expected:
- if at least one item is selected, top-level overview is present
- if multiple sections exist, overview should reflect more than one signal when possible

### D. Section summary should not regress to the old count-only template
Expected:
- section summary reads like导读
- it should not regress to only `本栏目共收录 X 篇内容...`

---

## 13. Completion criteria

Brief manual verification is complete when all of the following are true:

- [ ] bootstrap succeeds and default domain exists
- [ ] target account(s) are subscribed into `医疗信息`
- [ ] sync stores article metadata for the verification date
- [ ] normalize-account or normalize-domain stores normalized content
- [ ] `article_contents` has usable `cleaned_text` for selected article(s)
- [ ] `brief generate` works in Markdown mode
- [ ] `brief generate --output-json` returns overview, sections, and markdown
- [ ] overview is present and readable
- [ ] section summaries are readable and category-aware
- [ ] item summaries and `why_it_matters` look consistent with the article type
- [ ] multi-account domain aggregation works if tested

---

## 14. Recommended command summary

```bash
python -m wespy.main --db-path .tmp/test-output/brief-manual.db bootstrap --output-json
python -m wespy.main --db-path .tmp/test-output/brief-manual.db auth show --output-json
python -m wespy.main --db-path .tmp/test-output/brief-manual.db subscribe "CHIMA" --domain "医疗信息" --output-json
python -m wespy.main --db-path .tmp/test-output/brief-manual.db subscribe "国家医保局" --domain "医疗信息" --output-json
python -m wespy.main --db-path .tmp/test-output/brief-manual.db sync --all --domain "医疗信息" --max-pages 1 --output-json
python -m wespy.main --db-path .tmp/test-output/brief-manual.db normalize-domain --domain "医疗信息" --limit 1 --output-json -o .tmp/test-output/brief-articles
python -m wespy.main --db-path .tmp/test-output/brief-manual.db brief generate --domain "医疗信息" --date yesterday
python -m wespy.main --db-path .tmp/test-output/brief-manual.db brief generate --domain "医疗信息" --date yesterday --output-json
```