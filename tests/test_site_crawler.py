"""Site crawl: www/apex link following and telemetry."""

from __future__ import annotations

from invendx.http.client import FetchResult
from invendx.models.discovery import DiscoveredTarget
from invendx.pipeline.site_crawler import CrawlConfig, SiteCrawler


class _AllowAllRobots:
    def allowed(self, url: str) -> bool:
        return True


class _ChainHttp:
    """Return scripted HTML per requested URL."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages

    def fetch(self, url: str) -> FetchResult:
        html = self._pages.get(url, "")
        ok = url in self._pages
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200 if ok else 404,
            content_type="text/html",
            text=html,
            ok=ok,
        )


def test_crawler_follows_www_links_when_seed_is_apex() -> None:
    seed = "https://example.com/"
    child = "https://www.example.com/child"
    pages_map = {
        seed: f'<html><body><a href="{child}">x</a></body></html>',
        child: "<html><body>child</body></html>",
    }
    crawler = SiteCrawler(_ChainHttp(pages_map), _AllowAllRobots(), CrawlConfig(max_pages=5, delay_s=0))
    out = crawler.crawl_from_targets([DiscoveredTarget(url=seed, kind="homepage", priority=1)])
    assert {p.final_url for p in out} == {seed, child}
    assert crawler.last_telemetry.pages_stored == 2


def test_crawler_telemetry_increments_non_html() -> None:
    pdf_url = "https://example.com/doc.pdf"
    seed = "https://example.com/"
    pages_map = {
        seed: f'<html><body><a href="{pdf_url}">x</a></body></html>',
        pdf_url: "%PDF-1.4",
    }

    def fetch(url: str) -> FetchResult:
        if url == seed:
            return FetchResult(
                url=url, final_url=url, status_code=200, content_type="text/html", text=pages_map[seed], ok=True
            )
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content_type="application/pdf",
            text=pages_map[pdf_url],
            ok=True,
        )

    class _Http:
        def fetch(self, url: str) -> FetchResult:
            return fetch(url)

    crawler = SiteCrawler(_Http(), _AllowAllRobots(), CrawlConfig(max_pages=5, max_depth=2, delay_s=0))
    crawler.crawl_from_targets([DiscoveredTarget(url=seed, kind="homepage", priority=1)])
    t = crawler.last_telemetry
    assert t.pages_stored >= 1
    assert t.non_html_skipped >= 1
    assert any(s.get("crawl_reason") == "non_html_skipped" and pdf_url in s.get("url", "") for s in t.skipped_urls)


def test_crawler_telemetry_robots_denied() -> None:
    class _Deny:
        def allowed(self, url: str) -> bool:
            return False

    crawler = SiteCrawler(_ChainHttp({}), _Deny(), CrawlConfig(max_pages=5, delay_s=0))
    crawler.crawl_from_targets([DiscoveredTarget(url="https://example.com/", kind="homepage", priority=1)])
    assert crawler.last_telemetry.robots_denied == 1
    assert crawler.last_telemetry.pages_stored == 0
    assert len(crawler.last_telemetry.skipped_urls) == 1
    assert crawler.last_telemetry.skipped_urls[0]["crawl_reason"] == "robots_denied"
