"""Acquisition diagnostic: mirror crawler/parser gates per URL (standalone).

Compare fetch, robots, content-type, PageDocument eligibility, and optional parse
outcomes. Use --allowed-netloc to match SiteCrawler's first-seed host (e.g. crd.com
vs www.crd.com).

Run from repo root with the package on PYTHONPATH (e.g. ``pip install -e .``):

  python scripts/acquire_probe.py --allowed-netloc crd.com \\
    https://www.crd.com/solutions/charles-river-ims/ \\
    https://www.crd.com/company/partners/ \\
    https://info.crd.com/Partners-Interfaces

  python scripts/acquire_probe.py --allowed-netloc addepar.com --parse \\
    https://www.addepar.com/platform/
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from invendx.http.client import DEFAULT_UA, HttpClient
from invendx.http.robots import RobotsPolicy
from invendx.models.discovery import PageDocument
from invendx.models.vendor import VendorRecord
from invendx.pipeline.press_parser import parse_pages_to_evidence, title_looks_like_obvious_soft_error
from invendx.extract.text import extract_meta


@dataclass
class ProbeResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    content_length_bytes: int
    robots_allowed: bool
    fetch_ok: bool
    fetch_error: str | None
    body_non_empty: bool
    content_kind: str
    would_page_document: bool
    netloc_matches_allowed_seed_host: bool
    allowed_seed_netloc: str
    response_netloc: str
    soft_error_title_would_skip_parser: bool
    parse_record_count: int | None
    parse_evidence_types: list[str] | None
    pipeline_classification: str
    dedupe_risk: bool
    notes: str


def _content_kind(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "html" in ct:
        return "html"
    if "pdf" in ct:
        return "pdf"
    return "other"


def _classify(
    *,
    robots_allowed: bool,
    fetch_ok: bool,
    fetch_error: str | None,
    would_page_document: bool,
    soft_error_skip: bool,
    parse_count: int | None,
    parse_types: list[str] | None,
) -> tuple[str, bool, str]:
    """Return (pipeline_classification, dedupe_risk, notes)."""
    if not robots_allowed:
        return "blocked", False, "robots.txt disallows this URL for DEFAULT_UA"
    if fetch_error:
        return "blocked", False, f"fetch exception: {fetch_error}"
    if not fetch_ok:
        return "blocked", False, "HTTP status not ok (crawler would not build PageDocument)"

    if not would_page_document:
        return "fetched_but_dropped", False, "crawler requires ok response and content-type hinting html"

    if soft_error_skip:
        return "fetched_but_dropped", False, "would be PageDocument but parser skips (soft error title)"

    if parse_count is None:
        # Crawler would keep; parser not run
        return "kept_as_page_document", True, "PageDocument would be created; use --parse for parser breakdown"

    if parse_count == 0:
        return "fetched_but_dropped", False, "parser produced no rows (unexpected if html present)"

    thin = parse_types == ["page_crawl"] and parse_count == 1
    if thin:
        return "parsed_thinly", True, "only page_crawl row(s); no keyword/integration/dev_portal signals"

    return "kept_as_page_document", True, "parser emitted multiple evidence types or non-thin signals"


def probe_url(
    url: str,
    *,
    allowed_seed_netloc: str,
    http: HttpClient,
    robots: RobotsPolicy,
    do_parse: bool,
) -> ProbeResult:
    robots_allowed = robots.allowed(url)
    fetch_error: str | None = None
    res = None
    if robots_allowed:
        try:
            res = http.fetch(url)
        except Exception as e:  # noqa: BLE001
            fetch_error = f"{type(e).__name__}: {e}"

    if res is None:
        ok = False
        final_url = url
        status = 0
        ct = ""
        text = ""
    else:
        ok = res.ok
        final_url = res.final_url
        status = res.status_code
        ct = res.content_type
        text = res.text or ""

    body_non_empty = bool(text.strip())
    length = len(text.encode("utf-8", errors="replace")) if text else 0
    kind = _content_kind(ct)
    would_page = ok and ("html" in ct.lower())

    resp_host = (urlparse(final_url).netloc or "").lower()
    allowed_norm = allowed_seed_netloc.lower()
    netloc_match = bool(resp_host) and resp_host == allowed_norm

    soft_skip = False
    parse_count: int | None = None
    parse_types: list[str] | None = None

    if would_page and text:
        meta = extract_meta(text)
        title = meta.get("title") or final_url
        soft_skip = title_looks_like_obvious_soft_error(title)

        if do_parse and not soft_skip:
            stub = VendorRecord(
                vendor_id="probe",
                canonical_name="ProbeCo",
                primary_domain="probe.local",
                primary_segment="",
            )
            page = PageDocument(
                url=url,
                final_url=final_url,
                status_code=status,
                content_type=ct,
                html=text,
                fetched_at="1970-01-01T00:00:00+00:00",
            )
            recs = parse_pages_to_evidence([page], stub, "probe-run", "0.0.0")
            parse_count = len(recs)
            parse_types = sorted({r.evidence_type for r in recs})

    pipeline_class, dedupe_risk, notes = _classify(
        robots_allowed=robots_allowed,
        fetch_ok=ok,
        fetch_error=fetch_error,
        would_page_document=would_page,
        soft_error_skip=soft_skip,
        parse_count=parse_count,
        parse_types=parse_types,
    )

    return ProbeResult(
        requested_url=url,
        final_url=final_url,
        status_code=status,
        content_type=ct,
        content_length_bytes=length,
        robots_allowed=robots_allowed,
        fetch_ok=ok,
        fetch_error=fetch_error,
        body_non_empty=body_non_empty,
        content_kind=kind,
        would_page_document=would_page,
        netloc_matches_allowed_seed_host=netloc_match,
        allowed_seed_netloc=allowed_norm,
        response_netloc=resp_host,
        soft_error_title_would_skip_parser=soft_skip,
        parse_record_count=parse_count,
        parse_evidence_types=parse_types,
        pipeline_classification=pipeline_class,
        dedupe_risk=dedupe_risk,
        notes=notes,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Acquisition / fetch diagnostic for InVendX crawl mirrors.")
    p.add_argument(
        "urls",
        nargs="+",
        help="URLs to probe (order irrelevant unless --allowed-netloc omitted)",
    )
    p.add_argument(
        "--allowed-netloc",
        dest="allowed_netloc",
        default=None,
        help=(
            "Netloc of SiteCrawler seed[0] (e.g. crd.com for Charles River homepage). "
            "Default: netloc of the first URL argument."
        ),
    )
    p.add_argument(
        "--parse",
        action="store_true",
        help="Run parse_pages_to_evidence for html responses (soft-error pages skipped).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print JSON array (default: JSON lines)",
    )
    args = p.parse_args()
    allowed = args.allowed_netloc or urlparse(args.urls[0]).netloc
    if not allowed:
        print("Could not determine allowed netloc; pass --allowed-netloc", file=sys.stderr)
        sys.exit(1)

    http = HttpClient()
    robots = RobotsPolicy(DEFAULT_UA)
    results: list[ProbeResult] = [probe_url(u, allowed_seed_netloc=allowed, http=http, robots=robots, do_parse=args.parse) for u in args.urls]

    out: list[dict[str, Any]] = [asdict(r) for r in results]
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        for row in out:
            print(json.dumps(row))


if __name__ == "__main__":
    main()
