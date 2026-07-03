from __future__ import annotations

from pydantic import BaseModel


class EvidenceRecord(BaseModel):
    evidence_id: str = ""
    vendor_id: str
    vendor_name: str
    run_id: str
    source_type: str
    source_url: str
    source_date: str | None = None
    source_title: str | None = None
    evidence_type: str
    product_area: str | None = None
    entity_1: str | None = None
    entity_2: str | None = None
    claim_text: str
    confidence: str = "medium"
    tags: str = ""
    score_impact_category: str | None = None
    raw_text_excerpt: str | None = None
    parser_version: str
    collected_at: str
    dedupe_hash: str | None = None

    def tag_list(self) -> list[str]:
        if not self.tags.strip():
            return []
        return [t.strip() for t in self.tags.split(",") if t.strip()]
