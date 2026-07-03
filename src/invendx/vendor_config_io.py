"""Read/write helpers for config/vendors.yaml (shared by UI and usable by CLI extensions)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from invendx.models.vendor import VendorSeed


def normalize_primary_domain(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    lower = s.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        try:
            p = urlparse(s)
            host = (p.netloc or p.path or "").strip()
        except ValueError:
            host = s
    else:
        host = s
    host = host.split("/")[0].split(":")[0].strip()
    return host.removeprefix("www.")


def parse_alias_list(s: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[\n,]+", s or ""):
        t = part.strip()
        if t:
            out.append(t)
    return out


def parse_url_lines(blob: str) -> list[str]:
    urls: list[str] = []
    for line in (blob or "").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        urls.append(t)
    return urls


def load_vendors_yaml_doc(path: Path) -> dict:
    if not path.exists():
        return {"vendors": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Vendors YAML root must be a mapping")
    if "vendors" not in data:
        data["vendors"] = []
    if not isinstance(data["vendors"], list):
        raise ValueError("vendors key must be a list")
    return data


def save_vendors_yaml_doc(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        data,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    path.write_text(text, encoding="utf-8")


def append_vendor_seed(path: Path, seed: VendorSeed) -> None:
    """Append a validated seed; raises ValueError if canonical_name already exists in the file."""
    data = load_vendors_yaml_doc(path)
    vendors: list = data["vendors"]
    names = {str(v.get("canonical_name", "")).strip() for v in vendors if isinstance(v, dict)}
    if seed.canonical_name.strip() in names:
        raise ValueError(f"Vendor already in YAML: {seed.canonical_name!r}")
    vendors.append(seed.model_dump(mode="python"))
    save_vendors_yaml_doc(path, data)
