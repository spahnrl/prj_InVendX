from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from invendx.models.evidence import EvidenceRecord
from invendx.pipeline.coverage_status import DEFAULT_THRESHOLDS, classify_coverage
from invendx.pipeline.evidence_views import recent_evidence_lines_for_report
from invendx.storage import evidence_repo, score_repo, vendor_repo
from invendx.storage.coverage_diag_repo import fetch_coverage_rows

_SCORE_CATEGORY_LABELS: dict[str, str] = {
    "TradingDataDepth": "Trading / data depth",
    "IntegrationCapability": "Integration capability",
    "DeveloperExperience": "Developer experience",
    "EngineeringSignal": "Engineering signal",
}

_PROFILE_HINT_LABELS: dict[str, str] = {
    "aum_trillions_hint": "AUM (trillions, hint)",
    "advisors_or_institutions_hint": "Advisors / institutions (hint)",
    "accounts_millions_hint": "Accounts (millions, hint)",
    "ria_hint": "RIA firms (count, hint)",
}


def _category_display(category: str) -> str:
    return _SCORE_CATEGORY_LABELS.get(category, category)


def _format_iso_date_only(val: object | None) -> str:
    if val is None:
        return "n/a"
    s = str(val).strip()
    if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
        return s[:10]
    return s[:10] if len(s) >= 10 else s


def _summary_profile_hints_lines(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return ["- **Profile hints**: (none extracted)"]
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return ["- **Profile hints** (unparsed JSON):", "", f"  ```text\n{raw}\n  ```"]
    if not isinstance(d, dict) or not d:
        return ["- **Profile hints**: (none extracted)"]
    out: list[str] = [
        "- **Profile hints** (pattern extracts from evidence text — not validated financials):",
    ]
    for key, label in _PROFILE_HINT_LABELS.items():
        v = d.get(key)
        if v is not None and str(v).strip():
            out.append(f"  - **{label}**: {v}")
    for key in sorted(k for k in d if k not in _PROFILE_HINT_LABELS):
        v = d.get(key)
        if v is not None and str(v).strip():
            out.append(f"  - **{key}**: {v}")
    if len(out) == 1:
        out = ["- **Profile hints**: (none extracted)"]
    return out


def _report_reader_guide_lines() -> list[str]:
    """Explains what each report section contains and how to interpret it."""
    return [
        "## How to read this report",
        "",
        "This file is **machine-generated** from your InVendX database: public pages you ingested (crawl, seeds, manual capture) are stored as **evidence** rows; optional **scoring** applies YAML rules to those rows. It is a research aid, not a vendor endorsement or financial verification.",
        "",
        "- **Summary** (when present) — Roll-up **counts** (distinct source URLs vs evidence rows), **when** evidence was last stored, a **confidence rollup** (average of parser labels high/medium/low—not statistical certainty), and **profile hints** (pattern matches in text, e.g. scale language; **not validated** metrics).",
        "- **At a glance** — Short **factual bullets** computed from the summary and latest score run: volume of stored research, which scorecard **themes** gained the most total points, and a coarse read on **developer**-related signals in evidence.",
        "- **Latest scorecard** (when present) — **Rule-based points** tied to specific evidence IDs. Points mean “this rule matched these rows,” not “good/bad vendor.” Read the cited sources and rationales; use `--all-evidence` when scoring if you intend every stored row to be in scope.",
        "- **Recent evidence** — **Grouped excerpts** of captured signals; identical developer-portal claims on many URLs are **folded** into one bullet with a page count. Optional snippets skip text that mostly repeats the title or claim.",
        "- **Distinct source URLs** — Alphabetical checklist of **every** unique page URL referenced by evidence (cap in the report; use CSV export for unlimited).",
        "",
    ]


def _distinct_sources_appendix(ev: list[EvidenceRecord], *, max_list: int = 100) -> list[str]:
    urls = sorted({e.source_url for e in ev if (e.source_url or "").strip()})
    lines = [
        "## Distinct source URLs",
        "",
        f"*One row per unique `source_url` in stored evidence (**{len(urls)}** total). Links are repeated for convenience. For the full URL list in a spreadsheet, run* `invendx export evidence --vendor …`*.*",
        "",
    ]
    show = urls[:max_list]
    for u in show:
        lines.append(f"- [{u}]({u})")
    rest = len(urls) - len(show)
    if rest > 0:
        lines.append(f"- … **{rest}** more URLs not shown here (export evidence CSV).")
    lines.append("")
    return lines


def _parse_evidence_ids_json(raw: str | None) -> list[str]:
    try:
        ids = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(ids, list):
        return []
    return [str(x) for x in ids]


def _takeaways_lines(
    ev: list[EvidenceRecord],
    score_items: list[dict] | None,
    summary_row: dict | None,
) -> list[str]:
    lines = [
        "## At a glance",
        "",
        "*Quick, factual highlights from your stored summary and latest score run—use **Summary** for raw numbers and **Recent evidence** to verify claims at the URL level.*",
        "",
    ]
    bullets: list[str] = []
    if summary_row:
        ec = summary_row.get("evidence_count")
        sc = summary_row.get("source_count")
        if ec is not None:
            tail = f" across **{sc}** distinct source URLs" if sc is not None else ""
            bullets.append(f"- **Evidence stored**: **{ec}** row(s){tail}.")
    if score_items:
        by_cat: dict[str, float] = {}
        for it in score_items:
            c = str(it.get("category") or "")
            by_cat[c] = by_cat.get(c, 0.0) + float(it.get("points") or 0)
        top = sorted(by_cat.items(), key=lambda x: (-abs(x[1]), x[0]))[:3]
        if top:
            parts = [f"{_category_display(c)} ({p:+.1f})" for c, p in top]
            bullets.append(
                "- **Strongest scorecard categories (by total points, latest run)**: "
                + "; ".join(parts)
                + "."
            )
    has_dev = any(e.evidence_type == "dev_portal_signal" for e in ev)
    has_abs = any(
        e.evidence_type == "absence_signal" and "developer_docs" in (e.tags or "").lower() for e in ev
    )
    if has_dev or has_abs:
        if has_dev and not has_abs:
            bullets.append(
                "- **Developer signals**: developer-portal style evidence present; "
                "no developer-docs *absence* row in stored evidence."
            )
        elif has_abs and not has_dev:
            bullets.append(
                "- **Developer signals**: developer-docs *absence* evidence present; "
                "no developer-portal signal row in stored evidence."
            )
        else:
            bullets.append(
                "- **Developer signals**: both portal-style and absence-style developer evidence "
                "exist in the store (scoring may suppress conflicting absence lines)."
            )
    if not bullets:
        bullets.append(
            "- Ingest evidence or run scoring to populate takeaways; summary row may be missing."
        )
    lines.extend(bullets)
    lines.append("")
    return lines


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
    evidence_by_id = {e.evidence_id: e for e in ev if e.evidence_id}
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
    lines.extend(_report_reader_guide_lines())
    summary_dict: dict | None = None
    if srow:
        summary_dict = dict(srow)
        d = summary_dict
        cr = d.get("confidence_rollup")
        lines.extend(
            [
                "## Summary",
                "",
                "*Aggregates recomputed from all evidence rows for this vendor (after ingest or summary refresh). Use this block for coverage and freshness; interpret hints as clues only.*",
                "",
                f"- **Sources (distinct URLs)**: {d.get('source_count')}",
                f"- **Evidence rows**: {d.get('evidence_count')}",
                f"- **Last evidence (date)**: {_format_iso_date_only(d.get('last_evidence_at'))}",
                f"- **Confidence rollup**: {cr} — mean of per-row labels "
                f"(`high`→1.0, `medium`→0.6, `low`→0.3, other→0.5) across all evidence for this vendor.",
                "",
            ]
        )
        lines.extend(_summary_profile_hints_lines(d.get("profile_metrics_json")))
        lines.append("")

    run_meta = score_repo.get_latest_score_run(conn, vendor_id)
    score_items: list[dict] | None = None
    if run_meta:
        score_items = score_repo.list_line_items_for_run(conn, run_meta["score_run_id"])

    lines.extend(_takeaways_lines(ev, score_items, summary_dict))

    if run_meta and score_items is not None:
        items = score_items
        lines.extend(
            [
                "## Latest scorecard",
                "",
                "*Each line is one **rule** from your ruleset: points add or subtract when matching evidence was found. **Why** explains how many rows matched; indented bullets quote the cited evidence and link to the live page.*",
                "",
                "Reflects the most recent `invendx score` or `run --score` (default input: **latest ingest run** only; use `--all-evidence` on those commands to score everything).",
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
            cat = str(it.get("category") or "")
            cat_d = _category_display(cat)
            rationale = (it.get("rationale") or "").strip()
            lines.append(f"- **{cat_d}** — rule `{rid}` — **{pts}** pt")
            if rationale:
                lines.append(f"  - *Why*: {rationale}")
            eids = _parse_evidence_ids_json(it.get("evidence_ids_json"))
            preview_cap = 8
            for eid in eids[:preview_cap]:
                rec = evidence_by_id.get(eid)
                if rec:
                    claim = rec.claim_text[:120] + ("…" if len(rec.claim_text) > 120 else "")
                    lines.append(f"  - `{eid}`: {claim} — [source]({rec.source_url})")
                else:
                    lines.append(f"  - `{eid}`: (not found in current evidence list)")
            if len(eids) > preview_cap:
                lines.append(f"  - … and **{len(eids) - preview_cap}** more citation(s).")
        lines.append("")
    lines.extend(
        [
            "## Recent evidence",
            "",
            "*Concrete signals pulled from crawled or manually captured pages. Subheadings group similar **evidence types**. Repeated **developer-portal** claims on many case-study URLs collapse into **one bullet** with a distinct-page count; other types keep one bullet per page unless the same URL+claim repeats. Snippets favor longer excerpts when they add meaning beyond the title.*",
            "",
        ]
    )
    latest_rid = evidence_repo.get_latest_run_id_for_vendor(conn, vendor_id)
    recent_lines, recent_caption = recent_evidence_lines_for_report(
        ev, latest_run_id=latest_rid, max_lines=25, grouped=True
    )
    lines.append(f"*{recent_caption}*")
    lines.append("")
    lines.extend(recent_lines)
    lines.append("")
    lines.extend(_distinct_sources_appendix(ev))
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


_COVERAGE_CSV_FIELDS = [
    "vendor_id",
    "canonical_name",
    "primary_domain",
    "primary_segment",
    "ingest_run_count",
    "latest_ingest_run_id",
    "latest_ingest_at",
    "evidence_count",
    "distinct_source_url_count",
    "latest_evidence_at",
    "summary_row_present",
    "summary_updated_at",
    "confidence_rollup",
    "profile_metrics_present",
    "latest_score_run_present",
    "latest_score_run_id",
    "latest_score_created_at",
    "latest_score_line_item_count",
    "coverage_status",
    "coverage_notes",
]


def export_coverage_csv(conn: sqlite3.Connection, out_path: Path) -> Path:
    """One row per vendor: ingest/evidence/summary/score aggregates plus coverage_status."""
    raw = fetch_coverage_rows(conn)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_COVERAGE_CSV_FIELDS)
        w.writeheader()
        for row in raw:
            status, notes = classify_coverage(row, DEFAULT_THRESHOLDS)
            out_row: dict[str, str | int | float] = {}
            for key in _COVERAGE_CSV_FIELDS:
                if key == "coverage_status":
                    out_row[key] = status
                elif key == "coverage_notes":
                    out_row[key] = notes
                else:
                    val = row.get(key)
                    if val is None:
                        out_row[key] = ""
                    elif isinstance(val, bool):
                        out_row[key] = "true" if val else "false"
                    else:
                        out_row[key] = val
            w.writerow(out_row)
    return out_path
