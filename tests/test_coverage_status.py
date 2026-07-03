from __future__ import annotations

from invendx.pipeline.coverage_status import CoverageThresholds, classify_coverage


def _row(**kwargs):
    base = {
        "ingest_run_count": 0,
        "evidence_count": 0,
        "distinct_source_url_count": 0,
        "latest_score_run_present": False,
        "latest_score_line_item_count": 0,
        "profile_metrics_present": False,
    }
    base.update(kwargs)
    return base


def test_not_synced_only() -> None:
    t = CoverageThresholds(min_evidence_rows=8, min_distinct_urls=3)
    st, notes = classify_coverage(_row(ingest_run_count=0, evidence_count=0), t)
    assert st == "NOT_SYNCED_ONLY"
    assert "ingest runs" in notes.lower() or "yaml" in notes.lower()


def test_ingested_no_evidence() -> None:
    t = CoverageThresholds(8, 3)
    st, notes = classify_coverage(_row(ingest_run_count=1, evidence_count=0), t)
    assert st == "INGESTED_NO_EVIDENCE"
    assert "no evidence" in notes.lower()


def test_low_coverage() -> None:
    t = CoverageThresholds(8, 3)
    st, _ = classify_coverage(_row(ingest_run_count=1, evidence_count=3, distinct_source_url_count=3), t)
    assert st == "LOW_COVERAGE"


def test_coverage_ok_not_scored() -> None:
    t = CoverageThresholds(8, 3)
    st, notes = classify_coverage(
        _row(
            ingest_run_count=1,
            evidence_count=8,
            distinct_source_url_count=3,
            latest_score_run_present=False,
            profile_metrics_present=True,
        ),
        t,
    )
    assert st == "COVERAGE_OK_NOT_SCORED"
    assert notes == ""


def test_coverage_ok_scored() -> None:
    t = CoverageThresholds(8, 3)
    st, notes = classify_coverage(
        _row(
            ingest_run_count=1,
            evidence_count=8,
            distinct_source_url_count=3,
            latest_score_run_present=True,
            latest_score_line_item_count=2,
        ),
        t,
    )
    assert st == "COVERAGE_OK_SCORED"
    assert "0 line items" not in notes


def test_scored_zero_line_items_note() -> None:
    t = CoverageThresholds(8, 3)
    st, notes = classify_coverage(
        _row(
            ingest_run_count=1,
            evidence_count=8,
            distinct_source_url_count=3,
            latest_score_run_present=True,
            latest_score_line_item_count=0,
        ),
        t,
    )
    assert st == "COVERAGE_OK_SCORED"
    assert "0 line items" in notes


def test_profile_hints_absent_note_when_ok() -> None:
    t = CoverageThresholds(8, 3)
    st, notes = classify_coverage(
        _row(
            ingest_run_count=1,
            evidence_count=8,
            distinct_source_url_count=3,
            latest_score_run_present=False,
            profile_metrics_present=False,
        ),
        t,
    )
    assert st == "COVERAGE_OK_NOT_SCORED"
    assert "profile hints absent" in notes.lower()
