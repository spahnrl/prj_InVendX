import csv
import uuid

from invendx import PARSER_VERSION
from invendx.models.scoring import ScoreLineItem
from invendx.models.vendor import VendorSeed
from invendx.pipeline import report_builder
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, score_repo, vendor_repo


def test_export_scorecard_empty(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    seed = VendorSeed(canonical_name="Co", primary_domain="co.example", primary_segment="x")
    v = vendor_repo.upsert_vendor(conn, seed)
    out = tmp_path / "sc.csv"
    report_builder.export_scorecard_csv(conn, v.vendor_id, out)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert "score_run_id" in lines[0]
    assert len(lines) == 1


def test_export_scorecard_with_run(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    seed = VendorSeed(canonical_name="Co", primary_domain="co.example", primary_segment="x")
    v = vendor_repo.upsert_vendor(conn, seed)
    run_id = str(uuid.uuid4())
    evidence_repo.insert_run(conn, run_id, v.vendor_id, PARSER_VERSION)
    items = [
        ScoreLineItem(
            line_id="l1",
            score_run_id="",
            category="Cat",
            rule_id="r1",
            points=1.0,
            rationale="ok",
            evidence_ids=["e1"],
        )
    ]
    score_repo.insert_score_run(conn, v.vendor_id, v.canonical_name, "0.9.0", items)
    out = tmp_path / "sc.csv"
    report_builder.export_scorecard_csv(conn, v.vendor_id, out)
    with out.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["rule_id"] == "r1"
    assert rows[0]["ruleset_version"] == "0.9.0"
    assert "e1" in rows[0]["evidence_ids_json"]


def test_latest_score_category_totals(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    seed = VendorSeed(canonical_name="Co", primary_domain="co.example", primary_segment="x")
    v = vendor_repo.upsert_vendor(conn, seed)
    assert score_repo.latest_score_category_totals(conn, v.vendor_id) is None

    run_id = str(uuid.uuid4())
    evidence_repo.insert_run(conn, run_id, v.vendor_id, PARSER_VERSION)
    items = [
        ScoreLineItem(
            line_id="l1",
            score_run_id="",
            category="A",
            rule_id="r1",
            points=1.0,
            rationale="",
            evidence_ids=[],
        ),
        ScoreLineItem(
            line_id="l2",
            score_run_id="",
            category="A",
            rule_id="r2",
            points=2.0,
            rationale="",
            evidence_ids=[],
        ),
        ScoreLineItem(
            line_id="l3",
            score_run_id="",
            category="B",
            rule_id="r3",
            points=0.5,
            rationale="",
            evidence_ids=[],
        ),
    ]
    score_repo.insert_score_run(conn, v.vendor_id, v.canonical_name, "0.9.0", items)
    agg = score_repo.latest_score_category_totals(conn, v.vendor_id)
    assert agg is not None
    total, by_cat = agg
    assert total == 3.5
    assert by_cat == {"A": 3.0, "B": 0.5}
