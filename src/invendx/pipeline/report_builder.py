from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from invendx.storage import evidence_repo, vendor_repo


def export_evidence_csv(conn: sqlite3.Connection, vendor_id: str, out_path: Path) -> Path:
    rows = evidence_repo.list_evidence_for_vendor(conn, vendor_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return out_path
    fieldnames = list(rows[0].model_dump().keys())
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r.model_dump())
    return out_path


def export_vendor_markdown(conn: sqlite3.Connection, vendor_id: str, out_path: Path) -> Path:
    v = vendor_repo.get_vendor_by_id(conn, vendor_id)
    ev = evidence_repo.list_evidence_for_vendor(conn, vendor_id)
    cur = conn.cursor()
    cur.execute("SELECT * FROM vendor_summaries WHERE vendor_id = ?", (vendor_id,))
    srow = cur.fetchone()

    lines = [
        f"# {v.canonical_name}",
        "",
        f"- **Domain**: {v.primary_domain}",
        f"- **Segment**: {v.primary_segment or 'n/a'}",
        "",
    ]
    if srow:
        d = dict(srow)
        lines.extend(
            [
                "## Summary",
                "",
                f"- **Sources (distinct URLs)**: {d.get('source_count')}",
                f"- **Evidence rows**: {d.get('evidence_count')}",
                f"- **Last evidence at**: {d.get('last_evidence_at')}",
                f"- **Confidence rollup**: {d.get('confidence_rollup')}",
                f"- **Profile hints**: `{d.get('profile_metrics_json')}`",
                "",
            ]
        )
    lines.append("## Recent evidence")
    lines.append("")
    for e in ev[-25:]:
        lines.append(f"- `{e.evidence_type}` — {e.claim_text[:200]} ([source]({e.source_url}))")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def export_summaries_json(conn: sqlite3.Connection, out_path: Path) -> Path:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            v.vendor_id,
            v.canonical_name,
            v.primary_segment,
            s.source_count,
            s.evidence_count,
            s.last_evidence_at,
            s.confidence_rollup,
            s.profile_metrics_json,
            s.updated_at AS summary_updated_at
        FROM vendors v
        LEFT JOIN vendor_summaries s ON s.vendor_id = v.vendor_id
        ORDER BY v.canonical_name
        """
    )
    cols = [c[0] for c in cur.description]
    data = [dict(zip(cols, row)) for row in cur.fetchall()]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path
