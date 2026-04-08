from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import typer
from dotenv import load_dotenv

load_dotenv()

from invendx import PARSER_VERSION
from invendx.config_loader import load_score_rules, load_vendor_seeds
from invendx.http.client import DEFAULT_UA, HttpClient
from invendx.http.robots import RobotsPolicy
from invendx.logging_config import setup_logging
from invendx.pipeline.github_collector import collect_github_org
from invendx.pipeline.job_collector import collect_job_signals
from invendx.pipeline.press_parser import dev_docs_absence_evidence, parse_pages_to_evidence
from invendx.pipeline.score_engine import evaluate_rules
from invendx.pipeline.site_crawler import SiteCrawler
from invendx.pipeline.source_discovery import discover_vendor
from invendx.pipeline.vendor_summary import refresh_vendor_summary
from invendx.extract.patterns import load_keywords
from invendx.pipeline.entity_normalizer import EntityNormalizer
from invendx.pipeline import report_builder
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, score_repo, vendor_repo

app = typer.Typer(no_args_is_help=True)
vendors_app = typer.Typer(no_args_is_help=True)
app.add_typer(vendors_app, name="vendors")


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
    crawler = SiteCrawler(http, robots)
    pages = crawler.crawl_from_targets(targets)
    records = parse_pages_to_evidence(pages, v, run_id, PARSER_VERSION)

    absence = dev_docs_absence_evidence(v, run_id, [p.final_url for p in pages], PARSER_VERSION)
    if absence:
        records.append(absence)

    records.extend(collect_job_signals(v, targets, http, robots, run_id, PARSER_VERSION))

    if v.github_org:
        records.extend(collect_github_org(v, v.github_org, run_id, PARSER_VERSION))

    normalizer = EntityNormalizer.from_yaml(aliases)
    records = normalizer.normalize_evidence_entities(records)

    evidence_repo.insert_evidence(conn, records)
    refresh_vendor_summary(conn, v.vendor_id)
    typer.echo(f"Run {run_id}: stored {len(records)} evidence rows for {vendor}")


@app.command()
def score(
    vendor: str = typer.Argument(...),
    db: Path = typer.Option(Path("data/invendx.db"), "--db", "-d"),
    rules: Path = typer.Option(Path("config/score_rules.yaml"), "--rules", "-r"),
) -> None:
    setup_logging()
    conn = connect(db)
    init_schema(conn)
    v = vendor_repo.find_vendor_by_canonical_name(conn, vendor)
    if not v:
        typer.echo(f"Vendor not in DB: {vendor}", err=True)
        raise typer.Exit(1)
    cfg = load_score_rules(rules)
    ev = evidence_repo.list_evidence_for_vendor(conn, v.vendor_id)
    items = evaluate_rules(cfg, ev)
    score_repo.insert_score_run(conn, v.vendor_id, v.canonical_name, cfg.ruleset_version, items)
    typer.echo(f"Scored {vendor}: {len(items)} line items ({cfg.ruleset_version})")


@app.command("export")
def export_cmd(
    what: str = typer.Argument(..., help="evidence | report | summaries"),
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
    if not vendor:
        typer.echo("--vendor required for evidence/report", err=True)
        raise typer.Exit(1)
    v = vendor_repo.find_vendor_by_canonical_name(conn, vendor)
    if not v:
        typer.echo(f"Vendor not in DB: {vendor}", err=True)
        raise typer.Exit(1)
    if what == "evidence":
        path = report_builder.export_evidence_csv(conn, v.vendor_id, out / f"{vendor}_evidence.csv")
    elif what == "report":
        path = report_builder.export_vendor_markdown(conn, v.vendor_id, out / f"{vendor}_report.md")
    else:
        typer.echo("what must be evidence, report, or summaries", err=True)
        raise typer.Exit(1)
    typer.echo(str(path))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
