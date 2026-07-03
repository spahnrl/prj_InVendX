"""Cross-run fingerprint dedupe on insert (cli.run path simulation)."""

from __future__ import annotations

import uuid

from invendx import PARSER_VERSION
from invendx.models.evidence import EvidenceRecord
from invendx.models.vendor import VendorSeed
from invendx.pipeline.evidence_fingerprint import assign_dedupe_hashes
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, vendor_repo


def _one_claim(vendor_id: str, name: str, run_id: str, eid: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=eid,
        vendor_id=vendor_id,
        vendor_name=name,
        run_id=run_id,
        source_type="official_site",
        source_url="https://dup.example/",
        evidence_type="absence_signal",
        claim_text="Same absence claim.",
        confidence="low",
        tags="absence,developer_docs",
        parser_version=PARSER_VERSION,
        collected_at="2026-01-01T12:00:00+00:00",
    )


def _filter_insert(conn, records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Mirror cli.run batching: in-batch + DB fingerprint dedupe."""
    records = assign_dedupe_hashes(records)
    to_insert: list[EvidenceRecord] = []
    pending_fp: set[str] = set()
    for r in records:
        h = r.dedupe_hash or ""
        if h in pending_fp:
            continue
        if h and evidence_repo.vendor_has_dedupe_hash(conn, r.vendor_id, h):
            continue
        if h:
            pending_fp.add(h)
        to_insert.append(r)
    return to_insert


def test_second_identical_fingerprint_skipped_across_runs(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    v = vendor_repo.upsert_vendor(
        conn,
        VendorSeed(canonical_name="DupCo", primary_domain="dup.example", primary_segment=""),
    )
    rid1, rid2 = str(uuid.uuid4()), str(uuid.uuid4())
    evidence_repo.insert_run(conn, rid1, v.vendor_id, PARSER_VERSION)
    evidence_repo.insert_run(conn, rid2, v.vendor_id, PARSER_VERSION)

    b1 = _filter_insert(conn, [_one_claim(v.vendor_id, v.canonical_name, rid1, "a")])
    evidence_repo.insert_evidence(conn, b1)
    b2 = _filter_insert(conn, [_one_claim(v.vendor_id, v.canonical_name, rid2, "b")])
    assert b2 == []
    assert len(evidence_repo.list_evidence_for_vendor(conn, v.vendor_id)) == 1
