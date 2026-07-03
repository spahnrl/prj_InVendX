from __future__ import annotations

from pydantic import BaseModel


class DiscoveredTarget(BaseModel):
    """A URL to fetch with intent metadata."""

    url: str
    kind: str
    priority: int = 100
    notes: str = ""


class PageDocument(BaseModel):
    url: str
    final_url: str
    status_code: int
    content_type: str = ""
    html: str | None = None
    fetched_at: str
