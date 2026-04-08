from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from invendx.models.vendor import VendorRecord, VendorSeed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_vendor(conn: sqlite3.Connection, seed: VendorSeed, vendor_id: str | None = None) -> VendorRecord:
    """Insert or update vendor by (canonical_name, primary_domain). Preserves vendor_id if row exists."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT vendor_id FROM vendors
        WHERE canonical_name = ? AND primary_domain = ?
        """,
        (seed.canonical_name, seed.primary_domain),
    )
    row = cur.fetchone()
    aliases_json = json.dumps(seed.aliases)
    seed_urls_json = json.dumps(seed.seed_urls)
    ts = _now()
    if row:
        vid = row[0]
        cur.execute(
            """
            UPDATE vendors SET
                aliases_json = ?, seed_urls_json = ?, primary_segment = ?, github_org = ?, updated_at = ?
            WHERE vendor_id = ?
            """,
            (aliases_json, seed_urls_json, seed.primary_segment, seed.github_org, ts, vid),
        )
    else:
        import uuid

        vid = vendor_id or str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO vendors (
                vendor_id, canonical_name, primary_domain, aliases_json, seed_urls_json,
                primary_segment, github_org, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vid,
                seed.canonical_name,
                seed.primary_domain,
                aliases_json,
                seed_urls_json,
                seed.primary_segment,
                seed.github_org,
                ts,
                ts,
            ),
        )
    conn.commit()
    return get_vendor_by_id(conn, vid)


def get_vendor_by_id(conn: sqlite3.Connection, vendor_id: str) -> VendorRecord:
    cur = conn.cursor()
    cur.execute("SELECT * FROM vendors WHERE vendor_id = ?", (vendor_id,))
    row = cur.fetchone()
    if not row:
        raise KeyError(vendor_id)
    return _row_to_record(row)


def get_vendor_by_name_domain(conn: sqlite3.Connection, name: str, domain: str) -> VendorRecord | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM vendors WHERE canonical_name = ? AND primary_domain = ?",
        (name, domain),
    )
    row = cur.fetchone()
    return _row_to_record(row) if row else None


def find_vendor_by_canonical_name(conn: sqlite3.Connection, canonical_name: str) -> VendorRecord | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM vendors WHERE canonical_name = ?", (canonical_name,))
    row = cur.fetchone()
    return _row_to_record(row) if row else None


def list_vendors(conn: sqlite3.Connection) -> list[VendorRecord]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM vendors ORDER BY canonical_name")
    return [_row_to_record(r) for r in cur.fetchall()]


def _row_to_record(row: sqlite3.Row) -> VendorRecord:
    d = dict(row)
    return VendorRecord(
        vendor_id=d["vendor_id"],
        canonical_name=d["canonical_name"],
        primary_domain=d["primary_domain"],
        aliases=json.loads(d["aliases_json"] or "[]"),
        seed_urls=json.loads(d["seed_urls_json"] or "{}"),
        primary_segment=d.get("primary_segment") or "",
        github_org=d.get("github_org"),
        created_at=d.get("created_at") or "",
        updated_at=d.get("updated_at") or "",
    )
