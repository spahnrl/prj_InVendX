from invendx.config_loader import load_score_rules
from invendx.models.evidence import EvidenceRecord
from invendx.pipeline.score_engine import evaluate_rules


def test_score_engine_matches_keyword_signal() -> None:
    cfg = load_score_rules("config/score_rules.yaml")
    ev = [
        EvidenceRecord(
            evidence_id="e1",
            vendor_id="v1",
            vendor_name="TestCo",
            run_id="r1",
            source_type="official_site",
            source_url="https://example.com",
            evidence_type="keyword_signal",
            claim_text="mentions FIX and API",
            confidence="medium",
            tags="fix,api",
            parser_version="0.1.0",
            collected_at="2026-01-01T00:00:00+00:00",
        )
    ]
    items = evaluate_rules(cfg, ev)
    assert any(i.rule_id == "keyword_signal_present" for i in items)
    assert any("e1" in i.evidence_ids for i in items)
