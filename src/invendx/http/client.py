from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

DEFAULT_UA = (
    "InVendX/0.1 (+https://example.local; vendor research bot; respects robots.txt)"
)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    text: str
    ok: bool


class HttpClient:
    def __init__(
        self,
        timeout_s: float = 25.0,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self._timeout = timeout_s
        self._headers = {"User-Agent": user_agent, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        reraise=True,
    )
    def fetch(self, url: str) -> FetchResult:
        with httpx.Client(timeout=self._timeout, follow_redirects=True, headers=self._headers) as client:
            resp = client.get(url)
        ct = resp.headers.get("content-type", "").split(";")[0].strip()
        ok = resp.status_code < 400
        if not ok:
            logger.warning("fetch status %s for %s", resp.status_code, url)
        return FetchResult(
            url=url,
            final_url=str(resp.url),
            status_code=resp.status_code,
            content_type=ct,
            text=resp.text if resp.text else "",
            ok=ok,
        )
