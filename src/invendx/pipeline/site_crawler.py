from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from invendx.http.client import HttpClient
from invendx.http.robots import RobotsPolicy
from invendx.models.discovery import DiscoveredTarget, PageDocument

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CrawlConfig:
    max_pages: int = 40
    max_depth: int = 2
    delay_s: float = 0.75
    same_domain_only: bool = True


class SiteCrawler:
    def __init__(
        self,
        http: HttpClient,
        robots: RobotsPolicy,
        config: CrawlConfig | None = None,
    ) -> None:
        self.http = http
        self.robots = robots
        self.config = config or CrawlConfig()

    def crawl_from_targets(self, seed_targets: list[DiscoveredTarget]) -> list[PageDocument]:
        if not seed_targets:
            return []
        parsed = urlparse(seed_targets[0].url)
        allowed_netloc = parsed.netloc
        queue: list[tuple[str, int]] = []
        seen: set[str] = set()
        pages: list[PageDocument] = []

        for t in seed_targets:
            u, _ = urldefrag(t.url)
            if u not in seen:
                seen.add(u)
                queue.append((u, 0))

        while queue and len(pages) < self.config.max_pages:
            url, depth = queue.pop(0)
            if not self.robots.allowed(url):
                logger.debug("robots disallow %s", url)
                continue
            try:
                res = self.http.fetch(url)
            except Exception as e:  # noqa: BLE001
                logger.warning("fetch failed %s: %s", url, e)
                time.sleep(self.config.delay_s)
                continue

            if not res.ok or "html" not in res.content_type.lower():
                time.sleep(self.config.delay_s)
                continue

            doc = PageDocument(
                url=url,
                final_url=res.final_url,
                status_code=res.status_code,
                content_type=res.content_type,
                html=res.text,
                fetched_at=_now(),
            )
            pages.append(doc)

            if depth < self.config.max_depth:
                for link in _extract_same_domain_links(res.text, res.final_url, allowed_netloc):
                    if link not in seen and len(seen) < self.config.max_pages * 4:
                        seen.add(link)
                        queue.append((link, depth + 1))

            time.sleep(self.config.delay_s)

        return pages


def _extract_same_domain_links(html: str, base_url: str, netloc: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        abs_url = urljoin(base_url, href)
        u, _ = urldefrag(abs_url)
        p = urlparse(u)
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc != netloc:
            continue
        out.append(u)
    return list(dict.fromkeys(out))
