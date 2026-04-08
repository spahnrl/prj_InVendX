from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from invendx.storage import evidence_repo, score_repo, vendor_repo


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
    run_meta = score_repo.get_latest_score_run(conn, vendor_id)
    if run_meta:
        items = score_repo.list_line_items_for_run(conn, run_meta["score_run_id"])
        lines.extend(
            [
                "## Latest scorecard",
                "",
                f"- **Score run**: `{run_meta['score_run_id']}`",
                f"- **Ruleset**: {run_meta.get('ruleset_version')}",
                f"- **Created**: {run_meta.get('created_at')}",
                "",
            ]
        )
        for it in items:
            pts = it.get("points")
            rid = it.get("rule_id")
            cat = it.get("category")
            ev_ids = it.get("evidence_ids_json") or "[]"
            lines.append(f"- **{cat}** / `{rid}` — points **{pts}** — evidence IDs: `{ev_ids}`")
        lines.append("")
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


def export_scorecard_csv(conn: sqlite3.Connection, vendor_id: str, out_path: Path) -> Path:
    """Export latest score run and its line items as one flat CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_meta = score_repo.get_latest_score_run(conn, vendor_id)
    fieldnames = [
        "score_run_id",
        "ruleset_version",
        "score_run_created_at",
        "line_id",
        "category",
        "rule_id",
        "points",
        "rationale",
        "evidence_ids_json",
    ]
    rows_out: list[dict[str, str | float | None]] = []
    if not run_meta:
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
        return out_path
    items = score_repo.list_line_items_for_run(conn, run_meta["score_run_id"])
    for it in items:
        rows_out.append(
            {
                "score_run_id": run_meta["score_run_id"],
                "ruleset_version": run_meta.get("ruleset_version"),
                "score_run_created_at": run_meta.get("created_at"),
                "line_id": it.get("line_id"),
                "category": it.get("category"),
                "rule_id": it.get("rule_id"),
                "points": it.get("points"),
                "rationale": it.get("rationale"),
                "evidence_ids_json": it.get("evidence_ids_json"),
            }
        )
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)
    return out_path
