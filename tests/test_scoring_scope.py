"""Scoring scope: default latest ingest run vs --all-evidence."""

from __future__ import annotations

import uuid
from pathlib import Path

from invendx import PARSER_VERSION
from invendx.config_loader import load_score_rules
from invendx.models.vendor import VendorSeed
from invendx.pipeline import report_builder
from invendx.pipeline.score_engine import evaluate_rules
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, vendor_repo
from invendx.cli import _execute_score


def _vendor_and_runs(
    conn,
    *,
    run_old_started: str = "2026-01-01T10:00:00+00:00",
    run_new_started: str = "2026-01-02T10:00:00+00:00",
) -> tuple[str, str, str]:
    v = vendor_repo.upsert_vendor(
        conn,
        VendorSeed(canonical_name="ScopeCo", primary_domain="scope.example", primary_segment="x"),
    )
    rid_old = str(uuid.uuid4())
    rid_new = str(uuid.uuid4())
    evidence_repo.insert_run(conn, rid_old, v.vendor_id, PARSER_VERSION, notes="old")
    cur = conn.cursor()
    cur.execute("UPDATE runs SET started_at = ? WHERE run_id = ?", (run_old_started, rid_old))
    conn.commit()
    evidence_repo.insert_run(conn, rid_new, v.vendor_id, PARSER_VERSION, notes="new")
    cur.execute("UPDATE runs SET started_at = ? WHERE run_id = ?", (run_new_started, rid_new))
    conn.commit()
    assert evidence_repo.get_latest_run_id_for_vendor(conn, v.vendor_id) == rid_new
    return v.vendor_id, rid_old, rid_new


def test_list_evidence_filter_by_run_id(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    vid, rid_old, rid_new = _vendor_and_runs(conn)
    e_old = _fake_evidence(vid, "ScopeCo", rid_old, "e-old", "keyword_signal")
    e_new = _fake_evidence(vid, "ScopeCo", rid_new, "e-new", "page_crawl")
    evidence_repo.insert_evidence(conn, [e_old, e_new])
    all_e = evidence_repo.list_evidence_for_vendor(conn, vid)
    assert len(all_e) == 2
    only_new = evidence_repo.list_evidence_for_vendor(conn, vid, run_id=rid_new)
    assert len(only_new) == 1 and only_new[0].evidence_id == "e-new"


def test_evaluate_default_latest_run_excludes_prior_run_keyword(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    vid, rid_old, rid_new = _vendor_and_runs(conn)
    e_old = _fake_evidence(vid, "ScopeCo", rid_old, "e-old", "keyword_signal")
    e_new = _fake_evidence(vid, "ScopeCo", rid_new, "e-new", "page_crawl")
    evidence_repo.insert_evidence(conn, [e_old, e_new])
    cfg = load_score_rules("config/score_rules.yaml")
    ev_last = evidence_repo.list_evidence_for_vendor(conn, vid, run_id=rid_new)
    items_last = evaluate_rules(cfg, ev_last)
    assert not any(i.rule_id == "keyword_signal_present" for i in items_last)
    ev_all = evidence_repo.list_evidence_for_vendor(conn, vid)
    items_all = evaluate_rules(cfg, ev_all)
    assert any(i.rule_id == "keyword_signal_present" for i in items_all)


def test_execute_score_matches_cli_default_and_all_evidence(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    v = vendor_repo.upsert_vendor(
        conn,
        VendorSeed(canonical_name="Co2", primary_domain="co2.example", primary_segment="x"),
    )
    rid_old = str(uuid.uuid4())
    rid_new = str(uuid.uuid4())
    evidence_repo.insert_run(conn, rid_old, v.vendor_id, PARSER_VERSION)
    cur = conn.cursor()
    cur.execute("UPDATE runs SET started_at = ? WHERE run_id = ?", ("2026-01-01T00:00:00+00:00", rid_old))
    conn.commit()
    evidence_repo.insert_run(conn, rid_new, v.vendor_id, PARSER_VERSION)
    cur.execute("UPDATE runs SET started_at = ? WHERE run_id = ?", ("2026-01-02T00:00:00+00:00", rid_new))
    conn.commit()
    evidence_repo.insert_evidence(
        conn,
        [
            _fake_evidence(v.vendor_id, v.canonical_name, rid_old, "e1", "keyword_signal"),
            _fake_evidence(v.vendor_id, v.canonical_name, rid_new, "e2", "page_crawl"),
        ],
    )
    rules = Path("config/score_rules.yaml")
    _, n_default, _ = _execute_score(conn, v, rules, all_evidence=False)
    _, n_all, _ = _execute_score(conn, v, rules, all_evidence=True)
    assert n_default < n_all


def test_export_scorecard_and_report_reflect_latest_score_run(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    vid, rid_old, rid_new = _vendor_and_runs(conn)
    evidence_repo.insert_evidence(
        conn,
        [
            _fake_evidence(vid, "ScopeCo", rid_old, "e-old", "keyword_signal"),
            _fake_evidence(vid, "ScopeCo", rid_new, "e-new", "page_crawl"),
        ],
    )
    v = vendor_repo.find_vendor_by_canonical_name(conn, "ScopeCo")
    assert v is not None
    rules = Path("config/score_rules.yaml")
    _execute_score(conn, v, rules, all_evidence=False, ingest_run_id=rid_new)
    out_csv = tmp_path / "sc.csv"
    out_md = tmp_path / "r.md"
    report_builder.export_scorecard_csv(conn, vid, out_csv)
    report_builder.export_vendor_markdown(conn, vid, out_md)
    csv_text = out_csv.read_text(encoding="utf-8")
    assert "keyword_signal_present" not in csv_text
    md = out_md.read_text(encoding="utf-8")
    assert "Latest scorecard" in md
    assert "latest ingest run" in md.lower()
    _execute_score(conn, v, rules, all_evidence=True)
    report_builder.export_scorecard_csv(conn, vid, out_csv)
    csv2 = out_csv.read_text(encoding="utf-8")
    assert "keyword_signal_present" in csv2
    assert "e-old" in csv2


def _fake_evidence(
    vendor_id: str,
    vendor_name: str,
    run_id: str,
    eid: str,
    evidence_type: str,
):
    from invendx.models.evidence import EvidenceRecord

    return EvidenceRecord(
        evidence_id=eid,
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        run_id=run_id,
        source_type="official_site",
        source_url="https://x",
        evidence_type=evidence_type,
        claim_text="claim",
        confidence="medium",
        tags="x" if evidence_type == "keyword_signal" else "crawl",
        parser_version=PARSER_VERSION,
        collected_at="2026-01-01T12:00:00+00:00",
    )
