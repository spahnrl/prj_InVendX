from __future__ import annotations

from invendx.models.evidence import EvidenceRecord
from invendx.pipeline.evidence_fingerprint import (
    assign_dedupe_hashes,
    content_fingerprint_hex,
    content_fingerprint_key,
)


def test_fingerprint_stable_normalization() -> None:
    a = content_fingerprint_hex("v1", "t", "HTTPS://X.COM/a ", "  Hello  ", "a,b")
    b = content_fingerprint_hex("v1", "t", "https://x.com/a", "hello", "a,b")
    assert a == b


def test_fingerprint_differs_by_claim() -> None:
    a = content_fingerprint_hex("v1", "t", "https://x", "one", "")
    b = content_fingerprint_hex("v1", "t", "https://x", "two", "")
    assert a != b


def test_assign_dedupe_hashes() -> None:
    r = EvidenceRecord(
        evidence_id="e1",
        vendor_id="v",
        vendor_name="V",
        run_id="r",
        source_type="official_site",
        source_url="https://x",
        evidence_type="page_crawl",
        claim_text="c",
        confidence="high",
        parser_version="1",
        collected_at="2026-01-01T00:00:00+00:00",
    )
    out = assign_dedupe_hashes([r])
    assert out[0].dedupe_hash
    assert out[0].dedupe_hash == content_fingerprint_hex("v", "page_crawl", "https://x", "c", "")


def test_fingerprint_key_readable() -> None:
    k = content_fingerprint_key("v", "absence_signal", "https://x/", "claim", "t")
    assert "absence_signal" in k
