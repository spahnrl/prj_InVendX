"""Discovery path priorities and sitemap URL ranking."""

from __future__ import annotations

from invendx.http.client import FetchResult
from invendx.models.vendor import VendorRecord
from invendx.pipeline.source_discovery import discover_vendor


class _FakeHttp:
    def __init__(self, locs: list[str]) -> None:
        self._locs = locs

    def fetch(self, url: str) -> FetchResult:
        if not url.endswith("sitemap.xml"):
            return FetchResult(
                url=url,
                final_url=url,
                status_code=404,
                content_type="text/plain",
                text="",
                ok=False,
            )
        inner = "".join(f"<loc>{u}</loc>" for u in self._locs)
        body = f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{inner}</urlset>'
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content_type="application/xml",
            text=body,
            ok=True,
        )


def _vendor() -> VendorRecord:
    return VendorRecord(
        vendor_id="v1",
        canonical_name="Snap",
        primary_domain="snap.example",
        primary_segment="x",
    )


def test_seed_paths_products_before_blog() -> None:
    t = discover_vendor(_vendor(), http=_FakeHttp([]), include_sitemap=False)
    by_key = {(x.kind, x.url.rstrip("/")): x.priority for x in t}
    assert by_key[("products", "https://snap.example/products")] < by_key[
        ("blog_index", "https://snap.example/blog")
    ]


def test_products_priority_near_platform() -> None:
    t = discover_vendor(_vendor(), http=_FakeHttp([]), include_sitemap=False)
    pmap = {x.kind: x.priority for x in t}
    assert pmap["products"] == pmap["platform"] + 1
    assert pmap["products"] == pmap["solutions"] + 1


def test_sitemap_includes_www_when_origin_is_apex() -> None:
    locs = ["https://www.snap.example/products/overview"]
    t = discover_vendor(_vendor(), http=_FakeHttp(locs), include_sitemap=True)
    urls = {x.url for x in t if x.kind == "sitemap"}
    assert "https://www.snap.example/products/overview" in urls


def test_sitemap_marketing_paths_downranked() -> None:
    locs = [
        "https://snap.example/api/guide",
        "https://snap.example/blog/launch",
        "https://snap.example/insights/2025",
        "https://snap.example/news/press-kit",
        "https://snap.example/press/q1",
    ]
    t = discover_vendor(_vendor(), http=_FakeHttp(locs), include_sitemap=True)
    by_url = {x.url: x.priority for x in t if x.kind == "sitemap"}
    assert by_url["https://snap.example/api/guide"] == 30
    for u in locs[1:]:
        assert by_url[u] == 48
