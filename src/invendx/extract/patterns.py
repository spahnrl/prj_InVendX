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


def _parse_count_token(raw: str) -> int | None:
    s = re.sub(r",", "", raw.strip())
    if not s.isdigit():
        return None
    return int(s)


def _ria_count_from_k_suffix(raw: str) -> int | None:
    s = raw.strip().upper().replace(",", "")
    if not s.endswith("K") or len(s) < 2:
        return None
    base = s[:-1]
    if not base.replace(".", "", 1).isdigit():
        return None
    try:
        n = float(base) * 1000
    except ValueError:
        return None
    if n != int(n):
        return int(n)
    return int(n)


def _merge_ria_best(cur: int | None, n: int | None) -> int | None:
    if n is None:
        return cur
    if cur is None or n > cur:
        return n
    return cur


def _ria_hint_from_advisors_phrase(phrase: str) -> int | None:
    """When copy mentions RIAs inside the advisor-scale snippet but RIA-specific regexes missed."""
    if not phrase or not re.search(r"\brias?\b", phrase, re.I):
        return None
    km = re.search(r"\b([\d,]+(?:\.\d+)?)\s*[Kk]\+?\s+(?=\brias?\b)", phrase, re.I)
    if km:
        n = _ria_count_from_k_suffix(km.group(1).replace(",", "") + "K")
        if n is not None:
            return n
    nums: list[int] = []
    for m in re.finditer(r"\b([\d,]+)\b", phrase):
        n = _parse_count_token(m.group(1))
        if n is not None and n > 0:
            nums.append(n)
    if not nums:
        return None
    best = max(nums)
    if len(nums) == 1 and 1900 <= best <= 2100:
        return None
    return best


# AUM: same JSON key as before (`aum_trillions_hint`) so UI/report labels stay stable.
_AUM_PATTERNS = [
    re.compile(r"\$\s*[\d,]+(?:\.\d+)?\s*T\b", re.I),
    re.compile(r"\$\s*[\d,]+(?:\.\d+)?\s*(?:trillion|trn)\b", re.I),
    re.compile(r"\$\s*[\d,]+(?:\.\d+)?\s*B\b", re.I),
    re.compile(r"\$\s*[\d,]+(?:\.\d+)?\s*(?:billion|bn)\b", re.I),
]

# Scale language: avoid "3 advisors" — require ~, over/more than, + suffix, comma-grouped thousands, or 4+ digits.
_ADVISOR_SCALE = r"(?:RIAs?|advisors?|institutions?|registered\s+investment\s+advis(?:e|o)rs?)"
_ADVISOR_PATTERNS = [
    re.compile(rf"~\s*([\d,]+)\+?\s*{_ADVISOR_SCALE}\b", re.I),
    re.compile(rf"(?:over|more than)\s+([\d,]+)\+?\s*{_ADVISOR_SCALE}\b", re.I),
    re.compile(rf"([\d,]+)\+\s*{_ADVISOR_SCALE}\b", re.I),
    re.compile(rf"([\d]{{1,3}}(?:,\d{{3}})+)\+?\s*{_ADVISOR_SCALE}\b", re.I),
    re.compile(rf"(\d{{4,}})\+?\s*{_ADVISOR_SCALE}\b", re.I),
]

_RIA_COUNT_PATTERNS = [
    re.compile(r"(?:~|over|more than)\s+([\d,]+)\+?\s+RIAs?\b", re.I),
    re.compile(r"([\d,]+)\+\s*RIAs?\b", re.I),
    re.compile(r"([\d]{1,3}(?:,\d{3})+)\s*\+?\s+RIAs?\b", re.I),
    re.compile(r"(\d{4,})\s*\+?\s+RIAs?\b", re.I),
    re.compile(r"\brias?\s*[:\-–]\s*([\d,]+)\b", re.I),
    re.compile(r"([\d]{1,3}(?:,\d{3})+|\d{3,})\s*\+?\s+RIA\s+firms\b", re.I),
    re.compile(r"([\d]{1,3}(?:,\d{3})+|\d{3,})\s*\+?\s+independent\s+RIAs?\b", re.I),
    re.compile(
        r"(?:~|over|more than)\s+([\d,]+)\+?\s+registered\s+investment\s+advis(?:e|o)rs?\b",
        re.I,
    ),
    re.compile(
        r"([\d]{1,3}(?:,\d{3})+)\s*\+?\s+registered\s+investment\s+advis(?:e|o)rs?\b",
        re.I,
    ),
]


def extract_profile_metrics(text: str) -> dict[str, Any]:
    """Light heuristics for UI-oriented profile_metrics_json."""
    out: dict[str, Any] = {}
    if not (text or "").strip():
        return out

    for pat in _AUM_PATTERNS:
        m = pat.search(text)
        if m:
            out["aum_trillions_hint"] = m.group(0).strip()
            break

    for pat in _ADVISOR_PATTERNS:
        m = pat.search(text)
        if m:
            out["advisors_or_institutions_hint"] = m.group(0).strip()
            break

    best_ria: int | None = None
    for pat in _RIA_COUNT_PATTERNS:
        for m in pat.finditer(text):
            n = _parse_count_token(m.group(1))
            best_ria = _merge_ria_best(best_ria, n)

    for m in re.finditer(r"\b([\d,]+(?:\.\d+)?)\s*[Kk]\+?\s+RIAs?\b", text, re.I):
        k = _ria_count_from_k_suffix(m.group(1).replace(",", "") + "K")
        best_ria = _merge_ria_best(best_ria, k)

    ah = out.get("advisors_or_institutions_hint")
    if isinstance(ah, str) and ah:
        best_ria = _merge_ria_best(best_ria, _ria_hint_from_advisors_phrase(ah))

    if best_ria is not None:
        out["ria_hint"] = best_ria

    m3 = re.search(r"([\d,]+)\+?\s*(million|m)\s+accounts?", text, re.I)
    if m3:
        out["accounts_millions_hint"] = m3.group(0).strip()
    return out
