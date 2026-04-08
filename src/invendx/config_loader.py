from __future__ import annotations

from pathlib import Path

import yaml

from invendx.models.vendor import VendorSeed


def load_vendor_seeds(path: str | Path) -> list[VendorSeed]:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raw = data.get("vendors") or []
    return [VendorSeed.model_validate(v) for v in raw]


def load_score_rules(path: str | Path):
    from invendx.models.scoring import ScoreRulesConfig

    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return ScoreRulesConfig.model_validate(data)
