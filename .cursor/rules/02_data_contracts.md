# Data contracts

- **Evidence** is the system of record.
- **One row** per evidence item / claim / signal.
- **SQLite** is the source of truth for MVP.
- Include a **first-class `vendors` table** from day one (stable `vendor_id`, canonical fields, seeds).
- **Scores are derived**, not primary data.
- Every **score line item** must reference **supporting evidence IDs**.
- Preserve **source_url**, **source_type**, **source_date**, **raw_text_excerpt**, **parser_version**, and **run_id** on evidence.
- Do **not** collapse or summarize in a way that **loses traceability** to sources and excerpts.
