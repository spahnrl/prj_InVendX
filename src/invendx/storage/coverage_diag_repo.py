"""Read-only aggregates for per-vendor ingest / evidence / summary / score diagnostics."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _profile_metrics_present(raw: str | None) -> bool:
    if raw is None or not str(raw).strip():
        return False
    try:
        d = json.loads(raw)
        return isinstance(d, dict) and len(d) > 0
    except json.JSONDecodeError:
        return False


def _int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


_COVERAGE_SQL = """
SELECT
    v.vendor_id,
    v.canonical_name,
    v.primary_domain,
    v.primary_segment,
    COALESCE(rc.ingest_run_count, 0) AS ingest_run_count,
    rl.latest_ingest_run_id,
    rl.latest_ingest_at,
    COALESCE(ev.evidence_count, 0) AS evidence_count,
    COALESCE(ev.distinct_source_url_count, 0) AS distinct_source_url_count,
    ev.latest_evidence_at,
    CASE WHEN s.vendor_id IS NOT NULL THEN 1 ELSE 0 END AS summary_row_present,
    s.updated_at AS summary_updated_at,
    s.confidence_rollup,
    s.profile_metrics_json,
    sc.latest_score_run_id,
    sc.latest_score_created_at,
    COALESCE(sc.latest_score_line_item_count, 0) AS latest_score_line_item_count
FROM vendors v
LEFT JOIN (
    SELECT vendor_id, COUNT(*) AS ingest_run_count
    FROM runs
    GROUP BY vendor_id
) rc ON rc.vendor_id = v.vendor_id
LEFT JOIN (
    SELECT vendor_id, run_id AS latest_ingest_run_id, started_at AS latest_ingest_at
    FROM (
        SELECT
            vendor_id,
            run_id,
            started_at,
            /* tie-break same started_at for two runs */
            ROW_NUMBER() OVER (
                PARTITION BY vendor_id
                ORDER BY started_at DESC, run_id DESC
            ) AS rn
        FROM runs
    ) x
    WHERE x.rn = 1
) rl ON rl.vendor_id = v.vendor_id
LEFT JOIN (
    SELECT
        vendor_id,
        COUNT(*) AS evidence_count,
        COUNT(DISTINCT source_url) AS distinct_source_url_count,
        MAX(collected_at) AS latest_evidence_at
    FROM evidence
    GROUP BY vendor_id
) ev ON ev.vendor_id = v.vendor_id
LEFT JOIN vendor_summaries s ON s.vendor_id = v.vendor_id
LEFT JOIN (
    SELECT
        vendor_id,
        score_run_id AS latest_score_run_id,
        created_at AS latest_score_created_at,
        (
            SELECT COUNT(*)
            FROM score_line_items li
            WHERE li.score_run_id = x.score_run_id
        ) AS latest_score_line_item_count
    FROM (
        SELECT
            vendor_id,
            score_run_id,
            created_at,
            ROW_NUMBER() OVER (
                PARTITION BY vendor_id
                ORDER BY created_at DESC, score_run_id DESC
            ) AS rn
        FROM score_runs
    ) x
    WHERE x.rn = 1
) sc ON sc.vendor_id = v.vendor_id
ORDER BY v.canonical_name
"""


def fetch_coverage_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return one diagnostic row per vendor with raw DB fields and derived booleans."""
    cur = conn.cursor()
    cur.execute(_COVERAGE_SQL)
    cols = [c[0] for c in cur.description]
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        d = dict(zip(cols, row, strict=True))
        pm_raw = d.get("profile_metrics_json")
        d["ingest_run_count"] = _int(d.get("ingest_run_count"))
        d["evidence_count"] = _int(d.get("evidence_count"))
        d["distinct_source_url_count"] = _int(d.get("distinct_source_url_count"))
        d["latest_score_line_item_count"] = _int(d.get("latest_score_line_item_count"))
        d["summary_row_present"] = bool(_int(d.get("summary_row_present")))
        d["profile_metrics_present"] = _profile_metrics_present(
            pm_raw if isinstance(pm_raw, str) else None
        )
        d["latest_score_run_present"] = d.get("latest_score_run_id") is not None
        out.append(d)
    return out
