from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from invendx.http.client import HttpClient
from invendx.models.discovery import DiscoveredTarget
from invendx.models.vendor import VendorRecord
from invendx.pipeline.site_host_equiv import netloc_same_www_apex

logger = logging.getLogger(__name__)


def _origin_for_vendor(v: VendorRecord) -> str:
    d = v.primary_domain.strip().lower().rstrip("/")
    if d.startswith("http://") or d.startswith("https://"):
        parsed = urlparse(d)
        return f"{parsed.scheme}://{parsed.netloc}"
    return f"https://{d}"


def _prioritize(targets: list[DiscoveredTarget]) -> list[DiscoveredTarget]:
    return sorted(targets, key=lambda t: (t.priority, t.url))


def _sitemap_priority(url: str) -> int:
    """Lower numbers crawl first; marketing/blog trees are heavily down-ranked."""
    path = (urlparse(url).path or "/").lower()
    for prefix in ("/blog", "/insights", "/news", "/press"):
        if path == prefix or path.startswith(prefix + "/"):
            return 48
    return 30


def discover_vendor(
    vendor: VendorRecord,
    http: HttpClient | None = None,
    include_sitemap: bool = True,
) -> list[DiscoveredTarget]:
    """Return typed URL targets from seed domain + YAML seed_urls."""
    http = http or HttpClient()
    origin = _origin_for_vendor(vendor)
    parsed_o = urlparse(origin)
    netloc = parsed_o.netloc

    targets: list[DiscoveredTarget] = []
    seen: set[str] = set()

    def add(url: str, kind: str, priority: int, notes: str = "") -> None:
        url = url.strip()
        if not url or url in seen:
            return
        seen.add(url)
        targets.append(DiscoveredTarget(url=url, kind=kind, priority=priority, notes=notes))

    add(origin + "/", "homepage", 1, "root")
    paths = [
        ("/news", "news_index", 10),
        ("/press", "press_index", 10),
        ("/newsroom", "newsroom", 10),
        ("/blog", "blog_index", 28),
        ("/insights", "insights", 28),
        ("/resources", "resources", 28),
        ("/about", "about", 20),
        ("/company", "company", 25),
        ("/careers", "careers", 15),
        ("/jobs", "jobs", 15),
        ("/careers/jobs", "careers_jobs", 16),
        ("/developers", "developers", 12),
        ("/docs", "docs", 12),
        ("/documentation", "documentation", 12),
        ("/api", "api_landing", 12),
        ("/platform", "platform", 14),
        ("/solutions", "solutions", 14),
        ("/products", "products", 15),
    ]
    for path, kind, pri in paths:
        add(urljoin(origin + "/", path.lstrip("/")), kind, pri)

    for category, urls in (vendor.seed_urls or {}).items():
        for u in urls:
            add(u, f"seed:{category}", 5, category)

    if include_sitemap:
        sm_url = urljoin(origin + "/", "sitemap.xml")
        try:
            res = http.fetch(sm_url)
            if res.ok and "xml" in res.content_type.lower():
                soup = BeautifulSoup(res.text, "xml")
                for loc in soup.find_all("loc"):
                    u = loc.get_text(strip=True)
                    if netloc_same_www_apex(urlparse(u).netloc, netloc):
                        add(u, "sitemap", _sitemap_priority(u), "sitemap.xml")
        except Exception as e:  # noqa: BLE001
            logger.debug("sitemap skip %s: %s", sm_url, e)

    return _prioritize(targets)
