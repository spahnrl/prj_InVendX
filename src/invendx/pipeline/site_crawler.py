from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from invendx.http.client import HttpClient
from invendx.http.robots import RobotsPolicy
from invendx.models.discovery import DiscoveredTarget, PageDocument
from invendx.pipeline.site_host_equiv import netloc_same_www_apex

logger = logging.getLogger(__name__)

# Cap stored skip samples so run JSON notes stay bounded.
_MAX_CRAWL_SKIPPED_URL_SAMPLES = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CrawlConfig:
    max_pages: int = 40
    max_depth: int = 2
    delay_s: float = 0.75
    same_domain_only: bool = True


@dataclass
class CrawlSkipTelemetry:
    """Counts from the last ``crawl_from_targets`` run (skipped URLs + stored pages)."""

    robots_denied: int = 0
    http_not_ok: int = 0
    non_html_skipped: int = 0
    fetch_failed: int = 0
    pages_stored: int = 0
    skipped_urls: list[dict] = field(default_factory=list)

    def record_skip(self, url: str, crawl_reason: str) -> None:
        """Append a skipped URL sample for manual follow-up (bounded list)."""
        if len(self.skipped_urls) >= _MAX_CRAWL_SKIPPED_URL_SAMPLES:
            return
        self.skipped_urls.append({"url": url, "crawl_reason": crawl_reason})


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
        self.last_telemetry = CrawlSkipTelemetry()

    def crawl_from_targets(self, seed_targets: list[DiscoveredTarget]) -> list[PageDocument]:
        tel = CrawlSkipTelemetry()
        self.last_telemetry = tel
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
                tel.robots_denied += 1
                tel.record_skip(url, "robots_denied")
                logger.debug("robots disallow %s", url)
                continue
            try:
                res = self.http.fetch(url)
            except Exception as e:  # noqa: BLE001
                tel.fetch_failed += 1
                tel.record_skip(url, "fetch_failed")
                logger.warning("fetch failed %s: %s", url, e)
                time.sleep(self.config.delay_s)
                continue

            if not res.ok:
                tel.http_not_ok += 1
                tel.record_skip(url, "http_not_ok")
                time.sleep(self.config.delay_s)
                continue

            if "html" not in res.content_type.lower():
                tel.non_html_skipped += 1
                tel.record_skip(url, "non_html_skipped")
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
            tel.pages_stored += 1

            if depth < self.config.max_depth:
                for link in _extract_same_domain_links(res.text, res.final_url, allowed_netloc):
                    if link not in seen and len(seen) < self.config.max_pages * 4:
                        seen.add(link)
                        queue.append((link, depth + 1))

            time.sleep(self.config.delay_s)

        logger.info(
            "crawl telemetry: robots_denied=%s http_not_ok=%s non_html_skipped=%s "
            "fetch_failed=%s pages_stored=%s",
            tel.robots_denied,
            tel.http_not_ok,
            tel.non_html_skipped,
            tel.fetch_failed,
            tel.pages_stored,
        )
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
        if not netloc_same_www_apex(p.netloc, netloc):
            continue
        out.append(u)
    return list(dict.fromkeys(out))
