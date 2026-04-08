from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

from invendx.models.evidence import EvidenceRecord
from invendx.models.vendor import VendorRecord

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_github_org(
    vendor: VendorRecord,
    org: str,
    run_id: str,
    parser_version: str,
    max_repos: int = 15,
) -> list[EvidenceRecord]:
    load_dotenv()
    token = os.environ.get("GITHUB_TOKEN")
    headers: dict[str, str] = {"Accept": "application/vnd.github+json", "User-Agent": "InVendX/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/orgs/{org}/repos?per_page={max_repos}&sort=updated"
    records: list[EvidenceRecord] = []
    try:
        with httpx.Client(timeout=30.0, headers=headers) as client:
            resp = client.get(url)
    except Exception as e:  # noqa: BLE001
        logger.warning("github org fetch failed %s: %s", org, e)
        return records

    if resp.status_code != 200:
        logger.warning("github API %s for org %s", resp.status_code, org)
        return records

    repos: list[dict[str, Any]] = resp.json()
    for repo in repos[:max_repos]:
        name = repo.get("full_name") or repo.get("name")
        desc = repo.get("description") or ""
        stars = repo.get("stargazers_count")
        pushed = repo.get("pushed_at")
        html_url = repo.get("html_url") or ""
        claim = f"Public repo {name} (stars={stars}, updated={pushed})"
        records.append(
            EvidenceRecord(
                evidence_id=str(uuid.uuid4()),
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.canonical_name,
                run_id=run_id,
                source_type="github",
                source_url=html_url,
                source_date=(pushed or "")[:10] or None,
                source_title=name,
                evidence_type="repo_metadata",
                entity_1=org,
                entity_2=name,
                claim_text=claim,
                confidence="high",
                tags="github,repo",
                score_impact_category="DeveloperExperience",
                raw_text_excerpt=(desc or "")[:500],
                parser_version=parser_version,
                collected_at=_now(),
            )
        )
    if not records:
        records.append(
            EvidenceRecord(
                evidence_id=str(uuid.uuid4()),
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.canonical_name,
                run_id=run_id,
                source_type="github",
                source_url=f"https://github.com/{org}",
                source_date=None,
                source_title=f"GitHub org {org}",
                evidence_type="absence_signal",
                claim_text="No public repositories returned for org (or API empty).",
                confidence="low",
                tags="github,absence",
                score_impact_category="DeveloperExperience",
                raw_text_excerpt=json.dumps({"org": org, "status": resp.status_code})[:500],
                parser_version=parser_version,
                collected_at=_now(),
            )
        )
    return records
