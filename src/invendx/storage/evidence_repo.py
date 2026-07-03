from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from invendx.models.evidence import EvidenceRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_run(
    conn: sqlite3.Connection,
    run_id: str,
    vendor_id: str,
    parser_version: str,
    notes: str | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO runs (run_id, vendor_id, started_at, parser_version, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, vendor_id, _now(), parser_version, notes),
    )
    conn.commit()


def insert_evidence(conn: sqlite3.Connection, records: list[EvidenceRecord]) -> None:
    if not records:
        return
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO evidence (
            evidence_id, vendor_id, vendor_name, run_id, source_type, source_url,
            source_date, source_title, evidence_type, product_area, entity_1, entity_2,
            claim_text, confidence, tags, score_impact_category, raw_text_excerpt,
            parser_version, collected_at, dedupe_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r.evidence_id,
                r.vendor_id,
                r.vendor_name,
                r.run_id,
                r.source_type,
                r.source_url,
                r.source_date,
                r.source_title,
                r.evidence_type,
                r.product_area,
                r.entity_1,
                r.entity_2,
                r.claim_text,
                r.confidence,
                r.tags,
                r.score_impact_category,
                r.raw_text_excerpt,
                r.parser_version,
                r.collected_at,
                r.dedupe_hash,
            )
            for r in records
        ],
    )
    conn.commit()


def get_latest_run_id_for_vendor(conn: sqlite3.Connection, vendor_id: str) -> str | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT run_id FROM runs
        WHERE vendor_id = ?
        ORDER BY started_at DESC, run_id DESC
        LIMIT 1
        """,
        (vendor_id,),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def get_latest_run_row_for_vendor(conn: sqlite3.Connection, vendor_id: str) -> dict | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT run_id, vendor_id, started_at, parser_version, notes FROM runs
        WHERE vendor_id = ?
        ORDER BY started_at DESC, run_id DESC
        LIMIT 1
        """,
        (vendor_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def update_run_notes(conn: sqlite3.Connection, run_id: str, notes: str) -> None:
    cur = conn.cursor()
    cur.execute("UPDATE runs SET notes = ? WHERE run_id = ?", (notes, run_id))
    conn.commit()


def vendor_has_dedupe_hash(
    conn: sqlite3.Connection, vendor_id: str, dedupe_hash: str | None
) -> bool:
    if not dedupe_hash:
        return False
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM evidence WHERE vendor_id = ? AND dedupe_hash = ? LIMIT 1",
        (vendor_id, dedupe_hash),
    )
    return cur.fetchone() is not None


def list_evidence_for_vendor(
    conn: sqlite3.Connection, vendor_id: str, *, run_id: str | None = None
) -> list[EvidenceRecord]:
    cur = conn.cursor()
    if run_id is None:
        cur.execute(
            "SELECT * FROM evidence WHERE vendor_id = ? ORDER BY collected_at",
            (vendor_id,),
        )
    else:
        cur.execute(
            """
            SELECT * FROM evidence
            WHERE vendor_id = ? AND run_id = ?
            ORDER BY collected_at
            """,
            (vendor_id, run_id),
        )
    return [_row_to_model(dict(r)) for r in cur.fetchall()]


def _row_to_model(d: dict) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=d["evidence_id"],
        vendor_id=d["vendor_id"],
        vendor_name=d["vendor_name"],
        run_id=d["run_id"],
        source_type=d["source_type"],
        source_url=d["source_url"],
        source_date=d.get("source_date"),
        source_title=d.get("source_title"),
        evidence_type=d["evidence_type"],
        product_area=d.get("product_area"),
        entity_1=d.get("entity_1"),
        entity_2=d.get("entity_2"),
        claim_text=d["claim_text"],
        confidence=d["confidence"],
        tags=d.get("tags") or "",
        score_impact_category=d.get("score_impact_category"),
        raw_text_excerpt=d.get("raw_text_excerpt"),
        parser_version=d["parser_version"],
        collected_at=d["collected_at"],
        dedupe_hash=d.get("dedupe_hash"),
    )
