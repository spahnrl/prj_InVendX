from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from invendx.extract.patterns import match_architecture_keywords
from invendx.extract.text import extract_meta, html_to_text
from invendx.http.client import HttpClient
from invendx.http.robots import RobotsPolicy
from invendx.models.discovery import DiscoveredTarget
from invendx.models.evidence import EvidenceRecord
from invendx.models.vendor import VendorRecord

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_careers_target(t: DiscoveredTarget) -> bool:
    k = t.kind.lower()
    return "career" in k or "job" in k or k.startswith("seed:career") or "seed:jobs" in k


def collect_job_signals(
    vendor: VendorRecord,
    targets: list[DiscoveredTarget],
    http: HttpClient,
    robots: RobotsPolicy,
    run_id: str,
    parser_version: str,
) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    for t in targets:
        if not _is_careers_target(t):
            continue
        if not robots.allowed(t.url):
            continue
        try:
            res = http.fetch(t.url)
        except Exception as e:  # noqa: BLE001
            logger.debug("careers fetch %s: %s", t.url, e)
            continue
        if not res.ok or "html" not in res.content_type.lower():
            continue
        meta = extract_meta(res.text)
        title = meta.get("title") or t.url
        text = html_to_text(res.text)
        kw = match_architecture_keywords(text)
        tags = ["careers", "hiring"]
        tags.extend(kw[:10])
        records.append(
            EvidenceRecord(
                evidence_id=str(uuid.uuid4()),
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.canonical_name,
                run_id=run_id,
                source_type="careers_page",
                source_url=res.final_url,
                source_date=None,
                source_title=title,
                evidence_type="hiring_signal",
                claim_text="Careers page text scanned for platform / integration keywords.",
                confidence="medium" if kw else "low",
                tags=",".join(dict.fromkeys(tags)),
                score_impact_category="EngineeringSignal",
                raw_text_excerpt=" ".join(text.split())[:500],
                parser_version=parser_version,
                collected_at=_now(),
            )
        )
    return records
