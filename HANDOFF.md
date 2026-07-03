# Handoff checkpoint — InVendX (Streamlit + reports)

Use this file to continue in a new chat without re-deriving context.

**Canonical doc:** [`CHANGELOG.md`](CHANGELOG.md) — start at **`## Handoff — Vendor Intelligence + narrative reports + manual intake (use for new Cursor chat)`**, then checkpoint **`## Checkpoint: Profile hints (AUM/advisors) + RIA count + summaries refresh`** near the **bottom** (newest), then **`Vendor Intelligence UX + narrative markdown reports`** for full VI/report narrative.

## Quick start

**Windows:** double-click [`run_streamlit.bat`](run_streamlit.bat) in the repo root (uses `.venv` or `venv` if present).

```powershell
cd <repo-root>
pip install -e ".[ui]"
# optional: manual Chrome fetch in UI
pip install -e ".[ui,browser]"
# playwright install chrome
streamlit run operator_app.py
```

## What to know (April 2026)

- **Vendor Intelligence** (default tab): **Browse** (search, segment filter + optional token mode, sort, portfolio table with **AUM / Advisors / Accounts / RIA hint** columns, **Export CSV**), **Compare** (2–5 vendors: **same hint columns** + **Total score** + per-category sums, **Export comparison CSV**), **Report** (focus vendor, **Download full report (.md)**).
- **Hints** live in **`vendor_summaries.profile_metrics_json`**; populated by **`refresh_vendor_summary`** from evidence claim + excerpt via **`extract_profile_metrics`**. **`ria_hint`** is an **integer** (max across rows when multiple pages cite counts). Not validated financials.
- If hints are **empty or stale** after a code change: **`python -m invendx.cli summaries-refresh --db <path>`** (no re-crawl). Streamlit VI caption shows the same command with your DB path.
- **Markdown report** ([`export_vendor_markdown`](src/invendx/pipeline/report_builder.py)): **How to read**, **Summary** (profile hints including **RIA firms (count, hint)**), **At a glance**, **Latest scorecard**, **Recent evidence** (grouped; dev-portal claim collapse), **Distinct source URLs** appendix.
- **Admin / Operator:** Paths in sidebar, sync, run/score, exports, operation log, latest score panel, **Manual evidence intake** (Playwright fetch via subprocess, CDP, crawl-miss queue, dedupe, promote — **no scoring** on promote).

## Key files

| Area | Path |
|------|------|
| Streamlit entry | [`operator_app.py`](operator_app.py) |
| Profile metrics extraction (`ria_hint`, AUM, advisors) | [`src/invendx/extract/patterns.py`](src/invendx/extract/patterns.py) |
| Summary roll-up + max `ria_hint` | [`src/invendx/pipeline/vendor_summary.py`](src/invendx/pipeline/vendor_summary.py) |
| Markdown report + hint labels | [`src/invendx/pipeline/report_builder.py`](src/invendx/pipeline/report_builder.py) |
| Recent evidence (grouping, dev-portal collapse) | [`src/invendx/pipeline/evidence_views.py`](src/invendx/pipeline/evidence_views.py) |
| Latest score category totals (Compare) | [`src/invendx/storage/score_repo.py`](src/invendx/storage/score_repo.py) |
| CLI (`summaries-refresh`, run, export, manual …) | [`src/invendx/cli.py`](src/invendx/cli.py) |
| Optional deps | [`pyproject.toml`](pyproject.toml) — `ui`, `browser` extras |

## Backend / CSV note

- Portfolio / compare **Export CSV** uses cohort row dicts (`vendor_id`, `aum_trillions_hint`, `ria_hint`, etc.); not the Streamlit dataframe **Icon** column.

## Sensible next steps (still optional)

- Portfolio **latest score** column; **source pills** from evidence; **`logo_url`** in YAML.

## Changelog history

See [`CHANGELOG.md`](CHANGELOG.md) — **handoff** at the top, checkpoint **Profile hints (AUM/advisors) + RIA count + summaries refresh** at the bottom, then **Vendor Intelligence UX + narrative markdown reports**.
