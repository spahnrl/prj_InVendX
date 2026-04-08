from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from invendx.models.scoring import ScoreLineItem


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_score_run(
    conn: sqlite3.Connection,
    vendor_id: str,
    vendor_name: str,
    ruleset_version: str,
    items: list[ScoreLineItem],
) -> str:
    score_run_id = str(uuid.uuid4())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO score_runs (score_run_id, vendor_id, vendor_name, created_at, ruleset_version)
        VALUES (?, ?, ?, ?, ?)
        """,
        (score_run_id, vendor_id, vendor_name, _now(), ruleset_version),
    )
    for it in items:
        cur.execute(
            """
            INSERT INTO score_line_items (
                line_id, score_run_id, category, rule_id, points, rationale, evidence_ids_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                it.line_id,
                score_run_id,
                it.category,
                it.rule_id,
                it.points,
                it.rationale,
                json.dumps(it.evidence_ids),
            ),
        )
    conn.commit()
    return score_run_id
