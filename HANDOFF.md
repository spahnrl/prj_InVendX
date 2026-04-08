# Handoff checkpoint — InVendX UI (Streamlit)

Use this file to continue in a new chat without re-deriving context.

## Quick start

**Windows:** double-click [`run_streamlit.bat`](run_streamlit.bat) in the repo root (uses `.venv` or `venv` if present). First-time setup still needs: `pip install -e ".[ui]"`.

```powershell
cd <repo-root>
pip install -e ".[ui]"
streamlit run operator_app.py
```

- **Vendor Intelligence:** Read-only portfolio (`vendors` ⟕ `vendor_summaries`), search, CSV export, favicon column from `primary_domain`, report preview + full markdown in expander + download.
- **Admin / Operator:** Sidebar paths (DB, `vendors.yaml`, exports), sync, ingest / run+score / exports, log, latest score panel.

## Key files

| Area | Path |
|------|------|
| Streamlit entry | [`operator_app.py`](operator_app.py) |
| CLI | [`src/invendx/cli.py`](src/invendx/cli.py) |
| Summaries query shape | [`src/invendx/pipeline/report_builder.py`](src/invendx/pipeline/report_builder.py) (`export_summaries_json`, `export_vendor_markdown`) |
| Optional deps | [`pyproject.toml`](pyproject.toml) — `project.optional-dependencies.ui` |

## Backend boundary

- **No** new tables or product features were added for the UI; analyst actions use existing DB reads + `export_vendor_markdown`.
- **CSV export** from the portfolio tab uses the original filtered row dicts (snake_case), not the display-only dataframe with `Icon` URLs.

## Sensible next steps (not done)

- Optional **latest score** / points column on the portfolio table (join `score_runs`).
- **Source pills** or aggregates from `evidence` (extra queries).
- Optional **`logo_url`** (or similar) in YAML + schema for curated icons instead of favicons.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) — checkpoints **MVP Backend + First Operator UI** and **Two-tab Streamlit — Vendor Intelligence + Admin/Operator**.
