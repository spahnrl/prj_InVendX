# Changelog

Checkpoint-style history for **InVendX**. Entries describe what is implemented today, not planned work.

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

**InVendX (April 2026):** **MVP CLI pipeline**—vendor YAML sync, bounded crawl, evidence in SQLite, **rules-based scoring** (latest ingest run by default, `--all-evidence` when needed), **exports** (evidence, report, scorecard, summaries JSON). Tests cover extraction/scoring heuristics and scoring scope. **Streamlit** optional extra **`.[ui]`**: two-tab **`operator_app.py`** — **Vendor Intelligence** (portfolio + reports) and **Admin / Operator** (same `invendx` CLI as subprocess). Suitable for a portfolio demo; not a hosted production operator story.

---

<!-- Older checkpoints go below as the project grows. -->
