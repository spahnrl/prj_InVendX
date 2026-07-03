from __future__ import annotations

from pathlib import Path

import pytest

from invendx.models.vendor import VendorSeed
from invendx import vendor_config_io as vci


def test_normalize_primary_domain() -> None:
    assert vci.normalize_primary_domain("Example.COM") == "Example.COM"
    assert vci.normalize_primary_domain("https://www.foo.com/bar") == "foo.com"
    assert vci.normalize_primary_domain("") == ""


def test_parse_alias_list() -> None:
    assert vci.parse_alias_list("a, b\nc") == ["a", "b", "c"]


def test_parse_url_lines_skips_comments() -> None:
    assert vci.parse_url_lines(" https://x.com \n# skip\nhttps://y.com") == [
        "https://x.com",
        "https://y.com",
    ]


def test_append_vendor_seed_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "vendors.yaml"
    p.write_text("vendors: []\n", encoding="utf-8")
    seed = VendorSeed(
        canonical_name="Acme",
        primary_domain="acme.com",
        primary_segment="Test",
        aliases=["A"],
        seed_urls={"press": ["https://acme.com/news"]},
        github_org=None,
    )
    vci.append_vendor_seed(p, seed)
    data = vci.load_vendors_yaml_doc(p)
    assert len(data["vendors"]) == 1
    assert data["vendors"][0]["canonical_name"] == "Acme"
    loaded = VendorSeed.model_validate(data["vendors"][0])
    assert loaded.primary_domain == "acme.com"

    with pytest.raises(ValueError, match="already in YAML"):
        vci.append_vendor_seed(p, seed)
