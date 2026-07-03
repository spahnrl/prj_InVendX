"""CRUD for staged manual URL/capture rows before promotion to ``evidence``."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    return {k: d[k] for k in d}


def insert_intake(
    conn: sqlite3.Connection,
    *,
    vendor_id: str,
    source_url: str,
    source_type: str,
    reason_flagged: str,
    instructions_key: str,
    operator_notes: str | None = None,
    created_by: str | None = None,
    intake_id: str | None = None,
    skip_if_url_exists: bool = False,
) -> str | None:
    """Insert a queue row. If ``skip_if_url_exists`` and the vendor already has a non-discarded
    row for the same ``source_url``, return ``None`` (no insert).
    """
    if skip_if_url_exists and vendor_has_non_discarded_intake_for_url(conn, vendor_id, source_url):
        return None
    iid = intake_id or str(uuid.uuid4())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO manual_intake_queue (
            intake_id, vendor_id, source_url, source_type, reason_flagged,
            instructions_key, status, operator_notes, created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (iid, vendor_id, source_url, source_type, reason_flagged, instructions_key, operator_notes, _now(), created_by),
    )
    conn.commit()
    return iid


def vendor_has_non_discarded_intake_for_url(
    conn: sqlite3.Connection, vendor_id: str, source_url: str
) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM manual_intake_queue
        WHERE vendor_id = ? AND source_url = ? AND status != 'discarded'
        LIMIT 1
        """,
        (vendor_id, source_url),
    )
    return cur.fetchone() is not None


def get_intake(conn: sqlite3.Connection, intake_id: str) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM manual_intake_queue WHERE intake_id = ?", (intake_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_intakes_for_vendor(
    conn: sqlite3.Connection,
    vendor_id: str,
    *,
    include_ingested: bool = True,
    include_discarded: bool = False,
) -> list[dict]:
    conditions = ["vendor_id = ?"]
    params: list = [vendor_id]
    if not include_ingested:
        conditions.append("status != 'ingested'")
    if not include_discarded:
        conditions.append("status != 'discarded'")
    where = " AND ".join(conditions)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT * FROM manual_intake_queue
        WHERE {where}
        ORDER BY created_at DESC, intake_id DESC
        """,
        params,
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def save_capture(
    conn: sqlite3.Connection,
    intake_id: str,
    *,
    captured_text: str,
    captured_by: str | None,
    capture_method: str = "paste",
) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE manual_intake_queue SET
            captured_text = ?,
            captured_at = ?,
            captured_by = ?,
            capture_method = ?,
            status = 'captured'
        WHERE intake_id = ? AND status IN ('pending', 'captured')
        """,
        (captured_text, _now(), captured_by, capture_method, intake_id),
    )
    conn.commit()
    return cur.rowcount > 0


def update_operator_notes(conn: sqlite3.Connection, intake_id: str, operator_notes: str | None) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE manual_intake_queue SET operator_notes = ?
        WHERE intake_id = ? AND status IN ('pending', 'captured')
        """,
        (operator_notes, intake_id),
    )
    conn.commit()
    return cur.rowcount > 0


def mark_discarded(conn: sqlite3.Connection, intake_id: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE manual_intake_queue SET status = 'discarded'
        WHERE intake_id = ? AND status IN ('pending', 'captured')
        """,
        (intake_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def mark_promoted(
    conn: sqlite3.Connection,
    intake_id: str,
    *,
    promoted_run_id: str,
    evidence_ids: list[str],
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE manual_intake_queue SET
            status = 'ingested',
            promoted_run_id = ?,
            promoted_evidence_ids_json = ?
        WHERE intake_id = ?
        """,
        (promoted_run_id, json.dumps(evidence_ids), intake_id),
    )
    conn.commit()
