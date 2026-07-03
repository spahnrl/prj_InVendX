from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path

import typer
from dotenv import load_dotenv

from invendx import PARSER_VERSION
from invendx.config_loader import load_score_rules, load_vendor_seeds
from invendx.http.client import DEFAULT_UA, HttpClient
from invendx.http.robots import RobotsPolicy
from invendx.logging_config import setup_logging
from invendx.pipeline.github_collector import collect_github_org
from invendx.pipeline.job_collector import collect_job_signals
from invendx.pipeline.browser_capture import (
    CAPTURE_METHOD_CHROME_FETCH,
    BrowserCaptureError,
    extract_visible_text,
)
from invendx.pipeline.manual_intake import (
    discard_duplicate_active_intakes_by_url,
    promote_intake_to_evidence,
)
from invendx.pipeline.press_parser import dev_docs_absence_evidence, parse_pages_to_evidence
from invendx.pipeline.score_engine import evaluate_rules
from invendx.pipeline.site_crawler import CrawlConfig, SiteCrawler
from invendx.pipeline.source_discovery import discover_vendor
from invendx.pipeline.vendor_summary import refresh_vendor_summary
from invendx.extract.patterns import load_keywords
from invendx.pipeline.entity_normalizer import EntityNormalizer
from invendx.pipeline.evidence_fingerprint import assign_dedupe_hashes
from invendx.pipeline.evidence_views import (
    dedupe_evidence_for_scoring,
    suppress_developer_docs_absence_when_dev_portal_present,
)
from invendx.pipeline import report_builder
from invendx.models.vendor import VendorRecord
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, manual_intake_repo, score_repo, vendor_repo

load_dotenv()

app = typer.Typer(no_args_is_help=True)
vendors_app = typer.Typer(no_args_is_help=True)
manual_app = typer.Typer(no_args_is_help=True)
app.add_typer(vendors_app, name="vendors")
app.add_typer(manual_app, name="manual")


def _execute_score(
    conn: sqlite3.Connection,
    vendor: VendorRecord,
    rules: Path,
    *,
    all_evidence: bool = False,
    ingest_run_id: str | None = None,
) -> tuple[str, int, str]:
    """Load rules, evaluate evidence for vendor, persist score run.

    By default uses evidence for the latest ingest ``run_id`` only (or ``ingest_run_id`` when set).
    Pass ``all_evidence=True`` to score across all stored evidence for the vendor.
    """
    cfg = load_score_rules(rules)
    if all_evidence:
        ev = evidence_repo.list_evidence_for_vendor(conn, vendor.vendor_id)
    else:
        rid = ingest_run_id or evidence_repo.get_latest_run_id_for_vendor(conn, vendor.vendor_id)
        if rid is None:
            ev = []
        else:
            ev = evidence_repo.list_evidence_for_vendor(conn, vendor.vendor_id, run_id=rid)
    ev = dedupe_evidence_for_scoring(ev)
    ev = suppress_developer_docs_absence_when_dev_portal_present(ev)
    items = evaluate_rules(cfg, ev)
    score_run_id = score_repo.insert_score_run(
        conn, vendor.vendor_id, vendor.canonical_name, cfg.ruleset_version, items
    )
    return score_run_id, len(items), cfg.ruleset_version


@manual_app.command("promote")
def manual_promote(
    intake_id: str = typer.Argument(..., help="manual_intake_queue.intake_id"),
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
) -> None:
    """Promote one staged manual capture to the evidence table (no scoring)."""
    setup_logging()
    conn = connect(db)
    init_schema(conn)
    run_id, ev_ids, err = promote_intake_to_evidence(conn, intake_id)
    if err:
        typer.echo(err, err=True)
        raise typer.Exit(1)
    typer.echo(f"Promoted {intake_id}: run {run_id} evidence {ev_ids}")


@manual_app.command("fetch")
def manual_fetch(
    intake_id: str = typer.Argument(..., help="manual_intake_queue.intake_id"),
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
    headed: bool = typer.Option(False, "--headed", help="Show browser window (Chrome / Chromium)"),
    connect_cdp: str | None = typer.Option(
        None,
        "--connect-cdp",
        help="Attach to Chrome you started with remote debugging, e.g. http://127.0.0.1:9222 (ignores --headed)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print extracted text; do not write DB"),
    wait_until: str = typer.Option(
        "domcontentloaded",
        "--wait-until",
        help="Playwright wait_until (e.g. domcontentloaded, load, networkidle)",
    ),
    timeout_ms: int = typer.Option(60_000, "--timeout-ms", help="Navigation timeout in ms"),
) -> None:
    """Fetch rendered page text for a queued URL via Playwright and save the capture (unless --dry-run)."""
    setup_logging()
    conn = connect(db)
    init_schema(conn)
    row = manual_intake_repo.get_intake(conn, intake_id)
    if not row:
        typer.echo(f"No intake row: {intake_id}", err=True)
        raise typer.Exit(1)
    st = row["status"]
    if st == "discarded":
        typer.echo("Intake row is discarded.", err=True)
        raise typer.Exit(1)
    if st == "ingested" and not dry_run:
        typer.echo("Intake row already ingested; use --dry-run to fetch text only.", err=True)
        raise typer.Exit(1)
    url = row["source_url"]
    if not (url or "").strip():
        typer.echo("Intake row has no source_url.", err=True)
        raise typer.Exit(1)
    try:
        text = extract_visible_text(
            url,
            headed=headed if not connect_cdp else False,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
            connect_cdp_url=connect_cdp,
        )
    except BrowserCaptureError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    if dry_run:
        typer.echo(text)
        return
    saved = manual_intake_repo.save_capture(
        conn,
        intake_id,
        captured_text=text,
        captured_by=row.get("captured_by"),
        capture_method=CAPTURE_METHOD_CHROME_FETCH,
    )
    if not saved:
        typer.echo("Could not save capture (wrong status?).", err=True)
        raise typer.Exit(1)
    typer.echo(f"Saved capture for {intake_id} ({len(text)} characters).")


@manual_app.command("dedupe")
def manual_dedupe(
    vendor: str = typer.Argument(..., help="Canonical vendor name"),
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
) -> None:
    """Discard extra manual intake queue rows with the same URL (keep one pending/captured per link)."""
    setup_logging()
    conn = connect(db)
    init_schema(conn)
    v = vendor_repo.find_vendor_by_canonical_name(conn, vendor)
    if not v:
        typer.echo(f"Vendor not in DB: {vendor}. Run: invendx vendors sync", err=True)
        raise typer.Exit(1)
    n = discard_duplicate_active_intakes_by_url(conn, v.vendor_id)
    typer.echo(f"Discarded {n} duplicate manual intake row(s) for {vendor}.")


@vendors_app.command("sync")
def vendors_sync(
    config: Path = typer.Option(Path("config/vendors.yaml"), "--config", "-c"),
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
) -> None:
    setup_logging()
    conn = connect(db)
    init_schema(conn)
    for seed in load_vendor_seeds(config):
        vendor_repo.upsert_vendor(conn, seed)
    typer.echo(f"Synced vendors from {config} into {db}")


@app.command()
def discover(
    vendor: str = typer.Argument(..., help="Canonical vendor name"),
    config: Path = typer.Option(Path("config/vendors.yaml"), "--config", "-c"),
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
    emit_json: bool = typer.Option(False, "--json", help="Print targets as JSON"),
) -> None:
    setup_logging()
    conn = connect(db)
    init_schema(conn)
    v = vendor_repo.find_vendor_by_canonical_name(conn, vendor)
    if not v:
        typer.echo(f"Vendor not in DB: {vendor}. Run: invendx vendors sync", err=True)
        raise typer.Exit(1)
    http = HttpClient()
    targets = discover_vendor(v, http=http)
    if emit_json:
        typer.echo(json.dumps([t.model_dump() for t in targets], indent=2))
    else:
        for t in targets:
            typer.echo(f"{t.priority:3d} [{t.kind}] {t.url}")


@app.command()
def run(
    vendor: str = typer.Argument(..., help="Canonical vendor name"),
    config: Path = typer.Option(Path("config/vendors.yaml"), "--config", "-c"),
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
    keywords: Path = typer.Option(Path("config/keywords.yaml"), "--keywords", "-k"),
    aliases: Path = typer.Option(Path("config/aliases.yaml"), "--aliases", "-a"),
    score: bool = typer.Option(False, "--score", help="Run rule-based scoring after ingest"),
    rules: Path = typer.Option(Path("config/score_rules.yaml"), "--rules", "-r"),
    max_pages: int | None = typer.Option(None, "--max-pages", help="Max pages to fetch (default: 40)"),
    max_depth: int | None = typer.Option(None, "--max-depth", help="Max link depth from seeds (default: 2)"),
    delay_s: float | None = typer.Option(None, "--delay", help="Seconds between requests (default: 0.75)"),
    all_evidence: bool = typer.Option(
        False,
        "--all-evidence",
        help="With --score: include all vendor evidence (default: latest ingest run only)",
    ),
) -> None:
    setup_logging()
    log = logging.getLogger("invendx.run")
    load_keywords(keywords)
    conn = connect(db)
    init_schema(conn)
    v = vendor_repo.find_vendor_by_canonical_name(conn, vendor)
    if not v:
        typer.echo(f"Vendor not in DB: {vendor}. Run: invendx vendors sync", err=True)
        raise typer.Exit(1)

    run_id = str(uuid.uuid4())
    evidence_repo.insert_run(conn, run_id, v.vendor_id, PARSER_VERSION, notes="cli run")
    log.info("run_id=%s vendor=%s", run_id, vendor)

    http = HttpClient()
    robots = RobotsPolicy(DEFAULT_UA)
    targets = discover_vendor(v, http=http)
    crawl_config = CrawlConfig()
    if max_pages is not None:
        crawl_config = replace(crawl_config, max_pages=max_pages)
    if max_depth is not None:
        crawl_config = replace(crawl_config, max_depth=max_depth)
    if delay_s is not None:
        crawl_config = replace(crawl_config, delay_s=delay_s)
    crawler = SiteCrawler(http, robots, crawl_config)
    pages = crawler.crawl_from_targets(targets)
    ct = crawler.last_telemetry
    log.info(
        "crawl telemetry: robots_denied=%s http_not_ok=%s non_html_skipped=%s "
        "fetch_failed=%s pages_stored=%s",
        ct.robots_denied,
        ct.http_not_ok,
        ct.non_html_skipped,
        ct.fetch_failed,
        ct.pages_stored,
    )
    typer.echo(
        "Crawl telemetry: "
        f"robots_denied={ct.robots_denied} "
        f"http_not_ok={ct.http_not_ok} "
        f"non_html_skipped={ct.non_html_skipped} "
        f"fetch_failed={ct.fetch_failed} "
        f"pages_stored={ct.pages_stored}"
    )
    notes_obj = {
        "cli_run": True,
        "crawl_telemetry": {
            "robots_denied": ct.robots_denied,
            "http_not_ok": ct.http_not_ok,
            "non_html_skipped": ct.non_html_skipped,
            "fetch_failed": ct.fetch_failed,
            "pages_stored": ct.pages_stored,
        },
        "crawl_skipped_urls": ct.skipped_urls,
    }
    evidence_repo.update_run_notes(conn, run_id, json.dumps(notes_obj, ensure_ascii=False))
    records = parse_pages_to_evidence(pages, v, run_id, PARSER_VERSION)

    absence = dev_docs_absence_evidence(v, run_id, [p.final_url for p in pages], PARSER_VERSION)
    if absence:
        records.append(absence)

    records.extend(collect_job_signals(v, targets, http, robots, run_id, PARSER_VERSION))

    if v.github_org:
        records.extend(collect_github_org(v, v.github_org, run_id, PARSER_VERSION))

    normalizer = EntityNormalizer.from_yaml(aliases)
    records = normalizer.normalize_evidence_entities(records)
    records = assign_dedupe_hashes(records)
    to_insert = []
    skipped_dup = 0
    pending_fp: set[str] = set()
    for r in records:
        h = r.dedupe_hash or ""
        if h in pending_fp:
            skipped_dup += 1
            continue
        if h and evidence_repo.vendor_has_dedupe_hash(conn, r.vendor_id, h):
            skipped_dup += 1
            continue
        if h:
            pending_fp.add(h)
        to_insert.append(r)

    evidence_repo.insert_evidence(conn, to_insert)
    refresh_vendor_summary(conn, v.vendor_id)
    typer.echo(
        f"Run {run_id}: stored {len(to_insert)} evidence rows for {vendor}"
        + (f" ({skipped_dup} skipped as duplicate fingerprint)" if skipped_dup else "")
    )
    if score:
        score_run_id, n_items, rver = _execute_score(
            conn,
            v,
            rules,
            all_evidence=all_evidence,
            ingest_run_id=run_id,
        )
        typer.echo(f"Score run {score_run_id}: {n_items} line items ({rver})")


@app.command()
def score(
    vendor: str = typer.Argument(...),
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
    rules: Path = typer.Option(Path("config/score_rules.yaml"), "--rules", "-r"),
    all_evidence: bool = typer.Option(
        False,
        "--all-evidence",
        help="Score using all vendor evidence (default: latest ingest run only)",
    ),
) -> None:
    setup_logging()
    conn = connect(db)
    init_schema(conn)
    v = vendor_repo.find_vendor_by_canonical_name(conn, vendor)
    if not v:
        typer.echo(f"Vendor not in DB: {vendor}", err=True)
        raise typer.Exit(1)
    score_run_id, n_items, rver = _execute_score(conn, v, rules, all_evidence=all_evidence)
    typer.echo(f"Scored {vendor}: {n_items} line items ({rver}) (run {score_run_id})")


@app.command("summaries-refresh")
def summaries_refresh(
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
) -> None:
    """Recompute vendor_summaries (counts and profile hint patterns) from stored evidence.

    Use after upgrading hint extraction so the UI shows new RIA/AUM fields without re-crawling.
    """
    setup_logging()
    conn = connect(db)
    init_schema(conn)
    vendors = vendor_repo.list_vendors(conn)
    for v in vendors:
        refresh_vendor_summary(conn, v.vendor_id)
    typer.echo(f"Refreshed {len(vendors)} vendor summary row(s).")


@app.command("export")
def export_cmd(
    what: str = typer.Argument(
        ..., help="evidence | report | scorecard | summaries | coverage"
    ),
    vendor: str | None = typer.Option(None, "--vendor", "-v"),
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
    out: Path = typer.Option(Path("exports"), "--out", "-o"),
) -> None:
    setup_logging()
    conn = connect(db)
    init_schema(conn)
    if what == "summaries":
        path = report_builder.export_summaries_json(conn, out / "vendor_summaries.json")
        typer.echo(str(path))
        return
    if what == "coverage":
        path = report_builder.export_coverage_csv(conn, out / "vendor_coverage.csv")
        typer.echo(str(path))
        return
    if not vendor:
        typer.echo("--vendor required for evidence, report, or scorecard", err=True)
        raise typer.Exit(1)
    v = vendor_repo.find_vendor_by_canonical_name(conn, vendor)
    if not v:
        typer.echo(f"Vendor not in DB: {vendor}", err=True)
        raise typer.Exit(1)
    if what == "evidence":
        path = report_builder.export_evidence_csv(conn, v.vendor_id, out / f"{vendor}_evidence.csv")
    elif what == "report":
        path = report_builder.export_vendor_markdown(conn, v.vendor_id, out / f"{vendor}_report.md")
    elif what == "scorecard":
        path = report_builder.export_scorecard_csv(conn, v.vendor_id, out / f"{vendor}_scorecard.csv")
    else:
        typer.echo("what must be evidence, report, scorecard, summaries, or coverage", err=True)
        raise typer.Exit(1)
    typer.echo(str(path))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
