from __future__ import annotations

import uuid
from typing import Any

from invendx.models.evidence import EvidenceRecord
from invendx.models.scoring import ScoreLineItem, ScoreRulesConfig, ScoreRuleSpec


def _match_evidence(rule: ScoreRuleSpec, e: EvidenceRecord) -> bool:
    m: dict[str, Any] = rule.match or {}
    if not m:
        return False
    if "evidence_type_in" in m and e.evidence_type not in m["evidence_type_in"]:
        return False
    if "source_type_in" in m and e.source_type not in m["source_type_in"]:
        return False
    if "tag_contains" in m:
        needle = str(m["tag_contains"]).lower()
        if needle not in (e.tags or "").lower():
            return False
    if "claim_contains" in m:
        needle = str(m["claim_contains"]).lower()
        if needle not in e.claim_text.lower():
            return False
    if "claim_regex" in m:
        import re

        if not re.search(str(m["claim_regex"]), e.claim_text, re.I):
            return False
    return True


def evaluate_rules(
    cfg: ScoreRulesConfig,
    evidence: list[EvidenceRecord],
) -> list[ScoreLineItem]:
    items: list[ScoreLineItem] = []
    for rule in cfg.rules:
        matched = [e for e in evidence if _match_evidence(rule, e)]
        if not matched:
            continue
        matched = sorted(matched, key=lambda x: x.collected_at, reverse=True)
        cap = rule.max_citations
        cited = [e.evidence_id for e in matched[:cap] if e.evidence_id]
        rationale = f"rule={rule.id} matched {len(matched)} evidence row(s)"
        items.append(
            ScoreLineItem(
                line_id=str(uuid.uuid4()),
                score_run_id="",
                category=rule.category,
                rule_id=rule.id,
                points=rule.points,
                rationale=rationale,
                evidence_ids=cited,
            )
        )
    return items
