from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_ARCH_TERMS: list[str] = []


def load_keywords(path: str | Path) -> None:
    global _ARCH_TERMS
    p = Path(path)
    if not p.exists():
        _ARCH_TERMS = _default_terms()
        return
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    terms = data.get("architecture_keywords") or _default_terms()
    _ARCH_TERMS = [str(t).lower() for t in terms]


def _default_terms() -> list[str]:
    return [
        "api",
        "openapi",
        "swagger",
        "sdk",
        "fix",
        "ibor",
        "oems",
        "snowflake",
        "managed data",
        "data platform",
        "real-time",
        "two-way",
        "integration",
        "cloud",
        "postman",
    ]


def match_architecture_keywords(text: str) -> list[str]:
    terms = _ARCH_TERMS or _default_terms()
    low = text.lower()
    found: list[str] = []
    for term in terms:
        if term in low and term not in found:
            found.append(term)
    return found


DOC_PATH_HINTS = (
    "/developers",
    "/developer",
    "/docs",
    "/documentation",
    "/api",
    "openapi",
    "swagger",
    "postman",
)


def find_doc_hints_in_links(links: list[str]) -> list[str]:
    hits: list[str] = []
    for u in links:
        ul = u.lower()
        for h in DOC_PATH_HINTS:
            if h in ul:
                hits.append(u)
                break
    return list(dict.fromkeys(hits))


INTEGRATION_PATTERNS = [
    re.compile(r"integrat(es|ion|ed)\s+with", re.I),
    re.compile(r"partnership", re.I),
    re.compile(r"two-way", re.I),
    re.compile(r"real-time\s+updates?", re.I),
]


def text_suggests_integration(text: str) -> bool:
    return any(p.search(text) for p in INTEGRATION_PATTERNS)


def extract_profile_metrics(text: str) -> dict[str, Any]:
    """Light heuristics for UI-oriented profile_metrics_json."""
    out: dict[str, Any] = {}
    # AUM trillions e.g. $6T, $1.8T
    m = re.search(r"\$\s*([\d.]+)\s*T\b", text, re.I)
    if m:
        out["aum_trillions_hint"] = m.group(0).strip()
    # RIAs / advisors
    m2 = re.search(r"~\s*([\d,]+)\+?\s*(RIAs?|advisors?|institutions?)", text, re.I)
    if m2:
        out["advisors_or_institutions_hint"] = m2.group(0).strip()
    m3 = re.search(r"([\d,]+)\+?\s*(million|m)\s+accounts?", text, re.I)
    if m3:
        out["accounts_millions_hint"] = m3.group(0).strip()
    return out
