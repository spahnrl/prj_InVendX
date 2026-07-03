# Changelog

Checkpoint-style history for **InVendX**. Entries describe what is implemented today, not planned work.

---

## Handoff — Vendor Intelligence + narrative reports + manual intake (use for new Cursor chat)

**Date:** 2026-04-08

**Status:** **Vendor Intelligence** Streamlit sub-tabs (**Browse** / **Compare** / **Report**) with segment filter (and optional token mode), sort, portfolio CSV, **2–5 vendor compare** (latest score totals + per-category sums **plus AUM / advisors / RIA count hints** from `vendor_summaries`) + compare CSV. **Browse** portfolio table includes **RIA hint** (integer from `profile_metrics_json`). **Profile hints** (AUM scale, advisors/institutions, accounts, **`ria_hint`**) are extracted in [`extract_profile_metrics`](src/invendx/extract/patterns.py) from each evidence row’s claim + excerpt, aggregated in [`refresh_vendor_summary`](src/invendx/pipeline/vendor_summary.py) (`ria_hint` uses **max** across rows). Markdown **Summary** labels include **RIA firms (count, hint)** via [`_PROFILE_HINT_LABELS`](src/invendx/pipeline/report_builder.py). **CLI `summaries-refresh`** recomputes all `vendor_summaries` without re-crawling (needed after changing extraction or if hints look stale). Per-vendor Markdown reports from [`export_vendor_markdown`](src/invendx/pipeline/report_builder.py) include **How to read**, human **Summary** (profile hints as bullets), **At a glance**, **Latest scorecard**, **Recent evidence** (collapsed same-claim `dev_portal_signal` across URLs), **Distinct source URLs** appendix. **Manual intake** unchanged—see checklist below.

### Read first (canonical)

1. **`CHANGELOG.md`** (this file) — this handoff, then checkpoint **“Profile hints (AUM/advisors) + RIA count + summaries refresh”** at the **bottom**, then **“Vendor Intelligence UX + narrative markdown reports”** for earlier VI/report detail.
2. **Manual intake / crawl telemetry:** checkpoint **“Manual intake — Chrome capture, crawl misses, queue hygiene”** below.
3. Baseline **manual evidence intake** schema/flow: **“Manual evidence intake (staged queue + promote)”** further below.

### Key paths (implementation)

| Area | Location |
|------|----------|
| Vendor Markdown report | [`src/invendx/pipeline/report_builder.py`](src/invendx/pipeline/report_builder.py) — `export_vendor_markdown`, `_distinct_sources_appendix`, reader guide, takeaways |
| Recent evidence (grouping, dev-portal collapse, excerpts) | [`src/invendx/pipeline/evidence_views.py`](src/invendx/pipeline/evidence_views.py) — `recent_evidence_lines_for_report`, `_collapse_key_for_report` |
| Latest score category totals (Compare tab) | [`src/invendx/storage/score_repo.py`](src/invendx/storage/score_repo.py) — `latest_score_category_totals` |
| Streamlit VI + glance parser | [`operator_app.py`](operator_app.py) — `render_vendor_intelligence`, `_analyst_glance_markdown` (skips **How to read** / **At a glance** for compact card); Browse **RIA hint** column; Compare **AUM / Advisors / RIA hint** |
| Profile hint extraction + `ria_hint` | [`src/invendx/extract/patterns.py`](src/invendx/extract/patterns.py) — `extract_profile_metrics` |
| Vendor summary roll-up (max `ria_hint`) | [`src/invendx/pipeline/vendor_summary.py`](src/invendx/pipeline/vendor_summary.py) — `refresh_vendor_summary` |
| Summary hint labels in Markdown | [`src/invendx/pipeline/report_builder.py`](src/invendx/pipeline/report_builder.py) — `_PROFILE_HINT_LABELS` |
| SQLite schema v2 + `manual_intake_queue` | [`src/invendx/storage/db.py`](src/invendx/storage/db.py) |
| Staging CRUD + `skip_if_url_exists`, dedupe helpers | [`src/invendx/storage/manual_intake_repo.py`](src/invendx/storage/manual_intake_repo.py) |
| Guidance, promote, crawl queue, **`discard_duplicate_active_intakes_by_url`** | [`src/invendx/pipeline/manual_intake.py`](src/invendx/pipeline/manual_intake.py) |
| Playwright fetch + subprocess CLI runner | [`src/invendx/pipeline/browser_capture.py`](src/invendx/pipeline/browser_capture.py) |
| Crawl skip URL samples (bounded list) | [`src/invendx/pipeline/site_crawler.py`](src/invendx/pipeline/site_crawler.py) — `CrawlSkipTelemetry.skipped_urls` |
| Run notes JSON (`crawl_skipped_urls`, telemetry) | [`src/invendx/cli.py`](src/invendx/cli.py) `run` + [`evidence_repo.update_run_notes`](src/invendx/storage/evidence_repo.py) |
| CLI `manual promote` / `fetch` / `dedupe`; **`summaries-refresh`** | [`src/invendx/cli.py`](src/invendx/cli.py) |
| Streamlit Admin — `_render_manual_intake` | [`operator_app.py`](operator_app.py) |
| Tests | [`tests/test_report_builder_markdown.py`](tests/test_report_builder_markdown.py), [`tests/test_operator_intel_helpers.py`](tests/test_operator_intel_helpers.py), [`tests/test_manual_intake.py`](tests/test_manual_intake.py), [`tests/test_browser_capture.py`](tests/test_browser_capture.py), [`tests/test_evidence_views.py`](tests/test_evidence_views.py), [`tests/test_scorecard_export.py`](tests/test_scorecard_export.py) (`latest_score_category_totals`), [`tests/test_extract_profile_metrics.py`](tests/test_extract_profile_metrics.py), [`tests/test_vendor_summary_refresh.py`](tests/test_vendor_summary_refresh.py) |

### Operate

- **Deps:** `pip install '.[browser]'` then `playwright install chrome` (or system Chrome + CDP). UI-only: `pip install -e ".[ui]"`.
- **UI:** `streamlit run operator_app.py` → **Vendor Intelligence** (Browse / Compare / Report; **Download full report (.md)** on Report tab) → **Admin / Operator** → **Manual evidence intake** (CDP checkbox + instructions, bulk/single Chrome fetch via **subprocess**, crawl-miss queue buttons, dedupe button, **Promote all captured**).
- **CLI:** `invendx export report --vendor "…" --db … --out …` — same Markdown as Streamlit. `invendx manual promote|fetch|dedupe …` — `manual fetch` supports `--headed`, `--dry-run`, `--connect-cdp http://127.0.0.1:9222`. **`invendx summaries-refresh --db …`** — recompute **all** `vendor_summaries` (counts + `profile_metrics_json`) from stored evidence; use after changing hint regexes or if the UI shows empty hints on old DBs.

### Constraints to preserve

- **Scoring:** `manual_capture` is **not** in `config/score_rules.yaml`; promote does **not** invoke scoring.
- **Robots / acquisition:** No robots bypass on `SiteCrawler`; Chrome fetch is **operator-initiated** (policy remains operator responsibility).
- **Streamlit + Windows:** In-app fetch uses **`run_manual_fetch_subprocess`** (CLI in child process) to avoid asyncio `NotImplementedError` on subprocess exec under Streamlit.

### Likely follow-ups (not done)

- **Crawl-miss panel:** Uses **latest** `runs` row for vendor; if a newer run is promote-only (no `crawl_skipped_urls` JSON), section hides until next full **research run** — consider “latest run that contains `crawl_skipped_urls`”.
- Richer **robots diagnostics**; optional **honest configurable UA** (see older checkpoints).

---

## Checkpoint: Manual intake — Chrome capture, crawl misses, queue hygiene

**Date:** 2026-04-08

### Summary

**Playwright (optional extra `[browser]`):** [`browser_capture.py`](src/invendx/pipeline/browser_capture.py) — `extract_visible_text` (launch Chrome/Chromium or **`connect_over_cdp`**), `DEFAULT_UA`, `run_manual_fetch_subprocess` → `python -m invendx.cli manual fetch`.

**CLI:** `manual fetch` (`--headed`, `--dry-run`, `--connect-cdp`, `--wait-until`, `--timeout-ms`); **`manual dedupe <vendor>`** discards duplicate pending/captured rows per URL (keeps best row).

**Crawl → manual queue:** `SiteCrawler` records bounded **`skipped_urls`** `{url, crawl_reason}`; `invendx run` writes JSON into **`runs.notes`** via **`update_run_notes`**. UI: **Queue crawl-miss URLs**, optional **queue + Chrome-fetch all empty**.

**Queue hygiene:** `insert_intake(..., skip_if_url_exists=True)` for add/discover/crawl queue paths; **`discard_duplicate_active_intakes_by_url`** + Streamlit **Discard duplicate rows** button.

**Streamlit:** CDP “open Chrome first” instructions; **Promote all captured (no scoring)** beside single-row promote; flash messages for bulk promote results.

**Tests:** `tests/test_browser_capture.py` (mocked Playwright/subprocess).

### Deferred (unchanged or partial)

- File upload / PDF for manual intake; score rules citing `manual_capture`; fully automatic “latest run with skips” selection (see Handoff).

---

## Checkpoint: Manual evidence intake (staged queue + promote)

**Date:** 2026-04-08

### Summary

**Staging:** New SQLite table **`manual_intake_queue`** ([`src/invendx/storage/db.py`](src/invendx/storage/db.py) schema v2) with operator URL targets, reason flags, guidance key, capture text, and promote audit columns (`promoted_run_id`, `promoted_evidence_ids_json`).

**Pipeline:** [`src/invendx/pipeline/manual_intake.py`](src/invendx/pipeline/manual_intake.py) — URL normalization, per-reason guidance copy, **`manual_capture_to_evidence`**, **`promote_intake_to_evidence`** (new ingest `run` with JSON notes, one **`evidence_type=manual_capture`** row with **`source_type=manual`**, dedupe check, **no scoring**). Repo: [`src/invendx/storage/manual_intake_repo.py`](src/invendx/storage/manual_intake_repo.py).

**CLI:** `invendx manual promote <intake_id> --db …` ([`cli.py`](src/invendx/cli.py)).

**UI:** Admin / Operator expander **Manual evidence intake** in [`operator_app.py`](operator_app.py) — add URL, optional bulk queue from discover preview, queue table, capture form, discard, explicit promote.

**Deferred (note):** File upload / PDF storage; score rules citing `manual_capture`. **Crawl-skip → manual queue** is implemented in a later checkpoint (see **Manual intake — Chrome capture…** above).

---

## Checkpoint: Scoring contradiction, ingest hygiene, discovery tuning, acquisition slice

**Date:** 2026-04-08

### Summary

**Scoring:** When any **`dev_portal_signal`** exists in the same scoring scope, **`absence_signal`** rows tagged **`developer_docs`** are dropped before **`evaluate_rules`** (avoids **`dev_portal_link`** + **`dev_docs_absence`** firing together). Implemented in **`suppress_developer_docs_absence_when_dev_portal_present`** (`evidence_views.py`), wired from **`_execute_score`** (`cli.py`).

**Discovery (Phase 3):** Static path priorities adjusted—**`/blog`**, **`/insights`**, **`/resources`** down-ranked; **`/products`** aligned nearer **`/platform`** / **`/solutions`**; sitemap URLs under **`/blog/`**, **`/insights/`**, **`/news/`**, **`/press/`** get worse priority (`source_discovery.py`, **`_sitemap_priority`**).

**Ingest / parser:** **`_is_obvious_soft_error_page`** + shared **`title_looks_like_obvious_soft_error`** skip soft-404-style titles in **`parse_pages_to_evidence`** (`press_parser.py`). **`page.final_url`** is a **`dev_portal_signal`** doc-hint candidate alongside link hrefs.

**Reports:** When **Recent evidence** falls back to all runs (empty latest-run slice), rows matching the **same strict title-based junk rules** are filtered (`evidence_views.py`—**historical-only** path).

**Vendor seeds:** **`config/vendors.yaml`**—Charles River and SEI gained **`seed_urls`** for solutions/platform/partners/integrations and SEI **`developers.seic.com`** entry points (full URLs for cross-host).

**Diagnostics:** Standalone **`scripts/acquire_probe.py`**—per-URL fetch, robots allow, content-type, **`PageDocument`** eligibility, optional **`--parse`**, **`netloc_matches_allowed_seed_host`**, pipeline classification (blocked / dropped / etc.). No production behavior change.

**Acquisition (Phase 5—first slice only):** **`src/invendx/pipeline/site_host_equiv.py`**—narrow **www ↔ apex** equivalence only (not arbitrary subdomains). **`SiteCrawler`** uses it for link following; **`discover_vendor`** sitemap **`<loc>`** inclusion matches same rule. **`CrawlSkipTelemetry`** on **`SiteCrawler.last_telemetry`**: **`robots_denied`**, **`http_not_ok`**, **`non_html_skipped`**, **`fetch_failed`**, **`pages_stored`**—logged and echoed on **`invendx run`**. **No** PDF path, **no** robots bypass, **no** scoring changes.

### Tests added / touched

- `tests/test_evidence_views.py`, `tests/test_scoring_dev_portal_absence.py`, `tests/test_source_discovery.py`, `tests/test_extraction_and_scoring.py` (soft error + final_url dev portal), `tests/test_site_host_equiv.py`, `tests/test_site_crawler.py`.

### Deferred / out of scope (documented elsewhere)

- Case-study URL down-ranking in discovery (held for review).
- PDF acquisition / parsing.
- Production robots policy changes.
- Further **`allowed_netloc`** redesign beyond www/apex.

---

## Checkpoint: Evidence Quality Phase 2

**Date:** 2026-04-08

### Summary

**Fingerprint** (`dedupe_hash`) populated on ingest; **cross-run skip** when the same vendor already has that fingerprint; **within-run** batch dedupe. **Scoring** runs on a **deduped** evidence list (by hash or type/URL/claim). **Markdown reports** use **latest-run** recent evidence with **×N** collapse. **Discovery** adds optional paths (`/blog`, `/insights`, `/resources`, `/platform`, `/solutions`, `/products`). Optional **backfill** script: `scripts/backfill_evidence_dedupe_hashes.py`.

---

## Checkpoint: Coverage diagnostics

**Date:** 2026-04-08

### Summary

Per-vendor **coverage diagnostics**: SQL aggregates over `runs`, `evidence`, `vendor_summaries`, and latest `score_runs` / line-item counts; rule-based **`coverage_status`** and notes (thresholds: 8+ evidence rows and 3+ distinct source URLs). **Streamlit** Admin / Operator includes a **Coverage diagnostics** expander; **`invendx export coverage`** writes **`vendor_coverage.csv`** (no `--vendor`).

---

## Checkpoint: MVP Backend + First Operator UI

**Date:** 2026-04-07

### Summary

The CLI supports vendor sync, robots-aware bounded crawl, evidence ingestion to SQLite, rules-based scoring with explainable line items, and exports (evidence, report, scorecard). Scoring defaults to the latest ingest run; `--all-evidence` optionally scores across all stored evidence for a vendor. A minimal Streamlit operator UI runs the same CLI subprocesses and shows the latest score summary from the database.

### Completed in this checkpoint

- Initial GitHub repository setup and clean first push
- Merged and corrected README
- Vendor sync, crawl, evidence ingestion, scoring, and exports working end-to-end
- `run --score` (ingest then score in one invocation)
- `export scorecard` added
- Crawl tuning flags: `--max-pages`, `--max-depth`, `--delay`
- Regression tests for extraction/scoring heuristics
- Latest-run scoring by default
- `--all-evidence` override for scoring scope
- Scoring scope tests
- First Streamlit operator UI (`streamlit run operator_app.py`), optional `ui` extra in `pyproject.toml`

### Scope notes

- The operator UI is a single-screen MVP: path inputs, sync/run/export actions, log output, and a read-only latest score panel. It does not add new backend features beyond what the CLI already supports.

---

## Checkpoint: Two-tab Streamlit — Vendor Intelligence + Admin/Operator

**Date:** 2026-04-08

### Summary

The Streamlit app is split into **Vendor Intelligence** (analyst-first) and **Admin / Operator** (CLI parity). The analyst tab shows a read-only portfolio joins `vendors` with `vendor_summaries` (same shape as `export_summaries_json`), search, CSV export of raw rows, per-vendor markdown report preview + download, and an “At a glance” summary derived from the existing report text. The admin tab keeps paths in the sidebar, sync, ingest, scoring options, exports, operation log, and latest score line items. Layout/CSS polish and a **favicon column** (Google favicon URL from `primary_domain`, browser-loaded; placeholder if no domain) are presentation-only—no new SQLite tables or ingestion behavior.

### Completed in this checkpoint

- `st.tabs`: **Vendor Intelligence** (default) and **Admin / Operator**
- Portfolio table: search, export CSV, pandas + `column_config`, row height tuning, human-readable column labels
- Report: in-process `report_builder.export_vendor_markdown`, expander for full markdown, download `.md`
- “At a glance” card: footprint line + shortened labels from the same generated report (display-only trimming)
- Global layout CSS: narrower sidebar, capped main width for readability
- **Icon column:** favicon URLs from `primary_domain` (optional network); no `logo_url` in schema
- `ui` optional extra remains `streamlit>=1.30`; `operator_app.py` uses `pandas` (pulled in with Streamlit)

### Scope notes

- Deferred from earlier UI plan (still optional): portfolio **latest score** column via join; **source pills** from evidence aggregation; curated **brand logos** per vendor (would need config/DB field)

---

## Current status (paste for README or notes)

**InVendX (April 2026):** **MVP CLI pipeline**—vendor YAML sync, bounded crawl (telemetry + **sampled `crawl_skipped_urls`** in `runs.notes` on `run`), evidence in SQLite, **rules-based scoring** with **dev-portal vs dev-docs-absence** suppression, **exports**. **`scripts/acquire_probe.py`**. **Manual intake** — queue, paste / **Chrome fetch** (optional **`.[browser]`** + Playwright; **CDP attach** supported), crawl-miss queueing, **dedupe**, **Promote all captured**; CLI `manual promote|fetch|dedupe`. **Streamlit** **Vendor Intelligence** — Browse (filter/sort, **AUM/advisors/accounts/RIA hint** columns, portfolio CSV), Compare (2–5 vendors, **same hints** + score matrix + CSV), Report (**human-readable** Markdown). **`invendx summaries-refresh`** recomputes hint JSON without re-crawl. **Handoff** at top of **`CHANGELOG.md`**.

---

## Checkpoint: Vendor Intelligence UX + narrative markdown reports

**Date:** 2026-04-08

### Summary

**Streamlit — Vendor Intelligence:** Sub-tabs **Browse** (search, **segment** multiselect + optional token match on `/` and comma, **sort**, portfolio table, **Export CSV**), **Compare** (multiselect **2–5** vendors from cohort, table with ingest fields + **Total score** + **per-category** sums from latest `score_run`, **Export comparison CSV**), **Report** (focus vendor, metrics, **Download full report (.md)**). Shared filters above tabs drive cohort.

**Markdown reports —** [`export_vendor_markdown`](src/invendx/pipeline/report_builder.py): **`## How to read this report`** (section guide); **`## Summary`** with ISO date for last evidence, confidence rollup explanation, **profile hints** as labeled bullets (not raw JSON); **`## At a glance`** takeaways from summary + score categories + developer signal read; **`## Latest scorecard`** with category display names, **rationale**, indented **evidence ID → claim preview + link** (capped); **`## Recent evidence`** via [`recent_evidence_lines_for_report`](src/invendx/pipeline/evidence_views.py)—**`###` buckets**, page title / **longer excerpts** (drop excerpt when it mostly duplicates title or claim), confidence; **`dev_portal_signal`** rows with **identical `claim_text`** merged across many **source URLs** into one bullet with distinct-page count and pointer to appendix; **`## Distinct source URLs`** sorted link list (cap **100**, remainder note + `export evidence`).

**Supporting:** [`latest_score_category_totals`](src/invendx/storage/score_repo.py) for Compare tab; [`operator_app.py`](operator_app.py) — `_analyst_glance_markdown` skips **How to read** / **At a glance** blocks so the Streamlit glance card stays **Summary**-focused; **`Last evidence (date)`** label handled in glance regex.

**Tests:** [`tests/test_operator_intel_helpers.py`](tests/test_operator_intel_helpers.py), [`tests/test_report_builder_markdown.py`](tests/test_report_builder_markdown.py), [`test_recent_evidence_collapses_same_dev_portal_claim_across_urls`](tests/test_evidence_views.py), [`test_latest_score_category_totals`](tests/test_scorecard_export.py).

### Deferred / follow-ups (not done)

- Portfolio **latest score** column via join (still optional from older UI notes).
- **Source pills** from evidence aggregates; curated **logo_url** in config/DB.
- Scorecard citation dedupe when many rows cite the same dev-portal URL (report narrative is improved in **Recent evidence**; scorecard block can still list many IDs).

---

## Checkpoint: Profile hints (AUM/advisors) + RIA count + summaries refresh

**Date:** 2026-04-08

### Summary

**Extraction:** [`extract_profile_metrics`](src/invendx/extract/patterns.py) — broader **AUM** (`$T`, `$B`, trillion/billion words), **advisors/institutions** (comma thousands, `+`, over/more than, `~`; avoids tiny stray counts), **`ria_hint`** as **int** from RIA-specific phrases (e.g. `RIAs`, `RIA firms`, `RIAs:`, `10K+ RIAs`, `independent RIAs`, tight `+RIAs`), **K-suffix** scale, and **merge** with **max** across regex + optional derive from **`advisors_or_institutions_hint`** when that substring mentions **RIA/RIAs** (max of plausible integers; skips lone year-like 1900–2100).

**Aggregation:** [`refresh_vendor_summary`](src/invendx/pipeline/vendor_summary.py) — **`setdefault`** for string hints; **`ria_hint`** = **max** of ints across evidence rows.

**Markdown:** [`_PROFILE_HINT_LABELS`](src/invendx/pipeline/report_builder.py) includes **`ria_hint`** → *RIA firms (count, hint)* in **Summary** profile bullets.

**Streamlit:** [`operator_app.py`](operator_app.py) — **`_coerce_ria_hint_cell`**; Browse **RIA hint** `NumberColumn`; Compare adds **AUM hint**, **Advisors hint**, **RIA hint**; captions mention **`summaries-refresh`** when hints are stale.

**CLI:** **`invendx summaries-refresh --db …`** — loops **`list_vendors`** + **`refresh_vendor_summary`** (no ingest).

**Tests:** [`tests/test_extract_profile_metrics.py`](tests/test_extract_profile_metrics.py), [`tests/test_vendor_summary_refresh.py`](tests/test_vendor_summary_refresh.py); [`tests/test_report_builder_markdown.py`](tests/test_report_builder_markdown.py) asserts RIA label + value.

### Deferred / follow-ups (not done)

- Manual per-vendor **`ria_hint`** in YAML/DB (not implemented).
- Further tuning if vendor copy uses nonstandard RIA wording; **evidence text** must contain matchable phrases for hints to populate.

---

<!-- Older checkpoints go below as the project grows. -->
