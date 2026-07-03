"""Scoring: dev portal vs developer_docs absence — suppression before evaluate_rules."""

from __future__ import annotations

from invendx.config_loader import load_score_rules
from invendx.models.evidence import EvidenceRecord
from invendx.pipeline.evidence_views import suppress_developer_docs_absence_when_dev_portal_present
from invendx.pipeline.score_engine import evaluate_rules


def _absence_dev_docs(*, eid: str = "abs", run_id: str = "r1") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=eid,
        vendor_id="v",
        vendor_name="Co",
        run_id=run_id,
        source_type="official_site",
        source_url="https://co.example/",
        evidence_type="absence_signal",
        claim_text="No developer documentation section observed",
        tags="developer_docs",
        parser_version="0.1.0",
        collected_at="2026-01-02T00:00:00+00:00",
    )


def _portal(*, eid: str = "portal", run_id: str = "r1") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=eid,
        vendor_id="v",
        vendor_name="Co",
        run_id=run_id,
        source_type="official_site",
        source_url="https://co.example/docs",
        evidence_type="dev_portal_signal",
        claim_text="Developer docs linked from homepage",
        parser_version="0.1.0",
        collected_at="2026-01-02T01:00:00+00:00",
    )


def test_absence_only_scores_dev_docs_absence_rule() -> None:
    cfg = load_score_rules("config/score_rules.yaml")
    items = evaluate_rules(cfg, [_absence_dev_docs()])
    assert any(i.rule_id == "dev_docs_absence" for i in items)
    assert not any(i.rule_id == "dev_portal_link" for i in items)


def test_portal_only_scores_dev_portal_rule() -> None:
    cfg = load_score_rules("config/score_rules.yaml")
    items = evaluate_rules(cfg, [_portal()])
    assert any(i.rule_id == "dev_portal_link" for i in items)
    assert not any(i.rule_id == "dev_docs_absence" for i in items)


def test_both_present_without_filter_can_score_both_rules() -> None:
    cfg = load_score_rules("config/score_rules.yaml")
    items = evaluate_rules(cfg, [_absence_dev_docs(), _portal()])
    assert any(i.rule_id == "dev_portal_link" for i in items)
    assert any(i.rule_id == "dev_docs_absence" for i in items)


def test_both_present_after_suppression_scores_portal_only() -> None:
    cfg = load_score_rules("config/score_rules.yaml")
    ev = suppress_developer_docs_absence_when_dev_portal_present(
        [_absence_dev_docs(), _portal()]
    )
    items = evaluate_rules(cfg, ev)
    assert any(i.rule_id == "dev_portal_link" for i in items)
    assert not any(i.rule_id == "dev_docs_absence" for i in items)
