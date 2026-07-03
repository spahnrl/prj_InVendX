"""www ↔ apex host equivalence for same-site crawl (narrow; no arbitrary subdomains)."""

from __future__ import annotations


def normalize_www_apex_netloc(netloc: str) -> str:
    """Map ``www.example.com`` and ``example.com`` to the key ``example.com``.

    Other hosts (e.g. ``info.example.com``) are unchanged except lowercased.
    """
    h = (netloc or "").strip().lower()
    if h.startswith("www."):
        return h[4:]
    return h


def netloc_same_www_apex(a: str, b: str) -> bool:
    """True only when ``a`` and ``b`` are identical or www/apex variants of the same host."""
    return normalize_www_apex_netloc(a) == normalize_www_apex_netloc(b)
