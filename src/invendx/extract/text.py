from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_meta(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.find("title")
    title = title_el.get_text(strip=True) if title_el else None
    desc = None
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        desc = og["content"].strip()
    else:
        m = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
        if m and m.get("content"):
            desc = m["content"].strip()
    pub = None
    for prop in ("article:published_time", "og:updated_time", "date"):
        node = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if node and node.get("content"):
            pub = node["content"].strip()
            break
    return {"title": title, "description": desc, "published_hint": pub}


def parse_date_loose(value: str | None) -> str | None:
    if not value:
        return None
    from dateutil import parser as date_parser

    try:
        dt = date_parser.parse(value, fuzzy=True)
        return dt.date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def iso_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()
