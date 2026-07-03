from __future__ import annotations

import uuid
from datetime import datetime, timezone
from urllib.parse import urljoin

from invendx.extract.patterns import (
    find_doc_hints_in_links,
    match_architecture_keywords,
    text_suggests_integration,
)
from invendx.extract.text import extract_meta, html_to_text, parse_date_loose
from invendx.models.discovery import PageDocument
from invendx.models.evidence import EvidenceRecord
from invendx.models.vendor import VendorRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _excerpt(text: str, max_len: int = 600) -> str:
    t = " ".join(text.split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def title_looks_like_obvious_soft_error(title: str) -> bool:
    """Strict title-only soft-error heuristic (shared with report fallback for legacy rows)."""
    t = " ".join((title or "").lower().split())
    if not t:
        return False
    if "404" in t:
        return True
    if "not found" in t:
        return True
    if "could not be found" in t:
        return True
    if "cannot be found" in t:
        return True
    if "can't be found" in t:
        return True
    return False


def _is_obvious_soft_error_page(page: PageDocument, title: str) -> bool:
    """True for hard HTTP errors or soft 404 / obvious error titles (title and status only)."""
    if page.status_code >= 400:
        return True
    return title_looks_like_obvious_soft_error(title)


def parse_pages_to_evidence(
    pages: list[PageDocument],
    vendor: VendorRecord,
    run_id: str,
    parser_version: str,
) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    for page in pages:
        if not page.html:
            continue
        meta = extract_meta(page.html)
        title = meta.get("title") or page.final_url
        if _is_obvious_soft_error_page(page, title):
            continue
        text = html_to_text(page.html)
        source_date = parse_date_loose(meta.get("published_hint"))

        # Page-level capture
        records.append(
            EvidenceRecord(
                evidence_id=str(uuid.uuid4()),
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.canonical_name,
                run_id=run_id,
                source_type="official_site",
                source_url=page.final_url,
                source_date=source_date,
                source_title=title,
                evidence_type="page_crawl",
                claim_text=f"Crawled page: {title}",
                confidence="high",
                tags="crawl",
                raw_text_excerpt=_excerpt(text),
                parser_version=parser_version,
                collected_at=_now(),
            )
        )

        kw = match_architecture_keywords(text)
        if kw:
            records.append(
                EvidenceRecord(
                    evidence_id=str(uuid.uuid4()),
                    vendor_id=vendor.vendor_id,
                    vendor_name=vendor.canonical_name,
                    run_id=run_id,
                    source_type="official_site",
                    source_url=page.final_url,
                    source_date=source_date,
                    source_title=title,
                    evidence_type="keyword_signal",
                    product_area="platform",
                    claim_text="Architecture/integration keywords present: " + ", ".join(kw),
                    confidence="medium",
                    tags=",".join(kw),
                    score_impact_category="TradingDataDepth",
                    raw_text_excerpt=_excerpt(text, 400),
                    parser_version=parser_version,
                    collected_at=_now(),
                )
            )

        if text_suggests_integration(text):
            records.append(
                EvidenceRecord(
                    evidence_id=str(uuid.uuid4()),
                    vendor_id=vendor.vendor_id,
                    vendor_name=vendor.canonical_name,
                    run_id=run_id,
                    source_type="official_site",
                    source_url=page.final_url,
                    source_date=source_date,
                    source_title=title,
                    evidence_type="integration",
                    claim_text="Page language suggests integrations, partnerships, or real-time workflows.",
                    confidence="medium",
                    tags="integration,language",
                    score_impact_category="IntegrationCapability",
                    raw_text_excerpt=_excerpt(text, 400),
                    parser_version=parser_version,
                    collected_at=_now(),
                )
            )

        # Developer doc path presence on this page's links
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(page.html, "lxml")
        links = [a["href"] for a in soup.find_all("a", href=True)]
        abs_links = [urljoin(page.final_url, h) for h in links]
        doc_hits = find_doc_hints_in_links(list(dict.fromkeys([page.final_url] + abs_links)))
        for hit in doc_hits[:5]:
            records.append(
                EvidenceRecord(
                    evidence_id=str(uuid.uuid4()),
                    vendor_id=vendor.vendor_id,
                    vendor_name=vendor.canonical_name,
                    run_id=run_id,
                    source_type="official_site",
                    source_url=page.final_url,
                    source_date=source_date,
                    source_title=title,
                    evidence_type="dev_portal_signal",
                    claim_text=f"Link to developer/docs area discovered: {hit}",
                    confidence="high",
                    tags="docs,link",
                    score_impact_category="DeveloperExperience",
                    raw_text_excerpt=hit,
                    parser_version=parser_version,
                    collected_at=_now(),
                )
            )

    return records


def dev_docs_absence_evidence(
    vendor: VendorRecord,
    run_id: str,
    crawled_urls: list[str],
    parser_version: str,
) -> EvidenceRecord | None:
    """Emit absence signal if no crawled URL hints at developer documentation."""
    hints = ("developer", "docs", "documentation", "/api", "openapi", "swagger")
    joined = "\n".join(crawled_urls).lower()
    if any(h in joined for h in hints):
        return None
    return EvidenceRecord(
        evidence_id=str(uuid.uuid4()),
        vendor_id=vendor.vendor_id,
        vendor_name=vendor.canonical_name,
        run_id=run_id,
        source_type="official_site",
        source_url=f"https://{vendor.primary_domain}/",
        source_date=None,
        source_title=None,
        evidence_type="absence_signal",
        claim_text="No developer/docs/API URLs detected in bounded crawl (absence is a signal).",
        confidence="low",
        tags="absence,developer_docs",
        score_impact_category="DeveloperExperience",
        raw_text_excerpt="",
        parser_version=parser_version,
        collected_at=_now(),
    )
