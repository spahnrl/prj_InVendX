from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScoreRuleSpec(BaseModel):
    id: str
    category: str
    points: float
    match: dict[str, Any] = Field(default_factory=dict)
    max_citations: int = 5


class ScoreRulesConfig(BaseModel):
    ruleset_version: str
    rules: list[ScoreRuleSpec] = Field(default_factory=list)


class ScoreLineItem(BaseModel):
    line_id: str
    score_run_id: str
    category: str
    rule_id: str
    points: float
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
