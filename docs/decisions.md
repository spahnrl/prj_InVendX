# Architecture decisions (prj_InVendX)

Short log so we do not re-litigate choices each session. Add dated entries when something meaningful changes.

## 2026-04-07

- **`GITHUB_TOKEN`**: Loaded from a repo-root `.env` via `python-dotenv` when running the CLI (and at GitHub collection time). Use `.env.example` as a template; keep `.env` out of git.

- **Storage**: SQLite is the MVP source of truth; CSV/MD are exports only.
- **Vendors**: First-class `vendors` table with stable `vendor_id` (UUID); YAML seeds upsert by `(canonical_name, primary_domain)`.
- **Evidence**: One row per signal/claim; scores and summaries are derived and must cite `evidence_id`s.
- **HTTP**: `httpx` + `tenacity` retries; `urllib.robotparser` per-origin cache for robots.txt.
- **Crawl**: Bounded same-domain BFS; conservative defaults for depth, page count, and delay.
- **Graph**: `vendor_graph.py` is a stub in Phase 1; no entity/edge persistence yet.
- **UI / chatbot / LLM scoring**: Explicitly out of scope for Phase 1 (see `.cursor/rules/`).
- **Project guardrails**: [`.cursor/rules/`](../.cursor/rules/) (`00`–`04`) and this file are the canonical “why we built it this way” hints for agents.
- **Repo hygiene**: [`.gitignore`](../.gitignore) excludes `data/`, `.env`, `exports/`, and tool caches.
