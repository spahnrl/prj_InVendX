"""Rule-based coverage_status labels for vendor diagnostic rows (unit-testable)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class CoverageThresholds:
    min_evidence_rows: int = 8
    min_distinct_urls: int = 3


DEFAULT_THRESHOLDS = CoverageThresholds()


def classify_coverage(row: Mapping, thresholds: CoverageThresholds) -> tuple[str, str]:
    """Return (coverage_status, coverage_notes) using plan precedence."""
    ingest = int(row.get("ingest_run_count") or 0)
    ev = int(row.get("evidence_count") or 0)
    urls = int(row.get("distinct_source_url_count") or 0)
    has_score = bool(row.get("latest_score_run_present"))
    line_items = int(row.get("latest_score_line_item_count") or 0)
    prof = bool(row.get("profile_metrics_present"))

    notes_parts: list[str] = []

    ok = ev >= thresholds.min_evidence_rows and urls >= thresholds.min_distinct_urls

    if ingest == 0:
        status = "NOT_SYNCED_ONLY"
        notes_parts.append("No ingest runs in database; vendor may only be synced from YAML.")
    elif ev == 0:
        status = "INGESTED_NO_EVIDENCE"
        notes_parts.append("Ingest ran but no evidence rows stored (crawl/parser/site may yield nothing).")
    elif not ok:
        status = "LOW_COVERAGE"
        notes_parts.append(
            f"Below bar: need >= {thresholds.min_evidence_rows} evidence rows and "
            f">= {thresholds.min_distinct_urls} distinct source URLs."
        )
    elif not has_score:
        status = "COVERAGE_OK_NOT_SCORED"
    else:
        status = "COVERAGE_OK_SCORED"
        if line_items == 0:
            notes_parts.append("Score run has 0 line items (rules miss or evidence tags).")

    if ok and not prof:
        notes_parts.append("Profile hints absent (regex may not match site copy); evidence may still be adequate.")

    return status, "; ".join(notes_parts)
