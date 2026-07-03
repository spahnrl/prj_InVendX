"""refresh_vendor_summary aggregates profile_metrics (including max ria_hint)."""

from __future__ import annotations

import json
import uuid

from invendx import PARSER_VERSION
from invendx.models.evidence import EvidenceRecord
from invendx.models.vendor import VendorSeed
from invendx.pipeline.vendor_summary import refresh_vendor_summary
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, vendor_repo


def test_refresh_vendor_summary_ria_hint_max(tmp_path) -> None:
    db = tmp_path / "s.db"
    conn = connect(db)
    init_schema(conn)
    v = vendor_repo.upsert_vendor(
        conn,
        VendorSeed(
            canonical_name="RiaCo",
            primary_domain="ria.example",
            primary_segment="RIA / tech",
        ),
    )
    rid = str(uuid.uuid4())
    evidence_repo.insert_run(conn, rid, v.vendor_id, PARSER_VERSION)
    rows = [
        EvidenceRecord(
            evidence_id="e1",
            vendor_id=v.vendor_id,
            vendor_name=v.canonical_name,
            run_id=rid,
            source_type="official_site",
            source_url="https://ria.example/a",
            source_title="a",
            evidence_type="press_claim",
            claim_text="We serve 2,000+ RIAs in the region.",
            confidence="high",
            tags="",
            raw_text_excerpt="",
            parser_version=PARSER_VERSION,
            collected_at="2026-04-08T12:00:00+00:00",
        ),
        EvidenceRecord(
            evidence_id="e2",
            vendor_id=v.vendor_id,
            vendor_name=v.canonical_name,
            run_id=rid,
            source_type="official_site",
            source_url="https://ria.example/b",
            source_title="b",
            evidence_type="press_claim",
            claim_text="Join 5,000+ RIAs nationwide.",
            confidence="high",
            tags="",
            raw_text_excerpt="",
            parser_version=PARSER_VERSION,
            collected_at="2026-04-08T12:01:00+00:00",
        ),
    ]
    evidence_repo.insert_evidence(conn, rows)
    refresh_vendor_summary(conn, v.vendor_id)
    cur = conn.cursor()
    cur.execute(
        "SELECT profile_metrics_json FROM vendor_summaries WHERE vendor_id = ?",
        (v.vendor_id,),
    )
    raw = cur.fetchone()[0]
    pm = json.loads(raw or "{}")
    assert pm.get("ria_hint") == 5000
