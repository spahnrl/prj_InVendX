"""Read-side transforms: collapsed views for reporting and scoring."""

from __future__ import annotations

from collections import OrderedDict, defaultdict

from invendx.models.evidence import EvidenceRecord
from invendx.pipeline.press_parser import title_looks_like_obvious_soft_error

_RECENT_BUCKET_ORDER = [
    "Developer",
    "Integration",
    "Site and content",
    "Engineering and careers",
    "News and press",
    "Manual capture",
    "Other",
]


def _recent_evidence_bucket(evidence_type: str) -> str:
    et = evidence_type or ""
    if et in ("dev_portal_signal", "repo_metadata", "absence_signal"):
        return "Developer"
    if et == "integration":
        return "Integration"
    if et in ("keyword_signal", "page_crawl"):
        return "Site and content"
    if et in ("hiring_signal", "job_signal"):
        return "Engineering and careers"
    if et == "press_parser":
        return "News and press"
    if et == "manual_capture":
        return "Manual capture"
    return "Other"


def _excerpt_one_line(ex: str | None, max_len: int = 100) -> str:
    if not ex or not str(ex).strip():
        return ""
    t = " ".join(str(ex).split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _excerpt_for_report(e: EvidenceRecord, *, max_len: int = 280) -> str:
    """Longer excerpt than legacy one-liner; drop when it mostly duplicates title or claim."""
    raw = (e.raw_text_excerpt or "").strip()
    if not raw:
        return ""
    t = " ".join(raw.split())
    title = (e.source_title or "").strip().lower()
    tlow = t.lower()
    claim = (e.claim_text or "").strip()
    claim_low = claim.lower()
    if title and len(title) > 12 and len(tlow) >= 20 and tlow[: min(len(tlow), len(title) + 5)].startswith(title[: min(len(title), 60)]):
        return ""
    cprev = claim_low[:72] if claim_low else ""
    if cprev and len(tlow) >= 30 and tlow[: min(len(tlow), len(cprev) + 10)].startswith(cprev[: min(len(cprev), 72)]):
        return ""
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _collapse_key_for_report(e: EvidenceRecord) -> tuple:
    """Merge many pages that repeat the same developer-portal claim into one narrative bullet."""
    if e.evidence_type == "dev_portal_signal":
        return ("dev_portal_signal", (e.claim_text or "").strip())
    return collapse_evidence_key(e)


def _format_recent_evidence_bullet(
    e: EvidenceRecord,
    n: int,
    *,
    distinct_sources: int | None = None,
) -> str:
    suffix = f" (×{n})" if n > 1 else ""
    claim = e.claim_text[:200] + ("…" if len(e.claim_text) > 200 else "")
    parts: list[str] = []
    title = (e.source_title or "").strip()
    if title:
        parts.append(f"**{title}** — ")
    parts.append(f"`{e.evidence_type}` — {claim}")
    ex = _excerpt_for_report(e)
    if ex:
        parts.append(f" — _{ex}_")
    conf = (e.confidence or "").strip()
    if conf:
        parts.append(f" _(confidence: {conf})_")
    ds = distinct_sources if distinct_sources is not None else 1
    if e.evidence_type == "dev_portal_signal" and ds > 1:
        parts.append(
            f" — _**{ds}** distinct pages share this claim; link is one representative; "
            f"see **Distinct source URLs** for every URL._ ([source]({e.source_url}))"
        )
    else:
        parts.append(f"{suffix} ([source]({e.source_url}))")
    return "- " + "".join(parts)


def _title_for_legacy_junk_filter(e: EvidenceRecord) -> str:
    """Best-effort title for strict soft-error filtering (historical rows may lack source_title)."""
    if (e.source_title or "").strip():
        return (e.source_title or "").strip()
    if e.evidence_type == "page_crawl" and e.claim_text.startswith("Crawled page: "):
        return e.claim_text[len("Crawled page: ") :].strip()
    return ""


def _is_legacy_junk_evidence_row(e: EvidenceRecord) -> bool:
    t = _title_for_legacy_junk_filter(e)
    if not t:
        return False
    return title_looks_like_obvious_soft_error(t)


def collapse_evidence_key(e: EvidenceRecord) -> tuple[str, str, str]:
    return (e.evidence_type, e.source_url, e.claim_text)


def recent_evidence_lines_for_report(
    ev: list[EvidenceRecord],
    *,
    latest_run_id: str | None,
    max_lines: int = 25,
    grouped: bool = True,
) -> tuple[list[str], str]:
    """Build markdown lines and a caption for ## Recent evidence.

    Prefers evidence from ``latest_run_id``; if that slice is empty, falls back to all vendor
    evidence minus strict title-based legacy junk rows. Collapses identical (type, source_url,
    claim_text), newest first, with ×N when N>1.

    When ``grouped`` is True, emits ``###`` section headings by coarse bucket (Developer,
    Integration, …) then bullets with optional page title, excerpt, and confidence.
    """
    if latest_run_id:
        sub = [e for e in ev if e.run_id == latest_run_id]
        if sub:
            caption = (
                f"Latest ingest run (`{latest_run_id[:8]}…`); repeated rows folded (same page: ×N; "
                "same developer-portal **claim** across many URLs: one bullet with a page count)."
            )
            pool = sub
        else:
            caption = (
                "Latest run has no stored evidence rows (e.g. all deduped); "
                f"showing collapsed view across all runs (`{latest_run_id[:8]}…` was last run id). "
                "Repeated developer-portal claims on many URLs are folded into one line per claim."
            )
            pool = [e for e in ev if not _is_legacy_junk_evidence_row(e)]
    else:
        caption = "No ingest runs; collapsed view of stored evidence."
        pool = ev

    pool_sorted = sorted(pool, key=lambda e: e.collected_at, reverse=True)
    groups: OrderedDict[tuple, dict[str, object]] = OrderedDict()
    for e in pool_sorted:
        key = _collapse_key_for_report(e)
        if key in groups:
            g = groups[key]
            rec = g["rec"]
            assert isinstance(rec, EvidenceRecord)
            n = int(g["n"]) + 1
            urls = g["urls"]
            assert isinstance(urls, set)
            urls.add(e.source_url)
            if e.collected_at > rec.collected_at:
                rec = e
            g["rec"] = rec
            g["n"] = n
        else:
            groups[key] = {"rec": e, "n": 1, "urls": {e.source_url}}

    flat_bullets: list[str] = []
    bucket_to_bullets: dict[str, list[str]] = defaultdict(list)
    for i, (_key, g) in enumerate(groups.items()):
        if i >= max_lines:
            break
        rec = g["rec"]
        assert isinstance(rec, EvidenceRecord)
        n = int(g["n"])
        urls = g["urls"]
        assert isinstance(urls, set)
        bullet = _format_recent_evidence_bullet(
            rec,
            n,
            distinct_sources=len(urls),
        )
        flat_bullets.append(bullet)
        bucket_to_bullets[_recent_evidence_bucket(rec.evidence_type)].append(bullet)

    lines: list[str]
    if grouped and bucket_to_bullets:
        lines = []
        placed: set[str] = set()
        for bucket in _RECENT_BUCKET_ORDER:
            bl = bucket_to_bullets.get(bucket)
            if not bl:
                continue
            lines.append(f"### {bucket}")
            lines.append("")
            lines.extend(bl)
            placed.add(bucket)
        for bucket in sorted(bucket_to_bullets):
            if bucket in placed:
                continue
            lines.append(f"### {bucket}")
            lines.append("")
            lines.extend(bucket_to_bullets[bucket])
    else:
        lines = flat_bullets

    return lines, caption


def dedupe_evidence_for_scoring(evidence: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """One row per dedupe_hash (or per type/url/claim if hash missing); keep newest by collected_at."""
    by_key: dict[str, EvidenceRecord] = {}
    for e in sorted(evidence, key=lambda x: x.collected_at, reverse=True):
        key = e.dedupe_hash if e.dedupe_hash else "|".join(collapse_evidence_key(e))
        if key not in by_key:
            by_key[key] = e
    return sorted(by_key.values(), key=lambda x: x.collected_at)


def suppress_developer_docs_absence_when_dev_portal_present(
    evidence: list[EvidenceRecord],
) -> list[EvidenceRecord]:
    """Drop ``absence_signal`` tagged ``developer_docs`` when any ``dev_portal_signal`` is present.

    Same scoring scope as the surrounding list (e.g. one ingest run or all vendor evidence).
    Avoids scoring both ``dev_portal_link`` and ``dev_docs_absence`` on contradictory hints.
    """
    if not any(e.evidence_type == "dev_portal_signal" for e in evidence):
        return evidence
    tags_needle = "developer_docs"
    return [
        e
        for e in evidence
        if not (
            e.evidence_type == "absence_signal"
            and tags_needle in (e.tags or "").lower()
        )
    ]
