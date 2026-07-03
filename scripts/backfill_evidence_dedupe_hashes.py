"""One-off: set evidence.dedupe_hash for rows where it is NULL (run from repo root).

Usage:
  python scripts/backfill_evidence_dedupe_hashes.py --db data/invendx.db
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from invendx.pipeline.evidence_fingerprint import content_fingerprint_hex


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=Path("data/invendx.db"))
    args = p.parse_args()
    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT evidence_id, vendor_id, evidence_type, source_url, claim_text, tags
        FROM evidence
        WHERE dedupe_hash IS NULL OR dedupe_hash = ''
        """
    )
    rows = cur.fetchall()
    n = 0
    for r in rows:
        h = content_fingerprint_hex(
            str(r["vendor_id"]),
            str(r["evidence_type"]),
            str(r["source_url"]),
            str(r["claim_text"]),
            str(r["tags"] or ""),
        )
        cur.execute("UPDATE evidence SET dedupe_hash = ? WHERE evidence_id = ?", (h, r["evidence_id"]))
        n += 1
    conn.commit()
    conn.close()
    print(f"Updated {n} evidence row(s) in {args.db}")


if __name__ == "__main__":
    main()
