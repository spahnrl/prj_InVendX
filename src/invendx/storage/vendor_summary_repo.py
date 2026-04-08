from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_summary(
    conn: sqlite3.Connection,
    vendor_id: str,
    source_count: int,
    evidence_count: int,
    last_evidence_at: str | None,
    confidence_rollup: float,
    profile_metrics: dict,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO vendor_summaries (
            vendor_id, source_count, evidence_count, last_evidence_at,
            confidence_rollup, profile_metrics_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(vendor_id) DO UPDATE SET
            source_count = excluded.source_count,
            evidence_count = excluded.evidence_count,
            last_evidence_at = excluded.last_evidence_at,
            confidence_rollup = excluded.confidence_rollup,
            profile_metrics_json = excluded.profile_metrics_json,
            updated_at = excluded.updated_at
        """,
        (
            vendor_id,
            source_count,
            evidence_count,
            last_evidence_at,
            confidence_rollup,
            json.dumps(profile_metrics),
            _now(),
        ),
    )
    conn.commit()
