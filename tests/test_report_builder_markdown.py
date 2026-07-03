"""Human-readable vendor markdown report (summary, scorecard, recent evidence)."""

from __future__ import annotations

import uuid
from pathlib import Path

from invendx import PARSER_VERSION
from invendx.models.evidence import EvidenceRecord
from invendx.models.vendor import VendorSeed
from invendx.pipeline import report_builder
from invendx.pipeline.score_engine import evaluate_rules
from invendx.config_loader import load_score_rules
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, score_repo, vendor_repo
from invendx.storage import vendor_summary_repo


def test_export_vendor_markdown_human_readable_sections(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    v = vendor_repo.upsert_vendor(
        conn,
        VendorSeed(
            canonical_name="ReportCo",
            primary_domain="report.example",
            primary_segment="RIA / tech",
        ),
    )
    rid = str(uuid.uuid4())
    evidence_repo.insert_run(conn, rid, v.vendor_id, PARSER_VERSION)
    ev = EvidenceRecord(
        evidence_id="ev-doc",
        vendor_id=v.vendor_id,
        vendor_name=v.canonical_name,
        run_id=rid,
        source_type="official_site",
        source_url="https://report.example/docs",
        source_title="API reference",
        evidence_type="dev_portal_signal",
        claim_text="OpenAPI 3.0 specification available for partners.",
        confidence="high",
        tags="api",
        raw_text_excerpt="Partner API uses OAuth2 client credentials.",
        parser_version=PARSER_VERSION,
        collected_at="2026-04-08T12:00:00+00:00",
    )
    evidence_repo.insert_evidence(conn, [ev])
    vendor_summary_repo.upsert_summary(
        conn,
        vendor_id=v.vendor_id,
        source_count=1,
        evidence_count=1,
        last_evidence_at="2026-04-08T12:00:00+00:00",
        confidence_rollup=1.0,
        profile_metrics={
            "aum_trillions_hint": "1.2",
            "advisors_or_institutions_hint": "",
            "ria_hint": 4200,
        },
    )
    cfg = load_score_rules("config/score_rules.yaml")
    items = evaluate_rules(cfg, [ev])
    score_repo.insert_score_run(conn, v.vendor_id, v.canonical_name, cfg.ruleset_version, items)

    out_md = tmp_path / "r.md"
    report_builder.export_vendor_markdown(conn, v.vendor_id, out_md)
    md = out_md.read_text(encoding="utf-8")

    assert "## How to read this report" in md
    assert "machine-generated" in md.lower()
    assert "## Summary" in md
    assert "**Last evidence (date)**" in md or "2026-04-08" in md
    assert "mean of per-row labels" in md
    assert "AUM (trillions, hint)" in md
    assert "1.2" in md
    assert "RIA firms (count, hint)" in md
    assert "4200" in md
    assert "`profile_metrics_json`" not in md

    assert "## At a glance" in md
    assert "Strongest scorecard categories" in md or "Developer signals" in md

    assert "## Latest scorecard" in md
    assert "*Why*:" in md
    assert "Developer experience" in md
    assert "`ev-doc`:" in md

    assert "## Recent evidence" in md
    assert "Concrete signals" in md
    assert "### Developer" in md
    assert "## Distinct source URLs" in md
    assert "export evidence" in md.lower()
    assert "API reference" in md
    assert "OpenAPI 3.0" in md
    assert "confidence: high" in md
