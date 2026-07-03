"""Pure helpers from operator_app used by Vendor Intelligence Browse / Compare."""

from operator_app import (
    _apply_intel_filters,
    _distinct_primary_segments,
    _filter_by_segments,
    _segment_tokens,
    _sort_portfolio_rows,
)


def test_segment_tokens_splits() -> None:
    assert _segment_tokens("RIA / advisor tech") == {"ria", "advisor tech"}
    assert _segment_tokens("a, b") == {"a", "b"}


def test_filter_by_segments_exact() -> None:
    rows = [
        {"primary_segment": "RIA / advisor tech", "canonical_name": "A"},
        {"primary_segment": "Enterprise", "canonical_name": "B"},
    ]
    assert _filter_by_segments(rows, [], token_mode=False) == rows
    assert len(_filter_by_segments(rows, ["Enterprise"], token_mode=False)) == 1
    assert _filter_by_segments(rows, ["Enterprise"], token_mode=False)[0]["canonical_name"] == "B"


def test_filter_by_segments_token_mode() -> None:
    rows = [
        {"primary_segment": "RIA / advisor tech", "canonical_name": "A"},
        {"primary_segment": "Enterprise", "canonical_name": "B"},
    ]
    out = _filter_by_segments(rows, ["RIA / wealth"], token_mode=True)
    assert [r["canonical_name"] for r in out] == ["A"]


def test_apply_intel_filters_and_sort() -> None:
    rows = [
        {
            "vendor_id": "1",
            "canonical_name": "Zed",
            "primary_segment": "Seg",
            "primary_domain": "z.example",
            "evidence_count": 1,
            "source_count": 1,
            "last_evidence_at": "",
            "confidence_rollup": 0.5,
        },
        {
            "vendor_id": "2",
            "canonical_name": "Amy",
            "primary_segment": "Seg",
            "primary_domain": "a.example",
            "evidence_count": 99,
            "source_count": 2,
            "last_evidence_at": "2026-01-02",
            "confidence_rollup": 0.9,
        },
    ]
    f = _apply_intel_filters(rows, "", ["Seg"], token_mode=False)
    assert len(f) == 2
    s = _sort_portfolio_rows(f, "evidence_desc")
    assert [r["canonical_name"] for r in s] == ["Amy", "Zed"]
    s2 = _sort_portfolio_rows(f, "name_asc")
    assert [r["canonical_name"] for r in s2] == ["Amy", "Zed"]


def test_distinct_primary_segments_sorted() -> None:
    rows = [
        {"primary_segment": "zebra"},
        {"primary_segment": "apple"},
        {"primary_segment": "apple"},
        {"primary_segment": ""},
    ]
    assert _distinct_primary_segments(rows) == ["apple", "zebra"]
