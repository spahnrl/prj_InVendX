"""Stable content fingerprints for evidence dedupe (dedupe_hash column)."""

from __future__ import annotations

import hashlib

from invendx.models.evidence import EvidenceRecord


def _norm(s: str | None) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split()).lower()


def content_fingerprint_key(
    vendor_id: str,
    evidence_type: str,
    source_url: str,
    claim_text: str,
    tags: str = "",
) -> str:
    """Normalized logical key before hashing (for tests / debugging)."""
    parts = (
        _norm(vendor_id),
        _norm(evidence_type),
        _norm(source_url),
        _norm(claim_text),
        _norm(tags),
    )
    return "|".join(parts)


def content_fingerprint_hex(
    vendor_id: str,
    evidence_type: str,
    source_url: str,
    claim_text: str,
    tags: str = "",
) -> str:
    raw = content_fingerprint_key(vendor_id, evidence_type, source_url, claim_text, tags)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def assign_dedupe_hashes(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Return copies with dedupe_hash set from normalized vendor + type + url + claim + tags."""
    out: list[EvidenceRecord] = []
    for r in records:
        h = content_fingerprint_hex(
            r.vendor_id,
            r.evidence_type,
            r.source_url,
            r.claim_text,
            r.tags or "",
        )
        out.append(r.model_copy(update={"dedupe_hash": h}))
    return out
