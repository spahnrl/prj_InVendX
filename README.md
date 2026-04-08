# 🧠 prj_InVendX

### Evidence-First Vendor Intelligence Pipeline

**Repository:** [github.com/spahnrl/prj_InVendX](https://github.com/spahnrl/prj_InVendX)

---

## 📌 Overview

**prj_InVendX** is an evidence-driven system designed to automate vendor research, normalize fragmented public data, and support faster, more confident platform decisions in wealthtech and fintech environments.

This project was developed from a real-world need:

> Understanding how consulting firms evaluate vendors — and realizing that the hardest part is not process, but getting to *truth quickly*.

Instead of relying on manual research, scattered documentation, and vendor demos, this system builds a structured, repeatable approach to vendor intelligence.

---

## 🎯 Purpose

To answer:

> **Which vendor actually works in the real world — and why?**

---

## 🚫 What This Is NOT

* Not a generic web scraper
* Not a chatbot (planned; not in the current codebase)
* Not a feature comparison tool
* Not reliant on vendor demos

---

## ✅ What This IS

> An **evidence-first decision engine** for vendor evaluation

The system:

* Collects vendor information from **public** sources (Phase 1)
* Normalizes it into structured **evidence** rows in SQLite
* Scores vendors using **explainable, rules-based** logic tied to evidence IDs
* Produces **traceable** exports (CSV, Markdown, summary JSON)

---

## 🧱 Core Principles

* **Evidence is the system of record**
* **One row = one claim / signal**
* **All scores must trace back to evidence** (and source URLs)
* **Rules-based scoring first** (LLM summarization only in a future phase, and not for inventing facts)
* **Real-world usage > marketing claims**

---

## 🔍 Evidence layers (direction vs today)

The long-term target is layered intelligence for each vendor (profile, product, technical, market, risk, competitive context). **Today’s MVP** implements a **public-source pipeline** that feeds the evidence store and summaries; deeper extraction and competitive graphing are **not** fully built yet.

| Layer | MVP today (Phase 1) | Planned |
| ----- | ------------------- | ------- |
| Company / positioning | Keyword and page-level signals from **bounded same-domain crawl** | Richer profile extraction, client lists |
| Product evidence | From crawled official pages + seeded URLs | Dedicated parsers per content type |
| Technical evidence | Link hints to docs/API; optional **GitHub org** metadata | Deeper API/doc mining |
| Market signals | **Careers** pages (keyword scan) | Press feeds, partnerships (beyond crawl) |
| Risk / competitive | Not a dedicated module yet | Heuristics, analyst sources, graph |

---

## 🌐 Data sources (Phase 1 — automated)

What the **current CLI** actually runs:

1. **Official website** — discovery + bounded crawl (robots-aware, rate-limited)
2. **Seeded URLs** from config (e.g. newsroom, careers)
3. **Careers pages** — text scan for platform / integration keywords
4. **GitHub** — public API for org repos when `github_org` is set on the vendor (**requires** a [Personal Access Token](https://github.com/settings/tokens) in the `GITHUB_TOKEN` environment variable — this is **not** the repo URL)

**Not in Phase 1:** LinkedIn scraping, headless browsers, broad forum/review harvesting, LLM scoring.

Lower-confidence sources (analyst sites, reviews) remain **out of scope** until explicitly added.

---

## 🏗️ System architecture

```text
Vendor seeds (YAML) → vendors table (SQLite)
    ↓
Source discovery
    ↓
Bounded crawl (same-domain, robots-aware)
    ↓
Evidence extraction (pages, careers, GitHub)
    ↓
Entity normalization (aliases / fuzzy, minimal)
    ↓
SQLite: evidence + runs + (optional) score runs
    ↓
Vendor summaries (aggregates for a future UI table)
    ↓
Rule-based scoring → score line items (evidence IDs)
    ↓
Exports: CSV, Markdown, summaries JSON
    ↓
Web UI, chatbot, relationship graph — future
```

---

## 🧾 Data model (MVP)

**Vendors (first-class):** stable `vendor_id`, canonical name, primary domain, aliases, seed URLs, primary segment, optional `github_org`.

**Evidence (one row per item):** includes `vendor_id`, `source_type`, `source_url`, `source_date`, `evidence_type`, `product_area`, `entity_1` / `entity_2`, `claim_text`, `confidence`, `tags`, `score_impact_category`, `raw_text_excerpt`, `parser_version`, `run_id`.

**Scores:** derived only; each line item references supporting **evidence IDs**.

---

## ⚙️ Scoring (explainable)

Scoring is **YAML-driven** (`config/score_rules.yaml`). Rules match evidence fields (e.g. evidence type, tags) and attach points to scorecard categories. **By default**, `invendx score` and `run --score` only use evidence from the **latest ingest `run_id`** for that vendor. Use **`--all-evidence`** on those commands to include every stored evidence row. The README examples below are **illustrative**; the live rules file is the source of truth.

| Signal (illustrative) | Impact (example) |
| --------------------- | ---------------- |
| Named integration language on an official page | +Integration-related category |
| Developer/docs links detected | +Developer experience |
| No docs/API hints in crawl | Negative developer signal |
| Careers text with strong stack keywords | +Engineering signal |

> Every persisted score line cites specific evidence rows.

---

## 🖥️ UI / chatbot / graph (planned)

**Future:** sortable vendor table, drill-down to evidence, double-click report flow, comparison views, evidence-backed chatbot, relationship graph. **Not implemented** in this repository today.

---

## 🛠️ Setup

```bash
python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Run commands from the **repository root** so paths like `config/` resolve.

---

## ▶️ CLI (current)

**Vendor argument:** For `discover`, `run`, and `score`, the vendor name is the **first positional** argument (not `--vendor`). For `export`, the first positional is **what** to export (`evidence`, `report`, `scorecard`, `summaries`); the vendor is **`--vendor` / `-v`** (required except for `summaries`).

```bash
invendx vendors sync --config config/vendors.yaml --db data/invendx.db
invendx discover "Charles River" --db data/invendx.db
invendx discover "Charles River" --db data/invendx.db --json
invendx run "Charles River" --db data/invendx.db
invendx run "Charles River" --db data/invendx.db --score
invendx run "Charles River" --db data/invendx.db --score --all-evidence
# optional crawl tuning (defaults: max-pages 40, max-depth 2, delay 0.75s):
invendx run "Charles River" --db data/invendx.db --max-pages 20 --max-depth 1 --delay 1.0
invendx score "Charles River" --db data/invendx.db --rules config/score_rules.yaml
invendx score "Charles River" --db data/invendx.db --rules config/score_rules.yaml --all-evidence
invendx export evidence --vendor "Charles River" --db data/invendx.db --out exports/
invendx export report --vendor "Charles River" --db data/invendx.db --out exports/
invendx export scorecard --vendor "Charles River" --db data/invendx.db --out exports/
invendx export summaries --db data/invendx.db --out exports/
```

`--score` on `run` uses the same scoring path as `invendx score` (after ingest), including **`--all-evidence`**. `export scorecard` and the score section in `export report` always reflect the **most recent persisted score run** in the database (whatever scope was used on that last `score` / `run --score`). They do not re-score; re-run `invendx score` if you change ingest data or want a different scope. **`export evidence`** and the **Recent evidence** part of the report still list all stored rows for the vendor.

**GitHub API:** if you set `github_org` on a vendor, provide a GitHub **personal access token** as `GITHUB_TOKEN`. You can put it in a repo-root `.env` file (gitignored); the CLI loads it automatically via `python-dotenv`. Environment variables already set are not overwritten. The repository link at the top is not a token.

---

## 📐 Agent / contributor guardrails

* **Cursor rules:** [.cursor/rules/](.cursor/rules/)
* **Decision log:** [docs/decisions.md](docs/decisions.md)

---

## 🚀 MVP scope (implemented)

* Vendor seed sync into SQLite **`vendors`**
* Source discovery + bounded same-domain crawler (with robots check)
* Evidence extraction from crawled HTML (keywords, integration language, doc links), careers pages, optional GitHub org repos
* **`vendor_summaries`** refresh (counts, confidence rollup, light profile hints from text)
* Rules-based scoring (standalone or `run --score`; default scope = latest ingest run, opt-in `--all-evidence`) and CSV / Markdown / JSON summary exports, plus **scorecard** CSV and report section for the **latest persisted** score run
* **`vendor_graph`:** stub only (no graph persistence)

---

## 🔮 Future roadmap

### Phase 2 (planned)

* Private document ingestion, interviews, internal notes
* Dedup policy, manual score overrides
* **Relationship graph** implementation (beyond stub)

### Phase 3 (planned)

* HTTP API + UI
* Chatbot with **citation-only** answers over evidence
* Richer recommendation workflows

---

## 💡 Why This Matters

This project transforms:

```text
Scattered vendor noise → Structured decision intelligence
```

It enables:

* faster vendor evaluation
* consistent analysis
* reusable insights
* scalable consulting capability

---

## 🧠 Personal Context

This project directly supports a broader goal:

* Moving from **operations → strategy → decision-making roles**
* Building a **repeatable consulting framework**
* Applying AI/ML thinking to real-world platform problems

It reflects a shift toward:

> **Understanding systems, not just using them**

---

## ⚡ Summary

> prj_InVendX is a system that replaces manual vendor research with structured, evidence-based intelligence — enabling faster, clearer, and more defensible platform decisions.

---

## 📎 Notes

* Phase 1 uses **public** data only
* Outputs are traceable to **source URLs** and evidence rows
* Designed for later extension (UI, chatbot, private data) without changing the evidence-first contract
