"""www ↔ apex host equivalence (narrow)."""

from __future__ import annotations

from invendx.pipeline.site_host_equiv import netloc_same_www_apex, normalize_www_apex_netloc


def test_normalize_strips_single_www_prefix() -> None:
    assert normalize_www_apex_netloc("WWW.EXAMPLE.COM") == "example.com"
    assert normalize_www_apex_netloc("example.com") == "example.com"


def test_subdomain_not_merged_with_apex() -> None:
    assert not netloc_same_www_apex("info.example.com", "example.com")
    assert not netloc_same_www_apex("example.com", "api.example.com")


def test_www_and_apex_equivalent() -> None:
    assert netloc_same_www_apex("www.crd.com", "crd.com")
    assert netloc_same_www_apex("crd.com", "www.crd.com")

