import uuid

from invendx import PARSER_VERSION
from invendx.models.evidence import EvidenceRecord
from invendx.models.vendor import VendorSeed
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, vendor_repo


def test_vendor_upsert_and_evidence_roundtrip(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    seed = VendorSeed(
        canonical_name="TestCo",
        primary_domain="example.com",
        primary_segment="Test",
        aliases=["TC"],
        seed_urls={"press": ["https://example.com/news"]},
    )
    v = vendor_repo.upsert_vendor(conn, seed)
    run_id = str(uuid.uuid4())
    evidence_repo.insert_run(conn, run_id, v.vendor_id, PARSER_VERSION)
    rec = EvidenceRecord(
        evidence_id=str(uuid.uuid4()),
        vendor_id=v.vendor_id,
        vendor_name=v.canonical_name,
        run_id=run_id,
        source_type="official_site",
        source_url="https://example.com",
        evidence_type="page_crawl",
        claim_text="hello",
        confidence="high",
        parser_version=PARSER_VERSION,
        collected_at="2026-01-01T00:00:00+00:00",
    )
    evidence_repo.insert_evidence(conn, [rec])
    rows = evidence_repo.list_evidence_for_vendor(conn, v.vendor_id)
    assert len(rows) == 1
    assert rows[0].claim_text == "hello"
