"""
InVendX Streamlit UI — Vendor Intelligence (analyst) + Admin/Operator (CLI parity).

Run: streamlit run operator_app.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlparse

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from invendx.models.vendor import VendorSeed
from invendx.pipeline import report_builder
from invendx.pipeline.coverage_status import DEFAULT_THRESHOLDS, classify_coverage
from invendx.pipeline.browser_capture import DEFAULT_CDP_URL, run_manual_fetch_subprocess
from invendx.pipeline.manual_intake import (
    REASON_FLAGS,
    SOURCE_TYPES,
    default_instructions_key,
    discard_duplicate_active_intakes_by_url,
    guidance_for_key,
    normalize_source_url,
    parse_crawl_skipped_urls_from_run_notes,
    promote_intake_to_evidence,
    queue_crawl_skipped_urls_for_vendor,
)
from invendx.storage.coverage_diag_repo import fetch_coverage_rows
from invendx.storage.db import connect, init_schema
from invendx.storage import evidence_repo, score_repo, vendor_repo
from invendx.storage import manual_intake_repo
from invendx import vendor_config_io as vendor_yaml

PAGE_TITLE = "InVendX"
DEMO_DB_RELATIVE = Path("demo_data") / "invendx_demo.db"


def _hydrate_demo_db_if_missing(db_path: Path, repo_root: Path) -> bool:
    """Copy the committed demo DB into the active DB path when deployed without local data."""
    if db_path.exists():
        return False
    demo_db = repo_root / DEMO_DB_RELATIVE
    if not demo_db.exists():
        return False
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(demo_db, db_path)
    except OSError as e:
        st.warning(f"Could not load demo database: {e}")
        return False
    return True


def _append_log(msg: str) -> None:
    if "log_lines" not in st.session_state:
        st.session_state.log_lines = []
    st.session_state.log_lines.append(msg.rstrip())


def _run_cli_with_output(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    cmd = [sys.executable, "-m", "invendx.cli", *args]
    _append_log(f"$ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=os.environ.copy(),
    )
    out = proc.stdout or ""
    err = proc.stderr or ""
    if out:
        _append_log(out)
    if err:
        _append_log("[stderr]\n" + err)
    _append_log(f"(exit {proc.returncode})")
    return proc.returncode, out, err


def _run_cli(args: list[str], cwd: Path | None = None) -> int:
    return _run_cli_with_output(args, cwd)[0]


def _parse_run_evidence_count(stdout: str) -> int | None:
    m = re.search(r"stored (\d+) evidence rows", stdout or "")
    return int(m.group(1)) if m else None


def _optional_int(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _optional_float(s: str) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _coerce_ria_hint_cell(raw: object) -> int | str:
    """Normalize profile_metrics `ria_hint` for tables (int or empty)."""
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return ""
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw == int(raw):
        return int(raw)
    if isinstance(raw, str):
        s = raw.strip().replace(",", "")
        if s.isdigit():
            return int(s)
    return ""


def _run_ingest_args(
    vendor: str,
    db: Path,
    config: Path,
    *,
    with_score: bool,
    score_all_evidence: bool,
    max_pages: int | None,
    max_depth: int | None,
    delay: float | None,
) -> list[str]:
    args = [
        "run",
        vendor,
        "--db",
        str(db),
        "--config",
        str(config),
    ]
    if max_pages is not None:
        args.extend(["--max-pages", str(max_pages)])
    if max_depth is not None:
        args.extend(["--max-depth", str(max_depth)])
    if delay is not None:
        args.extend(["--delay", str(delay)])
    if with_score:
        args.append("--score")
        if score_all_evidence:
            args.append("--all-evidence")
    return args


def _load_portfolio_rows(conn) -> list[dict]:
    """Same join as report_builder.export_summaries_json."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            v.vendor_id,
            v.canonical_name,
            v.primary_domain,
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
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _row_for_display_clean(r: dict) -> dict:
    try:
        pm = json.loads(r.get("profile_metrics_json") or "{}")
    except json.JSONDecodeError:
        pm = {}
    return {
        "vendor_id": r["vendor_id"],
        "canonical_name": r["canonical_name"],
        "primary_domain": r["primary_domain"],
        "primary_segment": r.get("primary_segment") or "",
        "source_count": r.get("source_count") if r.get("source_count") is not None else "",
        "evidence_count": r.get("evidence_count") if r.get("evidence_count") is not None else "",
        "last_evidence_at": r.get("last_evidence_at") or "",
        "summary_updated_at": r.get("summary_updated_at") or "",
        "confidence_rollup": r.get("confidence_rollup") if r.get("confidence_rollup") is not None else "",
        "aum_trillions_hint": pm.get("aum_trillions_hint") or "",
        "advisors_or_institutions_hint": pm.get("advisors_or_institutions_hint") or "",
        "accounts_millions_hint": pm.get("accounts_millions_hint") or "",
        "ria_hint": _coerce_ria_hint_cell(pm.get("ria_hint")),
    }


def _filter_portfolio(rows: list[dict], q: str) -> list[dict]:
    q = (q or "").strip().lower()
    if not q:
        return rows
    out = []
    for r in rows:
        hay = " ".join(
            [
                str(r.get("canonical_name") or ""),
                str(r.get("primary_segment") or ""),
                str(r.get("primary_domain") or ""),
            ]
        ).lower()
        if q in hay:
            out.append(r)
    return out


def _segment_tokens(segment: str) -> set[str]:
    s = (segment or "").strip()
    if not s:
        return set()
    parts = re.split(r"[/,]+", s)
    return {p.strip().lower() for p in parts if p.strip()}


def _distinct_primary_segments(rows: list[dict]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for r in rows:
        seg = (r.get("primary_segment") or "").strip()
        if seg and seg not in seen:
            seen.add(seg)
            out.append(seg)
    out.sort(key=str.lower)
    return out


def _filter_by_segments(
    rows: list[dict],
    selected_segments: list[str],
    *,
    token_mode: bool,
) -> list[dict]:
    if not selected_segments:
        return rows
    if not token_mode:
        sel = {s.strip() for s in selected_segments if s.strip()}
        return [r for r in rows if (r.get("primary_segment") or "").strip() in sel]
    tok_union: set[str] = set()
    for s in selected_segments:
        tok_union |= _segment_tokens(s)
    if not tok_union:
        return rows
    return [
        r
        for r in rows
        if _segment_tokens(str(r.get("primary_segment") or "")) & tok_union
    ]


def _apply_intel_filters(
    rows: list[dict],
    search_q: str,
    selected_segments: list[str],
    *,
    token_mode: bool,
) -> list[dict]:
    after_seg = _filter_by_segments(rows, selected_segments, token_mode=token_mode)
    return _filter_portfolio(after_seg, search_q)


_INTEL_SORT_OPTIONS: list[tuple[str, str]] = [
    ("Vendor name (A–Z)", "name_asc"),
    ("Segment (A–Z)", "segment_asc"),
    ("Evidence (high → low)", "evidence_desc"),
    ("Sources (high → low)", "sources_desc"),
    ("Last evidence (newest first)", "last_evidence_desc"),
    ("Confidence (high → low)", "confidence_desc"),
]


def _sort_portfolio_rows(rows: list[dict], sort_key: str) -> list[dict]:
    out = list(rows)
    if sort_key == "name_asc":
        out.sort(key=lambda r: str(r.get("canonical_name") or "").lower())
    elif sort_key == "segment_asc":
        out.sort(
            key=lambda r: (
                str(r.get("primary_segment") or "").lower(),
                str(r.get("canonical_name") or "").lower(),
            )
        )
    elif sort_key == "evidence_desc":

        def ev_k(r: dict) -> tuple:
            v = r.get("evidence_count")
            if v is None or v == "":
                return (1, 0)
            try:
                return (0, -int(v))
            except (TypeError, ValueError):
                return (1, 0)

        out.sort(key=ev_k)
    elif sort_key == "sources_desc":

        def src_k(r: dict) -> tuple:
            v = r.get("source_count")
            if v is None or v == "":
                return (1, 0)
            try:
                return (0, -int(v))
            except (TypeError, ValueError):
                return (1, 0)

        out.sort(key=src_k)
    elif sort_key == "last_evidence_desc":
        out.sort(key=lambda r: str(r.get("last_evidence_at") or ""), reverse=True)
    elif sort_key == "confidence_desc":

        def cf_k(r: dict) -> float:
            v = r.get("confidence_rollup")
            if v is None or v == "":
                return float("-inf")
            try:
                return float(v)
            except (TypeError, ValueError):
                return float("-inf")

        out.sort(key=cf_k, reverse=True)
    else:
        out.sort(key=lambda r: str(r.get("canonical_name") or "").lower())
    return out


def _rows_to_csv_bytes(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    fieldnames = list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fieldnames})
    return buf.getvalue().encode("utf-8")


def _report_executive_summary(md_text: str) -> str:
    """Same on-disk report; trim to title + Summary for a compact analyst view."""
    cut = md_text.find("\n## Latest scorecard")
    if cut == -1:
        cut = md_text.find("\n## Recent evidence")
    if cut != -1:
        return md_text[:cut].strip()
    return md_text.strip()


_GLANCE_PROFILE_MAX = 180


def _analyst_glance_markdown(md_text: str) -> str:
    """Concise analyst blurb: same report facts, tighter labels and one footprint line."""
    block = _report_executive_summary(md_text)
    domain, segment = "", ""
    tail: list[str] = []
    mode: str = "head"
    for line in block.splitlines():
        t = line.strip()
        if t.startswith("# ") and not t.startswith("##"):
            continue
        if t == "## How to read this report":
            mode = "skip_section"
            continue
        if t == "## At a glance":
            mode = "skip_section"
            continue
        if mode == "skip_section":
            if t.startswith("## "):
                if t == "## Summary":
                    mode = "summary"
                elif t in ("## How to read this report", "## At a glance"):
                    mode = "skip_section"
                else:
                    break
            continue
        if t == "## Summary":
            mode = "summary"
            continue
        if t.startswith("## "):
            break
        if mode == "head":
            if t.startswith("- **Domain**"):
                domain = t.split(":", 1)[-1].strip()
            elif t.startswith("- **Segment**"):
                segment = t.split(":", 1)[-1].strip()
        elif mode == "summary":
            if t.startswith("## "):
                break
            if t.startswith("- "):
                s = t
                s = re.sub(r"\*\*Sources \(distinct URLs\)\*\*", "**Sources**", s)
                s = re.sub(r"\*\*Evidence rows\*\*", "**Evidence**", s)
                s = re.sub(r"\*\*Last evidence \(date\)\*\*", "**Last evidence**", s)
                s = re.sub(r"\*\*Last evidence at\*\*", "**Last evidence**", s)
                s = re.sub(r"\*\*Confidence rollup\*\*", "**Confidence**", s)
                if "Profile hints" in s or "profile_metrics_json" in s:
                    if len(s) > _GLANCE_PROFILE_MAX:
                        s = s[: _GLANCE_PROFILE_MAX - 1] + "…"
                tail.append(s)
    out: list[str] = []
    if domain or segment:
        out.append(f"**Footprint:** {domain or '—'} · {segment or '—'}")
    out.extend(tail)
    if out:
        return "\n\n".join(out)
    return block


# Inline placeholder when domain is missing (ImageColumn needs a value).
_ICON_PLACEHOLDER_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32'>"
    "<rect fill='%23ececec' width='32' height='32' rx='6'/>"
    "<text x='16' y='21' text-anchor='middle' font-size='14' fill='%23999'>—</text>"
    "</svg>"
)


def _host_from_primary_domain(primary_domain: str) -> str:
    """Normalize vendors.primary_domain to a hostname for favicon lookup."""
    raw = (primary_domain or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        try:
            p = urlparse(lower)
            host = (p.netloc or p.path or "").strip()
        except ValueError:
            host = raw
    else:
        host = raw
    host = host.split("/")[0].split(":")[0].strip()
    return host.removeprefix("www.")


def _vendor_favicon_url(primary_domain: str) -> str:
    """Public favicon URL for the vendor site (browser loads it; no backend fetch)."""
    host = _host_from_primary_domain(primary_domain)
    if not host:
        return _ICON_PLACEHOLDER_SVG
    return f"https://www.google.com/s2/favicons?domain={quote(host)}&sz=64"


def _portfolio_display_dataframe(filtered: list[dict]) -> pd.DataFrame:
    """Readable column order and labels; same underlying row data as before."""
    header_map = [
        ("canonical_name", "Vendor"),
        ("primary_segment", "Segment"),
        ("primary_domain", "Domain"),
        ("source_count", "Sources"),
        ("evidence_count", "Evidence"),
        ("last_evidence_at", "Last evidence"),
        ("summary_updated_at", "Summary updated"),
        ("confidence_rollup", "Confidence"),
        ("aum_trillions_hint", "AUM hint"),
        ("advisors_or_institutions_hint", "Advisors hint"),
        ("accounts_millions_hint", "Accounts hint"),
        ("ria_hint", "RIA hint"),
    ]
    records = []
    for r in filtered:
        row = {"Icon": _vendor_favicon_url(str(r.get("primary_domain") or ""))}
        for key, label in header_map:
            v = r.get(key, "")
            if key in ("source_count", "evidence_count", "ria_hint"):
                if v != "" and v is not None:
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        pass
                else:
                    v = pd.NA
            elif key == "confidence_rollup":
                if v != "" and v is not None:
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        pass
                else:
                    v = pd.NA
            else:
                v = "" if v is None else v
            row[label] = v
        records.append(row)
    return pd.DataFrame.from_records(records)


def _portfolio_column_config() -> dict:
    return {
        "Icon": st.column_config.ImageColumn(
            " ",
            width="small",
            help="Favicon for the vendor domain (loaded in your browser; requires network).",
        ),
        "Vendor": st.column_config.TextColumn("Vendor", width="large"),
        "Segment": st.column_config.TextColumn("Segment", width="medium"),
        "Domain": st.column_config.TextColumn("Domain", width="medium"),
        "Sources": st.column_config.NumberColumn("Sources", format="%d", width="small"),
        "Evidence": st.column_config.NumberColumn("Evidence", format="%d", width="small"),
        "Last evidence": st.column_config.TextColumn("Last evidence", width="medium"),
        "Summary updated": st.column_config.TextColumn("Summary at", width="medium"),
        "Confidence": st.column_config.NumberColumn("Conf.", format="%.2f", width="small"),
        "AUM hint": st.column_config.TextColumn("AUM hint", width="small"),
        "Advisors hint": st.column_config.TextColumn("Advisors hint", width="medium"),
        "Accounts hint": st.column_config.TextColumn("Accounts hint", width="small"),
        "RIA hint": st.column_config.NumberColumn("RIA hint", format="%d", width="small"),
    }


def _apply_layout_polish() -> None:
    """Sidebar stays readable but visually secondary; main column a bit wider."""
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            min-width: 14rem !important;
            width: 15rem !important;
            max-width: 16rem !important;
            font-size: 0.86rem;
        }
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            font-size: 1rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.01em;
        }
        [data-testid="stSidebar"] .stTextInput label p {
            font-size: 0.82rem !important;
            opacity: 0.88;
        }
        .block-container {
            padding-top: 1.35rem;
            padding-left: 1.75rem !important;
            padding-right: 2.5rem !important;
            max-width: 1320px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fmt_metric_cell(v) -> str:
    if v is None or v == "":
        return "—"
    return str(v)


def render_vendor_intelligence(db_path: Path, vendors_yaml: Path) -> None:
    st.markdown("## Vendor Intelligence")
    st.markdown(
        "Unified vendor knowledge base with auto-generated reports from ingested evidence."
    )
    st.caption(
        "Read-only from SQLite. Portfolio “hints” (AUM, advisors, accounts, RIA count) are pattern extracts when evidence matched—not validated financials."
    )
    st.caption(
        f"Hints are stored on **vendor_summaries** and refresh on ingest. If counts look stale after upgrading extraction, run "
        f"`python -m invendx.cli summaries-refresh --db \"{db_path}\"`."
    )
    st.caption("Paths (DB, YAML, exports) live in the narrow sidebar — keep focus here.")

    if not db_path.exists():
        st.warning("Database not found at the sidebar path. Check **Database file** or use Admin to sync.")
        st.info(
            "If this is the hosted Streamlit app, the local SQLite database may not be deployed with the app. "
            "The repository ignores `data/`, so the online version needs a synced or demo database before the "
            "portfolio table can appear."
        )
        st.markdown("#### Getting started")
        st.markdown(
            "1. Set **Paths** in the sidebar (database file, vendors config, exports folder).\n"
            "2. Open **Admin / Operator** — use **Add new vendor** or edit the YAML, then **Update vendor list from config**.\n"
            "3. Run **Run research** for a vendor, then return here for reports and exports."
        )
        st.markdown("#### Current paths")
        st.markdown(
            f"- Database file: `{db_path}`\n"
            f"- Vendors config: `{vendors_yaml}`"
        )
        return

    conn = None
    try:
        conn = connect(db_path)
        init_schema(conn)
        raw = _load_portfolio_rows(conn)
    except Exception as e:  # noqa: BLE001
        st.warning(f"Could not load portfolio: {e}")
        return
    finally:
        if conn is not None:
            conn.close()

    enriched = [_row_for_display_clean(r) for r in raw]
    if not raw:
        st.info(
            "No vendors in the database yet. Open **Admin / Operator**, **Update vendor list from config**, "
            "then run **Run research** for each vendor."
        )

    st.markdown("")
    seg_options = _distinct_primary_segments(enriched)
    c_search, c_sort = st.columns([3, 2], vertical_alignment="bottom", gap="medium")
    with c_search:
        search_q = st.text_input(
            "Search",
            label_visibility="collapsed",
            placeholder="Search by name, segment, or domain…",
            key="intel_search",
        )
    with c_sort:
        sort_labels = [x[0] for x in _INTEL_SORT_OPTIONS]
        sort_keys = [x[1] for x in _INTEL_SORT_OPTIONS]
        sort_ix = st.selectbox(
            "Sort portfolio",
            options=range(len(sort_labels)),
            format_func=lambda i: sort_labels[i],
            key="intel_sort",
            label_visibility="collapsed",
        )
        sort_key = sort_keys[int(sort_ix)]

    selected_segments = st.multiselect(
        "Segment filter",
        options=seg_options,
        default=[],
        key="intel_segment_filter",
        help="Empty = all segments. Values come from each vendor’s **primary_segment** in the database.",
    )
    token_mode = st.checkbox(
        "Match segment tokens (split on / and comma)",
        value=False,
        key="intel_segment_tokens",
        help="When on, a vendor matches if any token in its segment overlaps tokens in the selected segment strings.",
    )

    cohort = _apply_intel_filters(enriched, search_q, selected_segments, token_mode=token_mode)
    view_rows = _sort_portfolio_rows(cohort, sort_key)

    tab_browse, tab_compare, tab_report = st.tabs(["Browse", "Compare", "Report"])

    with tab_browse:
        c_export, _sp = st.columns([1, 4], vertical_alignment="bottom", gap="medium")
        with c_export:
            st.download_button(
                label="Export CSV",
                data=_rows_to_csv_bytes(view_rows),
                file_name="vendor_intelligence_portfolio.csv",
                mime="text/csv",
                key="intel_export_csv",
                use_container_width=True,
            )

        with st.expander("Add a new vendor", expanded=False):
            st.markdown(
                "Use **Admin / Operator → Add new vendor** to append to your vendors config and optionally sync to the database."
            )
            st.caption(f"Config path: `{vendors_yaml}`")
            if st.button("Remind me on Admin tab", key="intel_how_sync"):
                st.session_state["admin_highlight_sync"] = True
                st.info(
                    "Open **Admin / Operator** and use **Add new vendor** or **Update vendor list from config**."
                )

        st.divider()
        st.markdown("### Portfolio")
        st.caption(
            f"**{len(view_rows)}** in view (after search, segment filter, and sort) · "
            "Summaries from ingestion; hints are pattern-based, not validated metrics. "
            "**Icons** are site favicons from each **Domain** (external lookup)."
        )

        _row_px = 36
        _table_h = max(288, min(580, 108 + len(view_rows) * _row_px)) if len(view_rows) else 176
        if not view_rows:
            st.dataframe(pd.DataFrame(), use_container_width=True, height=_table_h, hide_index=True)
        else:
            st.dataframe(
                _portfolio_display_dataframe(view_rows),
                use_container_width=True,
                hide_index=True,
                height=_table_h,
                row_height=_row_px,
                column_config=_portfolio_column_config(),
            )

    with tab_compare:
        st.markdown("### Compare vendors")
        st.caption(
            "Choose **2–5** vendors from the current cohort (same search and segment filters as **Browse**; sort order matches **Browse**)."
        )
        name_opts = [r["canonical_name"] for r in view_rows]
        compare_pick = st.multiselect(
            "Vendors",
            options=name_opts,
            default=[],
            max_selections=5,
            key="intel_compare_pick",
        )
        if len(name_opts) < 2:
            st.info("Need at least two vendors in the cohort to compare. Adjust filters on **Browse**.")
        elif len(compare_pick) < 2:
            st.info("Select **2–5** vendors to see a side-by-side score and ingest summary.")
        else:
            by_name = {r["canonical_name"]: r for r in view_rows}
            paired: list[tuple[dict, dict[str, float] | None, float | None]] = []
            compare_err: str | None = None
            conn_c = None
            try:
                conn_c = connect(db_path)
                init_schema(conn_c)
                for name in compare_pick:
                    row = by_name.get(name) or {}
                    vid = str(row.get("vendor_id") or "")
                    total_pts: float | None = None
                    cat_totals: dict[str, float] | None = None
                    if vid:
                        agg = score_repo.latest_score_category_totals(conn_c, vid)
                        if agg is not None:
                            total_pts, cat_totals = agg
                    paired.append((row, cat_totals, total_pts))
            except Exception as e:  # noqa: BLE001
                compare_err = str(e)
            finally:
                if conn_c is not None:
                    conn_c.close()

            if compare_err:
                st.warning(compare_err)
            elif len(paired) == len(compare_pick):
                all_categories: set[str] = set()
                for _row, ct, _t in paired:
                    if ct:
                        all_categories.update(ct.keys())
                cat_sorted = sorted(all_categories)

                compare_records: list[dict] = []
                for name, (row, cat_totals, total_pts) in zip(compare_pick, paired, strict=True):
                    scored = "yes" if cat_totals is not None else "no"
                    rec: dict = {
                        "Vendor": name,
                        "Segment": row.get("primary_segment") or "",
                        "Domain": row.get("primary_domain") or "",
                        "Sources": row.get("source_count") if row.get("source_count") not in (None, "") else "",
                        "Evidence": row.get("evidence_count") if row.get("evidence_count") not in (None, "") else "",
                        "Last evidence": row.get("last_evidence_at") or "",
                        "Confidence": row.get("confidence_rollup")
                        if row.get("confidence_rollup") not in (None, "")
                        else "",
                        "AUM hint": row.get("aum_trillions_hint") or "",
                        "Advisors hint": row.get("advisors_or_institutions_hint") or "",
                        "RIA hint": row.get("ria_hint") if row.get("ria_hint") not in (None, "") else "",
                        "Scored": scored,
                        "Total score": total_pts if total_pts is not None else "",
                    }
                    for c in cat_sorted:
                        rec[c] = cat_totals.get(c, 0.0) if cat_totals is not None else ""
                    compare_records.append(rec)

                st.dataframe(pd.DataFrame(compare_records), use_container_width=True, hide_index=True)
                st.download_button(
                    label="Export comparison CSV",
                    data=_rows_to_csv_bytes(compare_records),
                    file_name="vendor_intelligence_compare.csv",
                    mime="text/csv",
                    key="intel_compare_csv",
                )

    with tab_report:
        st.markdown("### Vendor report")
        names = [r["canonical_name"] for r in view_rows]
        if not names:
            st.info("No vendors match the current filters. Adjust search or segment filter, or sync vendors in **Admin / Operator**.")
        else:
            pick = st.selectbox(
                "Focus vendor",
                options=names,
                key="intel_report_pick",
                help="Same markdown as CLI report export. Only vendors in the current cohort are listed.",
            )

            row_pick = next((r for r in view_rows if r["canonical_name"] == pick), None)

            conn = None
            try:
                conn = connect(db_path)
                init_schema(conn)
                v = vendor_repo.find_vendor_by_canonical_name(conn, pick)
                if not v:
                    st.warning("Vendor not found.")
                else:
                    with tempfile.TemporaryDirectory() as td:
                        out_md = Path(td) / "report.md"
                        report_builder.export_vendor_markdown(conn, v.vendor_id, out_md)
                        md_text = out_md.read_text(encoding="utf-8")

                    if row_pick:
                        m1, m2, m3, m4 = st.columns(4, gap="small")
                        m1.metric("Sources (URLs)", _fmt_metric_cell(row_pick.get("source_count")))
                        m2.metric("Evidence rows", _fmt_metric_cell(row_pick.get("evidence_count")))
                        m3.metric(
                            "Last evidence",
                            (str(row_pick.get("last_evidence_at") or "—"))[:10]
                            if row_pick.get("last_evidence_at")
                            else "—",
                        )
                        m4.metric("Confidence rollup", _fmt_metric_cell(row_pick.get("confidence_rollup")))

                    with st.container(border=True):
                        st.markdown("##### At a glance")
                        st.caption(
                            "From this vendor’s generated report — header, footprint, and ingestion summary only."
                        )
                        st.markdown(_analyst_glance_markdown(md_text))

                    dl_col, _ = st.columns([1, 3], gap="small")
                    with dl_col:
                        st.download_button(
                            label="Download full report (.md)",
                            data=md_text.encode("utf-8"),
                            file_name=f"{pick}_report.md",
                            mime="text/markdown",
                            key="intel_dl_report_md",
                            use_container_width=True,
                        )

                    with st.expander("Full report — scorecard, evidence excerpts, and details", expanded=False):
                        st.markdown(md_text)
            except Exception as e:  # noqa: BLE001
                st.warning(str(e))
            finally:
                if conn is not None:
                    conn.close()


def render_latest_score_panel(db_path: Path, vendor: str, *, disabled_run: bool) -> None:
    st.subheader("Latest score (read-only)")
    if not disabled_run and db_path.exists():
        conn = None
        try:
            conn = connect(db_path)
            init_schema(conn)
            v = vendor_repo.find_vendor_by_canonical_name(conn, vendor)
            if v:
                meta = score_repo.get_latest_score_run(conn, v.vendor_id)
                if meta:
                    st.markdown(f"**Score run:** `{meta.get('score_run_id')}`")
                    st.markdown(f"**Ruleset:** {meta.get('ruleset_version')}")
                    st.markdown(f"**Created:** {meta.get('created_at')}")
                    rows = score_repo.list_line_items_for_run(conn, meta["score_run_id"])
                    st.dataframe(rows, use_container_width=True, hide_index=True)
                else:
                    st.info("No score run for this vendor yet.")
            else:
                st.warning("Vendor not found in database.")
        except Exception as e:  # noqa: BLE001
            st.warning(str(e))
        finally:
            if conn is not None:
                conn.close()
    else:
        st.info("Select a synced vendor to view scores.")


def _render_manual_intake(db_path: Path, vendor: str, *, disabled_run: bool) -> None:
    """Human-in-the-loop queue → paste capture → promote to evidence (Admin only)."""
    with st.expander("Manual evidence intake", expanded=False):
        st.caption(
            "Queue URLs that resist automation, paste substantive text from the live page (or use "
            "**Chrome fetch** when Playwright is installed), then **Promote** into stored evidence. "
            "Does **not** run scoring; use **Run research and score** or exports when ready. "
            "**Chrome fetch** is operator-initiated; you are responsible for compliance on each URL."
        )
        if disabled_run or not db_path.exists():
            st.info("Select a synced vendor and ensure the database path exists.")
            return
        conn = None
        try:
            conn = connect(db_path)
            init_schema(conn)
            v = vendor_repo.find_vendor_by_canonical_name(conn, vendor)
            if not v:
                st.warning("Vendor not found in database.")
                return

            bulk_report = st.session_state.pop("mi_bulk_fetch_report", None)
            if bulk_report is not None:
                ok_n, err_lines = bulk_report
                if ok_n:
                    st.success(f"Chrome fetch: saved **{ok_n}** capture(s).")
                for ln in err_lines[:25]:
                    st.warning(ln)

            combo_flash = st.session_state.pop("mi_crawl_combo_flash", None)
            if combo_flash is not None:
                flash_msg, flash_errs = combo_flash
                if flash_msg:
                    st.success(flash_msg)
                for ln in (flash_errs or [])[:25]:
                    st.warning(ln)

            promo_all_flash = st.session_state.pop("mi_promote_all_report", None)
            if promo_all_flash is not None:
                pa_ok, pa_errs = promo_all_flash
                if pa_ok:
                    st.success(f"Promoted **{pa_ok}** row(s). No scoring was run.")
                for ln in (pa_errs or [])[:25]:
                    st.warning(ln)

            attach_cdp = st.checkbox(
                "Use Chrome I started myself (remote debugging — open Chrome **before** fetching)",
                value=False,
                key="mi_attach_cdp",
            )
            cdp_for_fetch: str | None = None
            if attach_cdp:
                st.info(
                    "**Step 1:** Quit Chrome completely (all windows).\n\n"
                    "**Step 2:** Start Chrome with remote debugging, for example:\n\n"
                    '`"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                    "--remote-debugging-port=9222`\n\n"
                    "**Step 3:** Leave that window open; then use **Fetch** below. "
                    "InVendX attaches to this Chrome instead of launching its own. "
                    "**Show browser (headed)** options are ignored while this is on."
                )
                _cdp = st.text_input("Chrome DevTools (CDP) URL", value=DEFAULT_CDP_URL, key="mi_cdp_url")
                cdp_for_fetch = (_cdp or "").strip() or DEFAULT_CDP_URL

            latest_run = evidence_repo.get_latest_run_row_for_vendor(conn, v.vendor_id)
            skipped_from_run = parse_crawl_skipped_urls_from_run_notes(
                (latest_run or {}).get("notes")
            )
            if skipped_from_run:
                st.markdown("###### Crawl misses → manual queue")
                st.caption(
                    f"Latest research run recorded **{len(skipped_from_run)}** URL sample(s) the crawler did not "
                    "store (robots / HTTP errors / non-HTML / fetch failures). List is capped (~500). "
                    "Queue them here, then use **Fetch all empty captures** below—or use the combined button."
                )
                crawl_miss_headed = st.checkbox(
                    "Show browser when Chrome-fetching (combined action only)",
                    value=False,
                    key="mi_crawl_miss_headed",
                    disabled=attach_cdp,
                )
                q1, q2 = st.columns(2)
                with q1:
                    if st.button(
                        "Queue crawl-miss URLs (latest run)",
                        key="mi_queue_crawl_skips",
                    ):
                        nq = queue_crawl_skipped_urls_for_vendor(conn, v.vendor_id, skipped_from_run)
                        st.success(f"Queued **{nq}** new row(s).")
                        st.rerun()
                with q2:
                    if st.button(
                        "Queue crawl misses + Chrome-fetch all empty rows",
                        key="mi_queue_crawl_skips_and_fetch",
                        help="Queues new intake rows from the list above, then runs subprocess fetch for every "
                        "pending/captured row that still has no captured text (not only the newly queued).",
                    ):
                        nq = queue_crawl_skipped_urls_for_vendor(conn, v.vendor_id, skipped_from_run)
                        intakes_after = manual_intake_repo.list_intakes_for_vendor(
                            conn,
                            v.vendor_id,
                            include_ingested=False,
                            include_discarded=False,
                        )
                        to_auto = [
                            r
                            for r in intakes_after
                            if r["status"] in ("pending", "captured")
                            and not (r.get("captured_text") or "").strip()
                        ]
                        errs: list[str] = []
                        ok_c = 0
                        with st.spinner(f"Queued {nq}; fetching {len(to_auto)} URL(s)…"):
                            for r in to_auto:
                                ok_sub, err_msg = run_manual_fetch_subprocess(
                                    db_path=db_path,
                                    intake_id=r["intake_id"],
                                    headed=crawl_miss_headed if not attach_cdp else False,
                                    connect_cdp_url=cdp_for_fetch if attach_cdp else None,
                                )
                                if ok_sub:
                                    ok_c += 1
                                else:
                                    short = (r.get("source_url") or "")[:72]
                                    errs.append(f"{short} — {err_msg}")
                        msg_parts: list[str] = []
                        if nq:
                            msg_parts.append(f"Queued **{nq}** row(s).")
                        if ok_c:
                            msg_parts.append(f"Chrome-saved **{ok_c}** capture(s).")
                        st.session_state["mi_crawl_combo_flash"] = (
                            " ".join(msg_parts) if msg_parts else None,
                            errs,
                        )
                        st.rerun()

            st.markdown("###### Add URL to queue")
            n_url = st.text_input("Source URL", placeholder="https://…", key="mi_new_url")
            n_reason = st.selectbox("Reason flagged", REASON_FLAGS, key="mi_new_reason")
            n_stype = st.selectbox("Source type", SOURCE_TYPES, index=0, key="mi_new_stype")
            n_note = st.text_area("Operator notes (optional)", height=68, key="mi_new_onotes")
            ac1, ac2 = st.columns(2)
            with ac1:
                if st.button("Add to queue", type="primary", key="mi_add_btn"):
                    url = normalize_source_url(n_url)
                    if not url:
                        st.error("Enter a URL.")
                    else:
                        ik = default_instructions_key(n_reason)
                        new_id = manual_intake_repo.insert_intake(
                            conn,
                            vendor_id=v.vendor_id,
                            source_url=url,
                            source_type=n_stype,
                            reason_flagged=n_reason,
                            instructions_key=ik,
                            operator_notes=n_note.strip() or None,
                            skip_if_url_exists=True,
                        )
                        if new_id is None:
                            st.warning("That URL is already in the queue (non-discarded).")
                        else:
                            st.success("Queued.")
                        st.rerun()
            with ac2:
                dj = st.session_state.get("admin_discover_json")
                if dj:
                    if st.button("Queue all discover preview URLs", key="mi_add_discover"):
                        nq = 0
                        n_skip = 0
                        for t in dj:
                            u = normalize_source_url(str(t.get("url") or ""))
                            if not u:
                                continue
                            added = manual_intake_repo.insert_intake(
                                conn,
                                vendor_id=v.vendor_id,
                                source_url=u,
                                source_type="target_official",
                                reason_flagged="discovered_target",
                                instructions_key="discovered_target",
                                skip_if_url_exists=True,
                            )
                            if added:
                                nq += 1
                            else:
                                n_skip += 1
                        msg = f"Queued **{nq}** new URL(s) from discover preview."
                        if n_skip:
                            msg += f" Skipped **{n_skip}** already in queue."
                        st.success(msg)
                        st.rerun()

            show_ingested = st.checkbox("Show ingested rows", value=False, key="mi_show_ingested")
            intakes = manual_intake_repo.list_intakes_for_vendor(
                conn,
                v.vendor_id,
                include_ingested=show_ingested,
                include_discarded=False,
            )

            if intakes:
                rows_view: list[dict] = []
                for r in intakes:
                    rows_view.append(
                        {
                            "intake_id": r["intake_id"][:8] + "…",
                            "status": r["status"],
                            "source_type": r["source_type"],
                            "reason": r["reason_flagged"],
                            "capture": (r.get("capture_method") or "—"),
                            "captured_at": (str(r.get("captured_at") or ""))[:19] or "—",
                            "captured_by": r.get("captured_by") or "—",
                            "source_url": r["source_url"],
                        }
                    )
                st.markdown("###### Queue")
                st.dataframe(pd.DataFrame(rows_view), use_container_width=True, hide_index=True)
                if st.button(
                    "Discard duplicate rows (same URL — keep one pending/captured row per link)",
                    key="mi_dedupe_url_btn",
                ):
                    nd = discard_duplicate_active_intakes_by_url(conn, v.vendor_id)
                    st.success(f"Discarded **{nd}** duplicate row(s).")
                    st.rerun()

                st.markdown("###### Bulk Chrome fetch")
                st.caption(
                    "Fetches rendered text only for rows that are pending/captured with **no** captured text yet "
                    "(does not overwrite). Uses a **subprocess** (CLI) so Playwright works under Streamlit on Windows. "
                    "Requires `pip install '.[browser]'` and `playwright install chrome`."
                )
                to_fetch_empty = [
                    r
                    for r in intakes
                    if r["status"] in ("pending", "captured")
                    and not (r.get("captured_text") or "").strip()
                ]
                bh1, bh2 = st.columns(2)
                with bh1:
                    bulk_headed = st.checkbox(
                        "Show browser (headed)",
                        value=False,
                        key="mi_bulk_headed",
                        disabled=attach_cdp,
                    )
                with bh2:
                    no_bulk = len(to_fetch_empty) == 0
                    if st.button(
                        "Fetch all empty captures (Chrome)",
                        key="mi_bulk_fetch",
                        disabled=no_bulk,
                        help="One page at a time; may take a while.",
                    ):
                        errs: list[str] = []
                        ok_c = 0
                        with st.spinner(f"Fetching {len(to_fetch_empty)} URL(s)…"):
                            for r in to_fetch_empty:
                                ok_sub, err_msg = run_manual_fetch_subprocess(
                                    db_path=db_path,
                                    intake_id=r["intake_id"],
                                    headed=bulk_headed if not attach_cdp else False,
                                    connect_cdp_url=cdp_for_fetch if attach_cdp else None,
                                )
                                if ok_sub:
                                    ok_c += 1
                                else:
                                    short = (r.get("source_url") or "")[:72]
                                    errs.append(f"{short} — {err_msg}")
                        st.session_state["mi_bulk_fetch_report"] = (ok_c, errs)
                        st.rerun()

                labels = [
                    f"{r['intake_id'][:8]} — {r['status']} — {r['source_url'][:64]}"
                    for r in intakes
                ]
                pick = st.selectbox("Row detail", range(len(intakes)), format_func=lambda i: labels[i], key="mi_pick")
                row = intakes[pick]
                iid = row["intake_id"]
                st.markdown(f"**Source:** [{row['source_url']}]({row['source_url']})")
                st.markdown(f"**Created:** {row.get('created_at') or '—'}")
                if row["status"] == "ingested":
                    st.success(
                        f"Ingested — run `{row.get('promoted_run_id')}` — IDs `{row.get('promoted_evidence_ids_json')}`"
                    )
                with st.expander("Guidance for this row", expanded=True):
                    st.markdown(guidance_for_key(row["instructions_key"]))

                if row["status"] == "ingested":
                    if row.get("captured_text"):
                        st.text_area(
                            "Captured text (read-only)",
                            value=row["captured_text"],
                            height=160,
                            disabled=True,
                            key=f"mi_ro_{iid}",
                        )
                else:
                    st.caption(
                        "**Chrome fetch** runs `invendx manual fetch` in a subprocess (Playwright; prefers system Chrome). "
                        "Install: `pip install '.[browser]'` then `playwright install chrome`."
                    )
                    fc1, fc2 = st.columns(2)
                    with fc1:
                        single_headed = st.checkbox(
                            "Show browser window (headed)",
                            key=f"mi_headed_{iid}",
                            disabled=attach_cdp,
                        )
                    with fc2:
                        if st.button("Fetch page text (Chrome)", key=f"mi_fetch_{iid}"):
                            with st.spinner("Fetching…"):
                                ok_sub, err_msg = run_manual_fetch_subprocess(
                                    db_path=db_path,
                                    intake_id=iid,
                                    headed=single_headed if not attach_cdp else False,
                                    connect_cdp_url=cdp_for_fetch if attach_cdp else None,
                                )
                            if ok_sub:
                                st.rerun()
                            else:
                                st.error(err_msg)
                    _cap_method = row.get("capture_method") or "paste"
                    with st.form(f"mi_detail_{iid}"):
                        cap = st.text_area(
                            "Captured text (paste from page)",
                            value=row.get("captured_text") or "",
                            height=240,
                            help="Required before promote. Stored as evidence excerpt.",
                        )
                        by = st.text_input("Captured by", value=row.get("captured_by") or "")
                        onotes = st.text_area("Operator notes", value=row.get("operator_notes") or "", height=68)
                        fs_save = st.form_submit_button("Save capture")
                        fs_notes = st.form_submit_button("Save notes only")
                        pr_a, pr_b = st.columns(2)
                        with pr_a:
                            fs_promo = st.form_submit_button("Promote to evidence (no scoring)")
                        with pr_b:
                            fs_promo_all = st.form_submit_button(
                                "Promote all captured (no scoring)",
                                help="Promotes every **captured** queue row for this vendor that has saved text. "
                                "Skips pending rows and duplicate fingerprints.",
                            )
                        fs_disc = st.form_submit_button("Discard queue row")
                        if fs_save:
                            if not cap.strip():
                                st.error("Captured text is empty.")
                            else:
                                manual_intake_repo.save_capture(
                                    conn,
                                    iid,
                                    captured_text=cap.strip(),
                                    captured_by=by.strip() or None,
                                    capture_method=_cap_method,
                                )
                                manual_intake_repo.update_operator_notes(conn, iid, onotes.strip() or None)
                                st.success("Saved capture.")
                                st.rerun()
                        if fs_notes:
                            manual_intake_repo.update_operator_notes(conn, iid, onotes.strip() or None)
                            st.success("Saved notes.")
                            st.rerun()
                        if fs_promo:
                            if not cap.strip():
                                st.error("Paste captured text before promoting (or Save capture first).")
                            else:
                                manual_intake_repo.save_capture(
                                    conn,
                                    iid,
                                    captured_text=cap.strip(),
                                    captured_by=by.strip() or None,
                                    capture_method=_cap_method,
                                )
                                manual_intake_repo.update_operator_notes(conn, iid, onotes.strip() or None)
                                run_id, ev_ids, err = promote_intake_to_evidence(conn, iid)
                                if err:
                                    st.error(err)
                                else:
                                    st.success(f"Promoted — run `{run_id}` — evidence `{ev_ids}`")
                                    st.rerun()
                        if fs_promo_all:
                            all_for_vendor = manual_intake_repo.list_intakes_for_vendor(
                                conn,
                                v.vendor_id,
                                include_ingested=show_ingested,
                                include_discarded=False,
                            )
                            to_promote = [
                                r
                                for r in all_for_vendor
                                if r["status"] == "captured"
                                and (r.get("captured_text") or "").strip()
                            ]
                            if not to_promote:
                                st.warning("No **captured** rows with text to promote. Save capture first.")
                            else:
                                ok_n = 0
                                err_lines: list[str] = []
                                with st.spinner(f"Promoting {len(to_promote)} row(s)…"):
                                    for r in sorted(
                                        to_promote,
                                        key=lambda x: (str(x.get("created_at") or ""), x["intake_id"]),
                                    ):
                                        _rid, _eids, perr = promote_intake_to_evidence(conn, r["intake_id"])
                                        if perr:
                                            short = (r.get("source_url") or "")[:48]
                                            err_lines.append(f"{r['intake_id'][:8]}… {short} — {perr}")
                                        else:
                                            ok_n += 1
                                st.session_state["mi_promote_all_report"] = (ok_n, err_lines)
                                st.rerun()
                        if fs_disc:
                            if manual_intake_repo.mark_discarded(conn, iid):
                                st.warning("Row discarded.")
                                st.rerun()
                            st.error("Could not discard (wrong status?).")
            else:
                st.info("No queue rows for this vendor yet. Add a URL above or from discover preview.")
        except Exception as e:  # noqa: BLE001
            st.warning(str(e))
        finally:
            if conn is not None:
                conn.close()


def render_admin_operator(
    db_path: Path,
    vendors_yaml: Path,
    exports_dir: Path,
) -> None:
    st.subheader("Admin / Operator")
    st.caption(
        "Runs the same pipeline as the `invendx` CLI. External tools can still call `invendx …`; "
        "this tab uses the same config file and database paths from the sidebar."
    )
    if st.session_state.pop("admin_highlight_sync", None):
        st.success("Use **Update vendor list from config** after adding or editing vendors.")

    vendors_preview: list = []
    setup_block = False
    if not db_path.exists():
        setup_block = True
    else:
        try:
            conn = connect(db_path)
            init_schema(conn)
            vendors_preview = vendor_repo.list_vendors(conn)
            conn.close()
            if not vendors_preview:
                setup_block = True
        except Exception as e:  # noqa: BLE001
            st.warning(f"Could not read database: {e}")
            setup_block = True

    if setup_block:
        st.markdown("#### Getting started")
        st.markdown(
            "1. Confirm **Database file** and **Vendors config** in the sidebar.\n"
            "2. Add vendors with **Add new vendor** below (or edit the YAML on disk).\n"
            "3. Click **Update vendor list from config** to load them into the database.\n"
            "4. Select a vendor, optionally **Preview crawl URLs**, then **Run research**."
        )

    with st.expander("Add new vendor", expanded=False):
        st.caption(
            "Writes to your vendors YAML (CLI-compatible). The file may be reformatted; duplicate canonical names are rejected."
        )
        with st.form("admin_add_vendor_form", clear_on_submit=False):
            av_name = st.text_input("Canonical name *", placeholder='e.g. "Acme Wealth"', key="addv_name")
            av_domain = st.text_input(
                "Primary domain *", placeholder="example.com or https://example.com", key="addv_domain"
            )
            av_segment = st.text_input("Segment (optional)", key="addv_segment")
            av_aliases = st.text_area(
                "Aliases (optional, comma or newline separated)",
                height=68,
                key="addv_aliases",
            )
            av_press = st.text_area("Press / newsroom URLs (optional, one per line)", height=68, key="addv_press")
            av_careers = st.text_area("Careers URLs (optional, one per line)", height=68, key="addv_careers")
            av_gh = st.text_input(
                "GitHub org slug (optional, for public repo metadata; needs GITHUB_TOKEN)",
                key="addv_gh",
            )
            av_sync = st.checkbox("Update vendor list from config after save", value=True, key="addv_sync")
            submitted = st.form_submit_button("Save vendor to config")
        if submitted:
            dom = vendor_yaml.normalize_primary_domain(av_domain)
            if not (av_name or "").strip() or not dom:
                st.error("Canonical name and primary domain are required.")
            else:
                seed_urls: dict[str, list[str]] = {}
                press_urls = vendor_yaml.parse_url_lines(av_press)
                careers_urls = vendor_yaml.parse_url_lines(av_careers)
                if press_urls:
                    seed_urls["press"] = press_urls
                if careers_urls:
                    seed_urls["careers"] = careers_urls
                gh = (av_gh or "").strip() or None
                try:
                    seed = VendorSeed(
                        canonical_name=(av_name or "").strip(),
                        primary_domain=dom,
                        primary_segment=(av_segment or "").strip(),
                        aliases=vendor_yaml.parse_alias_list(av_aliases),
                        seed_urls=seed_urls,
                        github_org=gh,
                    )
                except ValidationError as e:
                    st.error(str(e))
                else:
                    try:
                        vendor_yaml.append_vendor_seed(vendors_yaml, seed)
                    except ValueError as e:
                        st.error(str(e))
                    except OSError as e:
                        st.error(f"Could not write config: {e}")
                    else:
                        st.success(f"Saved **{seed.canonical_name}** to `{vendors_yaml}`.")
                        if av_sync:
                            exports_dir.mkdir(parents=True, exist_ok=True)
                            db_path.parent.mkdir(parents=True, exist_ok=True)
                            code = _run_cli(
                                ["vendors", "sync", "--config", str(vendors_yaml), "--db", str(db_path)]
                            )
                            if code == 0:
                                st.success("Vendor list updated in the database.")
                            else:
                                st.error("Sync failed — see Technical details log.")

    if st.button(
        "Update vendor list from config",
        type="primary",
        key="admin_sync",
        help="Same as: invendx vendors sync --config … --db …",
    ):
        exports_dir.mkdir(parents=True, exist_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        code = _run_cli(["vendors", "sync", "--config", str(vendors_yaml), "--db", str(db_path)])
        if code == 0:
            st.success("Vendor list updated from config.")
        else:
            st.error("Sync failed — see Technical details log.")

    with st.expander("Coverage diagnostics", expanded=False):
        st.caption(
            "Read-only: ingest runs, evidence volume, summary row, latest score, and coverage status "
            "(bar: 8+ evidence rows and 3+ distinct source URLs). CLI: "
            "`invendx export coverage --db … --out …` → vendor_coverage.csv."
        )
        if not db_path.exists():
            st.info("Database not found — set path in sidebar.")
        else:
            conn_cov = None
            try:
                conn_cov = connect(db_path)
                init_schema(conn_cov)
                raw_cov = fetch_coverage_rows(conn_cov)
            except Exception as e:  # noqa: BLE001
                st.warning(str(e))
            else:
                rows_ui: list[dict] = []
                for r in raw_cov:
                    st_lbl, notes = classify_coverage(r, DEFAULT_THRESHOLDS)
                    rows_ui.append(
                        {
                            "Vendor": r.get("canonical_name"),
                            "Domain": r.get("primary_domain"),
                            "Ingest runs": r.get("ingest_run_count"),
                            "Evidence": r.get("evidence_count"),
                            "Distinct URLs": r.get("distinct_source_url_count"),
                            "Latest ingest": (str(r.get("latest_ingest_at") or ""))[:19],
                            "Latest evidence": (str(r.get("latest_evidence_at") or ""))[:19],
                            "Summary": "yes" if r.get("summary_row_present") else "no",
                            "Scored": "yes" if r.get("latest_score_run_present") else "no",
                            "Score lines": r.get("latest_score_line_item_count"),
                            "Status": st_lbl,
                            "Notes": notes,
                        }
                    )
                st.dataframe(
                    pd.DataFrame(rows_ui),
                    use_container_width=True,
                    hide_index=True,
                )
            finally:
                if conn_cov is not None:
                    conn_cov.close()

    col_main, col_side = st.columns([2, 1])

    with col_main:
        st.markdown("##### Pipeline")
        vendors: list = []
        if db_path.exists():
            try:
                conn = connect(db_path)
                init_schema(conn)
                vendors = vendor_repo.list_vendors(conn)
                conn.close()
            except Exception as e:  # noqa: BLE001
                st.warning(f"Could not load vendors: {e}")
        names = [v.canonical_name for v in vendors]
        vendor = st.selectbox(
            "Vendor",
            options=names if names else ["(add vendors and sync first)"],
            disabled=not names,
            key="admin_vendor_select",
        )
        disabled_run = not names or vendor == "(add vendors and sync first)"
        prev_v = st.session_state.get("_admin_vendor_track")
        if prev_v is not None and prev_v != vendor:
            st.session_state.pop("admin_discover_json", None)
        st.session_state["_admin_vendor_track"] = vendor

        if st.button(
            "Preview crawl URLs",
            disabled=disabled_run,
            key="admin_discover",
            help="Same as: invendx discover … --json",
        ):
            code, out, _err = _run_cli_with_output(
                [
                    "discover",
                    vendor,
                    "--db",
                    str(db_path),
                    "--config",
                    str(vendors_yaml),
                    "--json",
                ]
            )
            if code != 0:
                st.error("Preview failed — see Technical details log.")
            else:
                try:
                    targets = json.loads(out)
                    st.session_state["admin_discover_json"] = targets
                except json.JSONDecodeError:
                    st.error("Could not parse discover output.")
                    st.session_state.pop("admin_discover_json", None)
        if st.session_state.get("admin_discover_json"):
            st.dataframe(pd.DataFrame(st.session_state["admin_discover_json"]), use_container_width=True)

        st.markdown("##### Crawl limits (optional)")
        c1, c2, c3 = st.columns(3)
        with c1:
            max_pages_in = st.text_input("Max pages", placeholder="default 40", key="admin_max_pages")
        with c2:
            max_depth_in = st.text_input("Max depth", placeholder="default 2", key="admin_max_depth")
        with c3:
            delay_in = st.text_input("Delay (seconds)", placeholder="default 0.75", key="admin_delay")

        st.markdown("##### After research completes")
        score_after_run = st.checkbox(
            "Also compute scores (rule-based)",
            value=True,
            key="admin_score_after",
            help="Adds --score to invendx run.",
        )
        all_evidence_when_scoring = st.checkbox(
            "When scoring, use all saved evidence for this vendor",
            value=False,
            key="admin_all_evidence",
            help="CLI flag --all-evidence. Omitting this matches CLI default (latest ingest run only).",
        )
        st.caption("Same commands as: `invendx run …`, optionally `--score` and `--all-evidence`.")

        st.markdown("##### Research")
        b_run1, b_run2 = st.columns(2)
        max_pages = _optional_int(max_pages_in)
        max_depth = _optional_int(max_depth_in)
        delay = _optional_float(delay_in)

        with b_run1:
            if st.button(
                "Run research",
                disabled=disabled_run,
                key="admin_run_ingest",
                help="invendx run without --score (collect evidence only).",
            ):
                exports_dir.mkdir(parents=True, exist_ok=True)
                args = _run_ingest_args(
                    vendor,
                    db_path,
                    vendors_yaml,
                    with_score=False,
                    score_all_evidence=False,
                    max_pages=max_pages,
                    max_depth=max_depth,
                    delay=delay,
                )
                code, out, _ = _run_cli_with_output(args)
                if code == 0:
                    n = _parse_run_evidence_count(out)
                    if n is not None:
                        st.success(
                            f"Research finished. Saved **{n}** evidence rows. "
                            "Open **Vendor Intelligence** to review."
                        )
                    else:
                        st.success("Research finished. Open **Vendor Intelligence** to review.")
                else:
                    st.error("Research failed — check domain and network, or see Technical details log.")

        with b_run2:
            if st.button(
                "Run research and score",
                disabled=disabled_run,
                key="admin_run_score",
                help="invendx run; honors the two scoring options above.",
            ):
                exports_dir.mkdir(parents=True, exist_ok=True)
                args = _run_ingest_args(
                    vendor,
                    db_path,
                    vendors_yaml,
                    with_score=score_after_run,
                    score_all_evidence=all_evidence_when_scoring,
                    max_pages=max_pages,
                    max_depth=max_depth,
                    delay=delay,
                )
                code, out, _ = _run_cli_with_output(args)
                if code == 0:
                    n = _parse_run_evidence_count(out)
                    if score_after_run:
                        msg = "Research and scoring finished."
                    else:
                        msg = "Research finished (scoring was unchecked)."
                    if n is not None:
                        st.success(f"{msg} Evidence rows saved: **{n}**. See **Vendor Intelligence** for the report.")
                    else:
                        st.success(f"{msg} See **Vendor Intelligence** for the report.")
                else:
                    st.error("Run failed — see Technical details log.")

        st.markdown("##### Exports (writes under your exports folder)")
        ex1, ex2, ex3 = st.columns(3)
        with ex1:
            if st.button(
                "Export evidence (CSV)",
                disabled=disabled_run,
                key="admin_export_evidence",
            ):
                exports_dir.mkdir(parents=True, exist_ok=True)
                code = _run_cli(
                    [
                        "export",
                        "evidence",
                        "--vendor",
                        vendor,
                        "--db",
                        str(db_path),
                        "--out",
                        str(exports_dir),
                    ]
                )
                dest = exports_dir / f"{vendor}_evidence.csv"
                if code == 0:
                    st.success(f"Wrote `{dest}`")
                else:
                    st.error("Export failed — see Technical details log.")
        with ex2:
            if st.button(
                "Export scorecard (CSV)",
                disabled=disabled_run,
                key="admin_export_scorecard",
            ):
                exports_dir.mkdir(parents=True, exist_ok=True)
                code = _run_cli(
                    [
                        "export",
                        "scorecard",
                        "--vendor",
                        vendor,
                        "--db",
                        str(db_path),
                        "--out",
                        str(exports_dir),
                    ]
                )
                dest = exports_dir / f"{vendor}_scorecard.csv"
                if code == 0:
                    st.success(f"Wrote `{dest}`")
                else:
                    st.error("Export failed — see Technical details log.")
        with ex3:
            if st.button(
                "Export report (Markdown)",
                disabled=disabled_run,
                key="admin_export_report",
            ):
                exports_dir.mkdir(parents=True, exist_ok=True)
                code = _run_cli(
                    [
                        "export",
                        "report",
                        "--vendor",
                        vendor,
                        "--db",
                        str(db_path),
                        "--out",
                        str(exports_dir),
                    ]
                )
                dest = exports_dir / f"{vendor}_report.md"
                if code == 0:
                    st.success(f"Wrote `{dest}`")
                else:
                    st.error("Export failed — see Technical details log.")

        if st.button(
            "Export all for this vendor",
            disabled=disabled_run,
            key="admin_export_all",
            help="Runs export evidence, scorecard, and report for the selected vendor.",
        ):
            exports_dir.mkdir(parents=True, exist_ok=True)
            steps = [
                ("evidence", f"{vendor}_evidence.csv"),
                ("scorecard", f"{vendor}_scorecard.csv"),
                ("report", f"{vendor}_report.md"),
            ]
            failed: list[str] = []
            for kind, _fname in steps:
                code = _run_cli(
                    [
                        "export",
                        kind,
                        "--vendor",
                        vendor,
                        "--db",
                        str(db_path),
                        "--out",
                        str(exports_dir),
                    ]
                )
                if code != 0:
                    failed.append(kind)
            if not failed:
                st.success(
                    f"All exports saved under `{exports_dir}` "
                    f"({vendor}_evidence.csv, {vendor}_scorecard.csv, {vendor}_report.md)."
                )
            else:
                st.error(f"Some exports failed ({', '.join(failed)}) — see Technical details log.")

        _render_manual_intake(db_path, vendor, disabled_run=disabled_run)

        with st.expander("Technical details (command log)", expanded=False):
            if st.button("Clear log", key="admin_clear_log"):
                st.session_state.log_lines = []
            log_text = "\n".join(st.session_state.get("log_lines", []))
            st.code(log_text or "(no commands yet)", language="bash")
            st.download_button(
                label="Download log for support",
                data=(log_text or "").encode("utf-8"),
                file_name="invendx_operator_log.txt",
                mime="text/plain",
                key="admin_dl_log",
            )

    with col_side:
        render_latest_score_panel(db_path, vendor, disabled_run=disabled_run)


def render_concept_intent(db_path: Path, vendors_yaml: Path, exports_dir: Path) -> None:
    """Read-only project concept page for sharing the app."""
    st.subheader("Concept / Intent")
    st.markdown(
        "InVendX is an evidence-first vendor intelligence system for wealthtech and fintech "
        "platform evaluation."
    )
    st.caption(
        "This page is read-only. It explains the intent of the application and does not run crawls, "
        "write to the database, or change vendor configuration."
    )

    st.markdown("### What this is for")
    st.markdown(
        "The application is designed to answer a practical consulting question: "
        "**which vendor actually works in the real world, and why?**"
    )
    st.markdown(
        "The original insight behind the project is that vendor evaluation is slowed down by "
        "scattered documentation, polished demos, fragmented proof points, and hard-to-compare "
        "technical claims. InVendX turns that noise into structured decision intelligence."
    )

    st.markdown("### How it should work")
    st.markdown(
        "1. Start with vendor seeds in YAML: canonical name, domain, segment, aliases, and optional source URLs.\n"
        "2. Discover and crawl bounded public sources for each vendor.\n"
        "3. Extract evidence rows from pages, developer signals, careers pages, seeded URLs, and optional GitHub metadata.\n"
        "4. Normalize entities and store each claim or signal in SQLite.\n"
        "5. Score vendors with transparent rules that cite supporting evidence IDs.\n"
        "6. Use the UI to browse, compare, export CSVs, and generate evidence-backed Markdown reports."
    )

    st.markdown("### Core principles")
    st.markdown(
        "- Evidence is the system of record.\n"
        "- One row equals one claim or signal.\n"
        "- Scores are derived from evidence, not invented.\n"
        "- Rules-based scoring comes first; LLM summarization can come later.\n"
        "- Real-world usage signals matter more than marketing language.\n"
        "- The pipeline is vendor-scoped, not an internet-wide scraper."
    )

    st.markdown("### What it is not")
    st.markdown(
        "- Not a generic web scraper.\n"
        "- Not a chatbot in the current MVP.\n"
        "- Not a finished commercial product.\n"
        "- Not a replacement for analyst judgment.\n"
        "- Not a source of validated financial metrics; AUM, advisor, account, and RIA values are pattern-based hints."
    )

    st.markdown("### Current MVP")
    st.markdown(
        "The local version already has the main MVP loop: vendor sync, bounded crawl, evidence ingestion, "
        "summary refresh, rules-based scoring, CSV exports, Markdown reports, and an operator UI. The "
        "portfolio view is strongest when the SQLite database has been populated with research runs."
    )

    st.markdown("### Surfaces in this app")
    st.markdown(
        "- **Vendor Intelligence** is the analyst-facing view: browse the portfolio, compare vendors, and build reports.\n"
        "- **Admin / Operator** is the control surface: sync vendors, run research, compute scores, export files, and manage manual intake.\n"
        "- **Concept / Intent** is the shareable explanation layer for reviewers, collaborators, and portfolio audiences."
    )

    st.markdown("### Hosted app note")
    st.markdown(
        "The online Streamlit app can load the code without automatically having your local SQLite database. "
        "Because `data/` is ignored by git, a hosted deployment may show an empty or missing database until "
        "vendors are synced and research is run in that environment, or until a separate approved demo dataset is provided."
    )

    st.markdown("### Future direction")
    st.markdown(
        "- Private document and interview ingestion.\n"
        "- Internal notes and manual evidence workflows.\n"
        "- Richer scoring categories for platform evaluation.\n"
        "- Relationship graph and competitive context.\n"
        "- Citation-backed chatbot over stored evidence."
    )

    st.markdown("### Active paths")
    st.markdown(
        f"- Database file: `{db_path}`\n"
        f"- Vendors config: `{vendors_yaml}`\n"
        f"- Exports folder: `{exports_dir}`"
    )


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    _apply_layout_polish()
    st.title(PAGE_TITLE)

    repo_root = Path(__file__).resolve().parent
    db_default = str(repo_root / "data" / "invendx.db")
    cfg_default = str(repo_root / "config" / "vendors.yaml")
    exp_default = str(repo_root / "exports")

    with st.sidebar:
        st.header("Paths")
        db_path = Path(st.text_input("Database file", value=db_default, key="path_db"))
        vendors_yaml = Path(st.text_input("Vendors config (YAML)", value=cfg_default, key="path_cfg"))
        exports_dir = Path(st.text_input("Exports folder", value=exp_default, key="path_exports"))
        if _hydrate_demo_db_if_missing(db_path, repo_root):
            st.success("Loaded bundled demo database for this session.")
        with st.expander("Glossary"):
            st.markdown(
                "**Sync / update vendor list** — reads your vendors YAML into SQLite (`vendors` table). "
                "Same as `invendx vendors sync`.\n\n"
                "**Evidence** — one stored signal from a public page or source, with URL and run metadata.\n\n"
                "**Research / run** — bounded crawl and extraction for one vendor; same as `invendx run`.\n\n"
                "**Score run** — rule-based scorecard lines linked to evidence IDs; from `invendx score` or "
                "`run` with scoring enabled."
            )

    tab_intel, tab_admin, tab_concept = st.tabs(
        ["Vendor Intelligence", "Admin / Operator", "Concept / Intent"]
    )
    with tab_intel:
        render_vendor_intelligence(db_path, vendors_yaml)
    with tab_admin:
        render_admin_operator(db_path, vendors_yaml, exports_dir)
    with tab_concept:
        render_concept_intent(db_path, vendors_yaml, exports_dir)


if __name__ == "__main__":
    main()
