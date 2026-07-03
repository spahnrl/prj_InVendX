"""Manual intake staging and promotion to evidence."""

from __future__ import annotations

from pathlib import Path

from invendx.config_loader import load_score_rules
from invendx.models.vendor import VendorSeed
from invendx.pipeline.manual_intake import (
    default_instructions_key,
    discard_duplicate_active_intakes_by_url,
    normalize_source_url,
    parse_crawl_skipped_urls_from_run_notes,
    promote_intake_to_evidence,
    queue_crawl_skipped_urls_for_vendor,
)
from invendx.pipeline.score_engine import evaluate_rules
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, manual_intake_repo, vendor_repo


def _vendor(conn, name: str = "ManCo") -> object:
    seed = VendorSeed(
        canonical_name=name,
        primary_domain="manual.example",
        primary_segment="Test",
        aliases=[],
        seed_urls={},
    )
    return vendor_repo.upsert_vendor(conn, seed)


def test_normalize_source_url_strips_fragment() -> None:
    assert normalize_source_url("https://a.com/x#frag ") == "https://a.com/x"


def test_default_instructions_key_maps_reason() -> None:
    assert default_instructions_key("robots_blocked") == "robots_blocked"
    assert default_instructions_key("unknown_reason") == "general"


def test_manual_intake_lifecycle_and_promote(tmp_path) -> None:
    db = tmp_path / "m.db"
    conn = connect(db)
    init_schema(conn)
    v = _vendor(conn)
    iid = manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url="https://manual.example/docs",
        source_type="target_official",
        reason_flagged="robots_blocked",
        instructions_key="robots_blocked",
        operator_notes="note",
    )
    rows = manual_intake_repo.list_intakes_for_vendor(conn, v.vendor_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"

    assert manual_intake_repo.save_capture(
        conn, iid, captured_text="  API overview and FIX integration.  ", captured_by="jdoe"
    )
    row = manual_intake_repo.get_intake(conn, iid)
    assert row["status"] == "captured"
    assert "FIX" in (row["captured_text"] or "")

    run_id, ev_ids, err = promote_intake_to_evidence(conn, iid)
    assert err is None
    assert run_id and ev_ids and len(ev_ids) == 1

    row2 = manual_intake_repo.get_intake(conn, iid)
    assert row2["status"] == "ingested"
    assert row2["promoted_run_id"] == run_id

    ev = evidence_repo.list_evidence_for_vendor(conn, v.vendor_id, run_id=run_id)
    assert len(ev) == 1
    e = ev[0]
    assert e.evidence_type == "manual_capture"
    assert e.source_type == "manual"
    assert e.source_url == "https://manual.example/docs"
    assert "manual" in e.tags
    assert "reason:robots_blocked" in e.tags
    assert f"intake_id:{iid}" in e.tags
    assert e.raw_text_excerpt and "FIX" in e.raw_text_excerpt
    assert e.dedupe_hash


def test_promote_requires_text(tmp_path) -> None:
    db = tmp_path / "m2.db"
    conn = connect(db)
    init_schema(conn)
    v = _vendor(conn, "NoTextCo")
    iid = manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url="https://x.com/a",
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
    )
    _a, _b, err = promote_intake_to_evidence(conn, iid)
    assert err == "no captured text; save capture first"


def test_second_promote_same_intake_rejected(tmp_path) -> None:
    db = tmp_path / "m3.db"
    conn = connect(db)
    init_schema(conn)
    v = _vendor(conn, "DupCo")
    iid = manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url="https://dup.example/page",
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
    )
    manual_intake_repo.save_capture(conn, iid, captured_text="unique body", captured_by="a")
    r1, ids1, e1 = promote_intake_to_evidence(conn, iid)
    assert e1 is None and r1 and ids1
    r2, ids2, e2 = promote_intake_to_evidence(conn, iid)
    assert r2 is None and ids2 is None
    assert e2 == "already ingested"


def test_scoring_isolation_manual_capture(tmp_path) -> None:
    db = tmp_path / "m4.db"
    conn = connect(db)
    init_schema(conn)
    v = _vendor(conn, "ScoreCo")
    iid = manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url="https://score.example/",
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
    )
    manual_intake_repo.save_capture(conn, iid, captured_text="keyword api integration", captured_by="x")
    _r, ev_ids, err = promote_intake_to_evidence(conn, iid)
    assert err is None
    ev = evidence_repo.list_evidence_for_vendor(conn, v.vendor_id)
    assert len(ev) == 1
    rules_path = Path(__file__).resolve().parent.parent / "config" / "score_rules.yaml"
    cfg = load_score_rules(rules_path)
    items = evaluate_rules(cfg, ev)
    assert items == []


def test_parse_crawl_skipped_from_run_notes() -> None:
    raw = '{"crawl_skipped_urls": [{"url": "https://a.com/x", "crawl_reason": "robots_denied"}]}'
    got = parse_crawl_skipped_urls_from_run_notes(raw)
    assert len(got) == 1 and got[0]["url"] == "https://a.com/x"


def test_insert_intake_skip_if_url_exists(tmp_path) -> None:
    db = tmp_path / "dup.db"
    conn = connect(db)
    init_schema(conn)
    v = _vendor(conn, "DupUrlCo")
    u = "https://dup.example/page"
    a = manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url=u,
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
    )
    assert a
    b = manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url=u,
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
        skip_if_url_exists=True,
    )
    assert b is None


def test_discard_duplicate_active_intakes_by_url(tmp_path) -> None:
    db = tmp_path / "dedupe.db"
    conn = connect(db)
    init_schema(conn)
    v = _vendor(conn, "DedupeCo")
    url = "https://dedupe.example/same"
    manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url=url,
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
    )
    manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url=url,
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
    )
    rows = manual_intake_repo.list_intakes_for_vendor(conn, v.vendor_id, include_ingested=False)
    assert len(rows) == 2
    nd = discard_duplicate_active_intakes_by_url(conn, v.vendor_id)
    assert nd == 1
    rows2 = manual_intake_repo.list_intakes_for_vendor(conn, v.vendor_id, include_ingested=False)
    assert len(rows2) == 1


def test_discard_duplicates_prefers_captured(tmp_path) -> None:
    db = tmp_path / "dedupe2.db"
    conn = connect(db)
    init_schema(conn)
    v = _vendor(conn, "CapCo")
    url = "https://cap.example/x"
    manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url=url,
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
    )
    i_cap = manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url=url,
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
    )
    manual_intake_repo.save_capture(conn, i_cap, captured_text="body", captured_by="t")
    nd = discard_duplicate_active_intakes_by_url(conn, v.vendor_id)
    assert nd == 1
    left = manual_intake_repo.list_intakes_for_vendor(conn, v.vendor_id, include_ingested=False)
    assert len(left) == 1
    assert left[0]["intake_id"] == i_cap


def test_queue_crawl_skipped_for_vendor(tmp_path) -> None:
    db = tmp_path / "sk.db"
    conn = connect(db)
    init_schema(conn)
    v = _vendor(conn, "SkipCo")
    n = queue_crawl_skipped_urls_for_vendor(
        conn,
        v.vendor_id,
        [{"url": "https://skip.example/r", "crawl_reason": "robots_denied"}],
    )
    assert n == 1
    rows = manual_intake_repo.list_intakes_for_vendor(conn, v.vendor_id)
    assert rows[0]["reason_flagged"] == "robots_blocked"
    n2 = queue_crawl_skipped_urls_for_vendor(
        conn,
        v.vendor_id,
        [{"url": "https://skip.example/r", "crawl_reason": "robots_denied"}],
    )
    assert n2 == 0


def test_discard_intake(tmp_path) -> None:
    db = tmp_path / "m5.db"
    conn = connect(db)
    init_schema(conn)
    v = _vendor(conn, "DiscardCo")
    iid = manual_intake_repo.insert_intake(
        conn,
        vendor_id=v.vendor_id,
        source_url="https://d.com/",
        source_type="target_official",
        reason_flagged="other",
        instructions_key="general",
    )
    assert manual_intake_repo.mark_discarded(conn, iid)
    _r, _ids, err = promote_intake_to_evidence(conn, iid)
    assert err == "discarded intake"
