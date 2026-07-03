from __future__ import annotations

import uuid

from invendx import PARSER_VERSION
from invendx.models.evidence import EvidenceRecord
from invendx.models.vendor import VendorSeed
from invendx.storage.coverage_diag_repo import fetch_coverage_rows
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, score_repo, vendor_repo
from invendx.pipeline import report_builder
from invendx.storage.vendor_summary_repo import upsert_summary


def test_fetch_coverage_rows_empty_vendor_and_runs(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    seed = VendorSeed(
        canonical_name="Solo",
        primary_domain="solo.example",
        primary_segment="",
    )
    v = vendor_repo.upsert_vendor(conn, seed)
    rows = fetch_coverage_rows(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r["vendor_id"] == v.vendor_id
    assert r["ingest_run_count"] == 0
    assert r["evidence_count"] == 0
    assert r["latest_score_run_present"] is False


def test_fetch_coverage_rows_with_run_evidence_and_score(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    seed = VendorSeed(
        canonical_name="FullCo",
        primary_domain="full.example",
        primary_segment="Seg",
    )
    v = vendor_repo.upsert_vendor(conn, seed)
    run_id = str(uuid.uuid4())
    evidence_repo.insert_run(conn, run_id, v.vendor_id, PARSER_VERSION)
    urls = ["https://a.example/1", "https://b.example/2", "https://c.example/3"]
    recs: list[EvidenceRecord] = []
    for i in range(8):
        recs.append(
            EvidenceRecord(
                evidence_id=str(uuid.uuid4()),
                vendor_id=v.vendor_id,
                vendor_name=v.canonical_name,
                run_id=run_id,
                source_type="official_site",
                source_url=urls[i % 3],
                evidence_type="page_crawl",
                claim_text=f"claim {i}",
                confidence="high",
                parser_version=PARSER_VERSION,
                collected_at=f"2026-01-0{i + 1}T00:00:00+00:00",
            )
        )
    evidence_repo.insert_evidence(conn, recs)
    upsert_summary(
        conn,
        vendor_id=v.vendor_id,
        source_count=3,
        evidence_count=8,
        last_evidence_at="2026-01-08T00:00:00+00:00",
        confidence_rollup=1.0,
        profile_metrics={"aum_trillions_hint": "$1T"},
    )
    score_repo.insert_score_run(conn, v.vendor_id, v.canonical_name, "rules-v1", [])

    rows = fetch_coverage_rows(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r["ingest_run_count"] == 1
    assert r["evidence_count"] == 8
    assert r["distinct_source_url_count"] == 3
    assert r["summary_row_present"] is True
    assert r["profile_metrics_present"] is True
    assert r["latest_score_run_present"] is True
    assert r["latest_score_line_item_count"] == 0
    assert r["latest_ingest_run_id"] == run_id


def test_export_coverage_csv_roundtrip(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    seed = VendorSeed(canonical_name="CsvCo", primary_domain="csv.example", primary_segment="")
    vendor_repo.upsert_vendor(conn, seed)
    out = tmp_path / "vendor_coverage.csv"
    report_builder.export_coverage_csv(conn, out)
    conn.close()
    text = out.read_text(encoding="utf-8")
    assert "canonical_name" in text
    assert "CsvCo" in text
    assert "coverage_status" in text
