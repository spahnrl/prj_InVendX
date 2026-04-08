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

## Current status (paste for README or notes)

**InVendX (April 2026 checkpoint):** The project delivers a working **MVP CLI pipeline**—vendor YAML sync, bounded web crawl, structured evidence in SQLite, **rules-based scoring** (latest run by default, optional `--all-evidence`), and **exports** (including scorecard). **Regression and scoring-scope tests** cover key heuristics. A **first Streamlit operator UI** wraps the same `invendx` CLI (optional `pip install -e ".[ui]"`). This checkpoint reflects **implemented** behavior suitable for a portfolio demo, not a full product or hosted automation story.

---

<!-- Older checkpoints go below as the project grows. -->
