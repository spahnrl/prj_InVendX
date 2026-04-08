from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VendorSeed(BaseModel):
    """Row from config/vendors.yaml before DB assignment."""

    canonical_name: str
    primary_domain: str
    aliases: list[str] = Field(default_factory=list)
    seed_urls: dict[str, list[str]] = Field(default_factory=dict)
    primary_segment: str = ""
    github_org: str | None = None


class VendorRecord(BaseModel):
    """Vendor as stored in SQLite."""

    vendor_id: str
    canonical_name: str
    primary_domain: str
    aliases: list[str] = Field(default_factory=list)
    seed_urls: dict[str, list[str]] = Field(default_factory=dict)
    primary_segment: str = ""
    github_org: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def seed_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "primary_domain": self.primary_domain,
            "aliases": self.aliases,
            "seed_urls": self.seed_urls,
            "primary_segment": self.primary_segment,
            "github_org": self.github_org,
        }
