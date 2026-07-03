"""Manual evidence intake: URL normalization, operator guidance, promotion to ``EvidenceRecord``."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urldefrag, urlparse

from invendx import PARSER_VERSION
from invendx.models.evidence import EvidenceRecord
from invendx.models.vendor import VendorRecord
from invendx.pipeline.evidence_fingerprint import assign_dedupe_hashes
from invendx.pipeline.vendor_summary import refresh_vendor_summary
from invendx.storage import evidence_repo, manual_intake_repo, vendor_repo

logger = logging.getLogger(__name__)

INTAKE_STATUS_PENDING = "pending"
INTAKE_STATUS_CAPTURED = "captured"
INTAKE_STATUS_INGESTED = "ingested"
INTAKE_STATUS_DISCARDED = "discarded"

REASON_FLAGS = [
    "robots_blocked",
    "non_html",
    "fetch_failed",
    "http_error",
    "pdf_target",
    "js_heavy_suspected",
    "low_signal_coverage",
    "operator_escalation",
    "discovered_target",
    "other",
]

SOURCE_TYPES = ["target_official", "target_third_party", "unknown"]

CRAWL_REASON_TO_INTAKE_REASON: dict[str, str] = {
    "robots_denied": "robots_blocked",
    "http_not_ok": "http_error",
    "non_html_skipped": "non_html",
    "fetch_failed": "fetch_failed",
}


def intake_reason_for_crawl_skip(crawl_reason: str) -> str:
    return CRAWL_REASON_TO_INTAKE_REASON.get(crawl_reason, "other")


def parse_crawl_skipped_urls_from_run_notes(notes: str | None) -> list[dict]:
    if not (notes or "").strip():
        return []
    try:
        data = json.loads(notes)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("crawl_skipped_urls") or []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for x in raw:
        if isinstance(x, dict) and x.get("url"):
            out.append(x)
    return out


def queue_crawl_skipped_urls_for_vendor(
    conn: sqlite3.Connection,
    vendor_id: str,
    skipped: list[dict],
    *,
    skip_if_already_queued: bool = True,
) -> int:
    """Insert manual intake rows for crawl skip samples (dedupe by URL when requested)."""
    n = 0
    for item in skipped:
        url = normalize_source_url(str(item.get("url") or ""))
        if not url:
            continue
        cr = str(item.get("crawl_reason") or "")
        reason = intake_reason_for_crawl_skip(cr)
        ik = default_instructions_key(reason)
        added = manual_intake_repo.insert_intake(
            conn,
            vendor_id=vendor_id,
            source_url=url,
            source_type="target_official",
            reason_flagged=reason,
            instructions_key=ik,
            skip_if_url_exists=skip_if_already_queued,
        )
        if added:
            n += 1
    return n


def discard_duplicate_active_intakes_by_url(conn: sqlite3.Connection, vendor_id: str) -> int:
    """Mark discarded all but one pending/captured row per normalized ``source_url``.

    Keeps the **best** row: **captured** before **pending**; then latest ``captured_at``,
    then latest ``created_at``. Does not change **ingested** rows.
    """
    rows = manual_intake_repo.list_intakes_for_vendor(
        conn, vendor_id, include_ingested=False, include_discarded=False
    )
    by_url: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        u = normalize_source_url(r["source_url"] or "")
        key = u if u else (r["source_url"] or "")
        by_url[key].append(r)
    discarded = 0
    for _url_key, group in by_url.items():
        if len(group) < 2:
            continue

        def sort_key(row: dict) -> tuple:
            status_rank = 2 if row["status"] == "captured" else 1
            cap = str(row.get("captured_at") or "")
            cre = str(row.get("created_at") or "")
            return (status_rank, cap, cre)

        group_sorted = sorted(group, key=sort_key, reverse=True)
        for row in group_sorted[1:]:
            if manual_intake_repo.mark_discarded(conn, row["intake_id"]):
                discarded += 1
    return discarded


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_source_url(url: str) -> str:
    u = " ".join((url or "").strip().split())
    if not u:
        return ""
    with_defrag, _frag = urldefrag(u)
    return with_defrag


def default_instructions_key(reason_flagged: str) -> str:
    if reason_flagged in GUIDANCE_MARKDOWN:
        return reason_flagged
    return "general"


GUIDANCE_MARKDOWN: dict[str, str] = {
    "general": (
        "**What to capture from the source**\n\n"
        "- Product/platform scope and positioning; concrete capabilities (not taglines alone).\n"
        "- Developer or API documentation, integration surfaces, and partner/ecosystem claims.\n"
        "- Security, compliance, or certification language when material.\n"
        "- Scale signals (customers, volumes, geographies) **only** if explicitly stated.\n\n"
        "**Avoid:** footers, legal/cookie boilerplate, pure navigation, duplicate menus, and "
        "generic marketing copy with no factual claims."
    ),
    "robots_blocked": (
        "Automated crawl is not allowed for this URL under the current robots policy. "
        "**Capture** the same substantive content an analyst would need from a normal page view: "
        "platform scope, APIs/docs hints, integrations/partners, and factual scale or compliance "
        "claims. **Omit** chrome and boilerplate."
    ),
    "non_html": (
        "This target is not treated as HTML in the crawler (e.g. PDF or other content-type). "
        "**Paste** the key readable text you can access out-of-band. Prefer structured sections "
        "(overview, integrations, security) over entire documents if very long."
    ),
    "pdf_target": (
        "Likely or known PDF. **Capture** headings and paragraphs that state capabilities, "
        "integrations, APIs, partners, compliance, or measurable scale. Skip cover pages and "
        "repeated legal blocks."
    ),
    "fetch_failed": (
        "Fetch failed during automation. **Paste** what you can load manually; note any "
        "**limitations** in operator notes if the page is partial or login-gated."
    ),
    "http_error": (
        "HTTP error during automation. If you can still see content (or an archived view), "
        "**paste** factual claims only; avoid error-page chrome."
    ),
    "js_heavy_suspected": (
        "Page may rely heavily on client-side rendering. **Paste** substantive text after the "
        "app has loaded (not loading spinners or empty shells)."
    ),
    "low_signal_coverage": (
        "Automation produced little usable evidence for this vendor/URL. **Capture** missing "
        "signals: product depth, developer surfaces, integrations, partners, compliance."
    ),
    "operator_escalation": (
        "Manually queued by operator. **Capture** content aligned to research goals; use notes "
        "to explain context."
    ),
    "discovered_target": (
        "URL came from discovery preview. **Capture** the same signals as a crawl would: "
        "platform, docs/APIs, integrations, partners, compliance, stated scale."
    ),
    "other": (
        "See **general** guidance: factual product, technical, and partnership content; "
        "exclude boilerplate and pure marketing filler."
    ),
}


def guidance_for_key(instructions_key: str) -> str:
    return GUIDANCE_MARKDOWN.get(instructions_key, GUIDANCE_MARKDOWN["general"])


def _claim_from_capture(text: str, max_len: int = 200) -> str:
    t = " ".join((text or "").strip().split())
    if not t:
        return "Manual capture (empty body)"
    if len(t) <= max_len:
        return f"Manual capture: {t}"
    return f"Manual capture: {t[: max_len - 3]}..."


def _title_from_url(source_url: str) -> str:
    p = urlparse(source_url or "")
    host = p.netloc or "source"
    path = (p.path or "").strip("/")
    bit = f"{host}/{path}" if path else host
    return f"Manual capture — {bit[:120]}"


def manual_capture_to_evidence(
    *,
    intake_row: dict,
    vendor: VendorRecord,
    run_id: str,
    collected_at: str | None = None,
) -> EvidenceRecord:
    body = (intake_row.get("captured_text") or "").strip()
    src_url = intake_row["source_url"]
    rid = intake_row.get("reason_flagged") or "other"
    iid = intake_row["intake_id"]
    cap_at = intake_row.get("captured_at") or ""
    tags_parts = ["manual", f"reason:{rid}", f"intake_id:{iid}"]
    if cap_at:
        tags_parts.append(f"captured_at:{cap_at}")
    return EvidenceRecord(
        evidence_id=str(uuid.uuid4()),
        vendor_id=vendor.vendor_id,
        vendor_name=vendor.canonical_name,
        run_id=run_id,
        source_type="manual",
        source_url=src_url,
        source_title=_title_from_url(src_url),
        evidence_type="manual_capture",
        claim_text=_claim_from_capture(body),
        confidence="high",
        tags=",".join(tags_parts),
        raw_text_excerpt=body if body else None,
        parser_version=PARSER_VERSION,
        collected_at=collected_at or _now(),
    )


def promote_intake_to_evidence(
    conn: sqlite3.Connection, intake_id: str
) -> tuple[str | None, list[str] | None, str | None]:
    """Create a manual ingest run and one ``manual_capture`` evidence row. Returns (run_id, evidence_ids, error)."""
    row = manual_intake_repo.get_intake(conn, intake_id)
    if not row:
        return None, None, "intake not found"
    if row["status"] == INTAKE_STATUS_INGESTED:
        return None, None, "already ingested"
    if row["status"] == INTAKE_STATUS_DISCARDED:
        return None, None, "discarded intake"
    if row["status"] not in (INTAKE_STATUS_PENDING, INTAKE_STATUS_CAPTURED):
        return None, None, f"invalid status: {row['status']}"
    body = (row.get("captured_text") or "").strip()
    if not body:
        return None, None, "no captured text; save capture first"

    vendor = vendor_repo.get_vendor_by_id(conn, row["vendor_id"])
    run_id = str(uuid.uuid4())
    rec = manual_capture_to_evidence(intake_row=row, vendor=vendor, run_id=run_id)
    hashed = assign_dedupe_hashes([rec])[0]
    h = hashed.dedupe_hash or ""
    if h and evidence_repo.vendor_has_dedupe_hash(conn, vendor.vendor_id, h):
        return None, None, "duplicate content fingerprint already stored for this vendor"

    notes = json.dumps({"manual_intake": True, "intake_id": intake_id})
    evidence_repo.insert_run(conn, run_id, vendor.vendor_id, PARSER_VERSION, notes=notes)

    evidence_repo.insert_evidence(conn, [hashed])
    eid = hashed.evidence_id
    manual_intake_repo.mark_promoted(conn, intake_id, promoted_run_id=run_id, evidence_ids=[eid])
    refresh_vendor_summary(conn, vendor.vendor_id)
    logger.info("promoted manual intake %s -> run %s evidence %s", intake_id, run_id, eid)
    return run_id, [eid], None
