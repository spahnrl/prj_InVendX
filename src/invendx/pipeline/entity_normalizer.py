from __future__ import annotations

from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from invendx.models.evidence import EvidenceRecord


class EntityNormalizer:
    """Minimal alias-based normalization; low-confidence strings left unchanged."""

    def __init__(self, alias_map: dict[str, str]) -> None:
        self._alias_map = {k.lower(): v for k, v in alias_map.items()}
        self._choices = list({v for v in self._alias_map.values()})

    @classmethod
    def from_yaml(cls, path: str | Path) -> EntityNormalizer:
        p = Path(path)
        if not p.exists():
            return cls({})
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        aliases = data.get("aliases") or {}
        flat: dict[str, str] = {}
        for canonical, vals in aliases.items():
            if isinstance(vals, list):
                for v in vals:
                    flat[str(v)] = str(canonical)
        return cls(flat)

    def normalize_token(self, raw: str | None, threshold: int = 90) -> str | None:
        if not raw:
            return raw
        key = raw.strip()
        low = key.lower()
        if low in self._alias_map:
            return self._alias_map[low]
        if not self._choices:
            return key
        match = process.extractOne(key, self._choices, scorer=fuzz.WRatio)
        if match and match[1] >= threshold:
            return match[0]
        return key

    def normalize_evidence_entities(self, records: list[EvidenceRecord]) -> list[EvidenceRecord]:
        out: list[EvidenceRecord] = []
        for r in records:
            e1 = self.normalize_token(r.entity_1)
            e2 = self.normalize_token(r.entity_2)
            out.append(r.model_copy(update={"entity_1": e1, "entity_2": e2}))
        return out
