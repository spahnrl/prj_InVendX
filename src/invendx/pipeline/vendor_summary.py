from __future__ import annotations

import sqlite3

from invendx.extract.patterns import extract_profile_metrics
from invendx.storage import vendor_summary_repo


def _confidence_to_score(c: str) -> float:
    m = {"high": 1.0, "medium": 0.6, "low": 0.3}
    return m.get((c or "").lower(), 0.5)


def refresh_vendor_summary(conn: sqlite3.Connection, vendor_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(DISTINCT source_url) FROM evidence WHERE vendor_id = ?
        """,
        (vendor_id,),
    )
    source_count = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM evidence WHERE vendor_id = ?", (vendor_id,))
    evidence_count = int(cur.fetchone()[0])
    cur.execute(
        """
        SELECT MAX(collected_at) FROM evidence WHERE vendor_id = ?
        """,
        (vendor_id,),
    )
    last_row = cur.fetchone()[0]

    cur.execute("SELECT confidence, claim_text, raw_text_excerpt FROM evidence WHERE vendor_id = ?", (vendor_id,))
    rows = cur.fetchall()
    if rows:
        rollup = sum(_confidence_to_score(r[0]) for r in rows) / len(rows)
    else:
        rollup = 0.0

    profile: dict = {}
    for _conf, claim, excerpt in rows:
        blob = f"{claim or ''}\n{excerpt or ''}"
        for k, v in extract_profile_metrics(blob).items():
            if k == "ria_hint" and isinstance(v, int):
                prev = profile.get("ria_hint")
                profile["ria_hint"] = v if not isinstance(prev, int) else max(prev, v)
            else:
                profile.setdefault(k, v)

    vendor_summary_repo.upsert_summary(
        conn,
        vendor_id=vendor_id,
        source_count=source_count,
        evidence_count=evidence_count,
        last_evidence_at=last_row,
        confidence_rollup=round(rollup, 4),
        profile_metrics=profile,
    )
