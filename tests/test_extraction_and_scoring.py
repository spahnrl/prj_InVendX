"""Regression tests for HTML → evidence extraction and rule matching (MVP heuristics)."""

from __future__ import annotations

import pytest

import invendx.extract.patterns as pattern_mod
from invendx.config_loader import load_score_rules
from invendx.models.discovery import PageDocument
from invendx.models.evidence import EvidenceRecord
from invendx.models.scoring import ScoreRulesConfig, ScoreRuleSpec
from invendx.models.vendor import VendorRecord
from invendx.pipeline.press_parser import parse_pages_to_evidence
from invendx.pipeline.score_engine import evaluate_rules


@pytest.fixture(autouse=True)
def reset_arch_keywords() -> None:
    """Avoid cross-test pollution if another test called load_keywords()."""
    pattern_mod._ARCH_TERMS = []
    yield
    pattern_mod._ARCH_TERMS = []


def _vendor() -> VendorRecord:
    return VendorRecord(
        vendor_id="v-test",
        canonical_name="TestCo",
        primary_domain="vendor.example",
        primary_segment="Test",
    )


def _page(html: str, url: str = "https://vendor.example/news") -> PageDocument:
    return PageDocument(
        url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        html=html,
        fetched_at="2026-01-01T12:00:00+00:00",
    )


def test_parse_pages_keyword_signal_tags_from_body() -> None:
    html = "<html><head><title>Platform</title></head><body>FIX connectivity and cloud deployment.</body></html>"
    recs = parse_pages_to_evidence([_page(html)], _vendor(), "run-1", "0.1.0")
    kw = [r for r in recs if r.evidence_type == "keyword_signal"]
    assert len(kw) == 1
    tags = {t.strip() for t in kw[0].tags.split(",")}
    assert "fix" in tags
    assert "cloud" in tags


def test_parse_pages_integration_when_partnership_language() -> None:
    html = (
        "<html><head><title>News</title></head>"
        "<body>We announced a strategic partnership with Example Corp.</body></html>"
    )
    recs = parse_pages_to_evidence([_page(html)], _vendor(), "run-1", "0.1.0")
    kinds = {r.evidence_type for r in recs}
    assert "integration" in kinds
    integ = next(r for r in recs if r.evidence_type == "integration")
    assert "integration" in integ.tags


def test_parse_pages_dev_portal_signal_from_docs_href() -> None:
    html = (
        "<html><head><title>Home</title></head>"
        "<body><p>Welcome</p><a href=\"/docs/api\">Developer docs</a></body></html>"
    )
    url = "https://vendor.example/"
    recs = parse_pages_to_evidence([_page(html, url=url)], _vendor(), "run-1", "0.1.0")
    dev = [r for r in recs if r.evidence_type == "dev_portal_signal"]
    assert len(dev) >= 1
    assert any("docs" in r.claim_text.lower() for r in dev)


def test_score_rules_keyword_and_tag_based_matching() -> None:
    cfg_prod = load_score_rules("config/score_rules.yaml")
    ev_keyword = EvidenceRecord(
        evidence_id="e-kw",
        vendor_id="v",
        vendor_name="Co",
        run_id="r",
        source_type="official_site",
        source_url="https://x",
        evidence_type="keyword_signal",
        claim_text="keywords present",
        confidence="medium",
        tags="fix,api",
        parser_version="0.1.0",
        collected_at="2026-01-02T00:00:00+00:00",
    )
    items_kw = evaluate_rules(cfg_prod, [ev_keyword])
    assert any(i.rule_id == "keyword_signal_present" for i in items_kw)

    ev_hire_no_api = EvidenceRecord(
        evidence_id="e-h0",
        vendor_id="v",
        vendor_name="Co",
        run_id="r",
        source_type="careers_page",
        source_url="https://x/jobs",
        evidence_type="hiring_signal",
        claim_text="careers scan",
        confidence="low",
        tags="careers,hiring",
        parser_version="0.1.0",
        collected_at="2026-01-02T00:01:00+00:00",
    )
    ev_hire_api = ev_hire_no_api.model_copy(
        update={"evidence_id": "e-h1", "tags": "careers,hiring,api", "collected_at": "2026-01-02T00:02:00+00:00"}
    )
    hiring_items = evaluate_rules(cfg_prod, [ev_hire_no_api])
    assert not any(i.rule_id == "hiring_tech_keywords" for i in hiring_items)
    hiring_ok = evaluate_rules(cfg_prod, [ev_hire_api])
    assert any(i.rule_id == "hiring_tech_keywords" for i in hiring_ok)

    cfg_tag = ScoreRulesConfig(
        ruleset_version="test",
        rules=[
            ScoreRuleSpec(
                id="need_both",
                category="X",
                points=1.0,
                max_citations=3,
                match={
                    "evidence_type_in": ["absence_signal"],
                    "tag_contains": "developer_docs",
                },
            )
        ],
    )
    ev_abs = EvidenceRecord(
        evidence_id="e-a",
        vendor_id="v",
        vendor_name="Co",
        run_id="r",
        source_type="official_site",
        source_url="https://x/",
        evidence_type="absence_signal",
        claim_text="no docs",
        confidence="low",
        tags="absence,developer_docs",
        parser_version="0.1.0",
        collected_at="2026-01-02T00:03:00+00:00",
    )
    tag_items = evaluate_rules(cfg_tag, [ev_abs])
    assert len(tag_items) == 1 and tag_items[0].rule_id == "need_both"
