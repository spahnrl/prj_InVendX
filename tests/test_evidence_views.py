from __future__ import annotations

from invendx.models.evidence import EvidenceRecord
from invendx.pipeline.evidence_views import (
    dedupe_evidence_for_scoring,
    recent_evidence_lines_for_report,
    suppress_developer_docs_absence_when_dev_portal_present,
)


def _row(
    *,
    eid: str,
    run_id: str,
    et: str = "page_crawl",
    url: str = "https://a",
    claim: str = "c",
    at: str = "2026-01-01T00:00:00+00:00",
    dh: str | None = None,
    tags: str = "",
    source_title: str | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=eid,
        vendor_id="v",
        vendor_name="V",
        run_id=run_id,
        source_type="official_site",
        source_url=url,
        evidence_type=et,
        claim_text=claim,
        source_title=source_title,
        confidence="medium",
        tags=tags,
        parser_version="1",
        collected_at=at,
        dedupe_hash=dh,
    )


def test_recent_evidence_fallback_filters_legacy_soft_error_titles() -> None:
    ev = [
        _row(
            eid="junk",
            run_id="old",
            url="https://x/y",
            claim="Crawled page: 404 Not Found",
            source_title="404 Not Found",
            at="2026-01-01T00:00:00+00:00",
        ),
        _row(
            eid="ok",
            run_id="older",
            url="https://x/z",
            claim="Crawled page: Product",
            source_title="Product overview",
            at="2026-01-02T00:00:00+00:00",
        ),
    ]
    lines, cap = recent_evidence_lines_for_report(ev, latest_run_id="latest-empty", max_lines=25)
    assert "across all runs" in cap
    blob = "\n".join(lines)
    assert not any("404 Not Found" in ln for ln in lines)
    assert "Product overview" in blob or "Product" in blob
    assert "### Site and content" in blob


def test_recent_evidence_collapses_same_dev_portal_claim_across_urls() -> None:
    """Many pages with identical dev_portal claim → one bullet, distinct page count."""
    ev = [
        _row(
            eid="a",
            run_id="r",
            et="dev_portal_signal",
            url="https://example.com/case-a",
            claim="Link to developer/docs area discovered: https://developers.example.com/",
            at="2026-01-03T00:00:00+00:00",
            source_title="Case A",
        ),
        _row(
            eid="b",
            run_id="r",
            et="dev_portal_signal",
            url="https://example.com/case-b",
            claim="Link to developer/docs area discovered: https://developers.example.com/",
            at="2026-01-02T00:00:00+00:00",
            source_title="Case B",
        ),
    ]
    lines, _cap = recent_evidence_lines_for_report(ev, latest_run_id="r", max_lines=25)
    blob = "\n".join(lines)
    assert blob.count("developers.example.com") >= 1
    assert "**2** distinct pages share this claim" in blob


def test_recent_evidence_prefers_latest_run_and_collapses() -> None:
    ev = [
        _row(eid="1", run_id="old", claim="same", at="2026-01-01T00:00:00+00:00"),
        _row(eid="2", run_id="new", claim="same", at="2026-01-02T00:00:00+00:00"),
        _row(eid="3", run_id="new", claim="same", at="2026-01-03T00:00:00+00:00"),
        _row(eid="3b", run_id="new", claim="same", at="2026-01-03T01:00:00+00:00"),
        _row(eid="4", run_id="new", claim="other", at="2026-01-04T00:00:00+00:00"),
    ]
    lines, cap = recent_evidence_lines_for_report(ev, latest_run_id="new", max_lines=25)
    assert "Latest ingest run" in cap
    blob = "\n".join(lines)
    mul = "\u00d7"  # ×
    assert f"{mul}3" in blob
    assert "other" in blob


def test_dedupe_evidence_for_scoring_keeps_newest_per_hash() -> None:
    h = "abc123"
    ev = [
        _row(eid="1", run_id="r", at="2026-01-01T00:00:00+00:00", dh=h),
        _row(eid="2", run_id="r", at="2026-01-02T00:00:00+00:00", dh=h),
    ]
    out = dedupe_evidence_for_scoring(ev)
    assert len(out) == 1
    assert out[0].evidence_id == "2"


def test_suppress_dev_docs_absence_keeps_rows_when_no_portal_signal() -> None:
    ev = [_row(eid="a", run_id="r", et="absence_signal", claim="no api docs", tags="developer_docs")]
    out = suppress_developer_docs_absence_when_dev_portal_present(ev)
    assert len(out) == 1 and out[0].evidence_id == "a"


def test_suppress_dev_docs_absence_drops_tagged_rows_when_portal_present() -> None:
    ev = [
        _row(eid="p", run_id="r", et="dev_portal_signal", claim="docs linked"),
        _row(eid="a", run_id="r", et="absence_signal", claim="no docs", tags="developer_docs"),
    ]
    out = suppress_developer_docs_absence_when_dev_portal_present(ev)
    assert [e.evidence_id for e in out] == ["p"]


def test_suppress_dev_docs_absence_keeps_other_absence_when_portal_present() -> None:
    ev = [
        _row(eid="p", run_id="r", et="dev_portal_signal", claim="portal"),
        _row(eid="a", run_id="r", et="absence_signal", claim="other gap", tags="pricing_page"),
    ]
    out = suppress_developer_docs_absence_when_dev_portal_present(ev)
    assert {e.evidence_id for e in out} == {"p", "a"}
