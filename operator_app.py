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
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlparse

import pandas as pd
import streamlit as st

from invendx.pipeline import report_builder
from invendx.storage.db import connect, init_schema
from invendx.storage import score_repo, vendor_repo

PAGE_TITLE = "InVendX"


def _append_log(msg: str) -> None:
    if "log_lines" not in st.session_state:
        st.session_state.log_lines = []
    st.session_state.log_lines.append(msg.rstrip())


def _run_cli(args: list[str], cwd: Path | None = None) -> int:
    cmd = [sys.executable, "-m", "invendx.cli", *args]
    _append_log(f"$ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=os.environ.copy(),
    )
    if proc.stdout:
        _append_log(proc.stdout)
    if proc.stderr:
        _append_log("[stderr]\n" + proc.stderr)
    _append_log(f"(exit {proc.returncode})")
    return proc.returncode


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
        if t.startswith("# "):
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
        elif mode == "summary" and t.startswith("- "):
            s = t
            s = re.sub(r"\*\*Sources \(distinct URLs\)\*\*", "**Sources**", s)
            s = re.sub(r"\*\*Evidence rows\*\*", "**Evidence**", s)
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
    ]
    records = []
    for r in filtered:
        row = {"Icon": _vendor_favicon_url(str(r.get("primary_domain") or ""))}
        for key, label in header_map:
            v = r.get(key, "")
            if key in ("source_count", "evidence_count"):
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
        "Read-only from SQLite. Portfolio “hints” (AUM, advisors, accounts) are pattern extracts when evidence matched—not validated financials."
    )
    st.caption("Paths (DB, YAML, exports) live in the narrow sidebar — keep focus here.")

    if not db_path.exists():
        st.warning("Database not found at the sidebar path. Check **Database file** or use Admin to sync.")
        with st.expander("Add vendor (YAML + Admin sync)", expanded=False):
            st.markdown(
                "Add a vendor seed to your YAML config, then open **Admin / Operator** and run **Sync vendors from YAML**."
            )
            st.markdown(f"**Config file:** `{vendors_yaml}`")
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

    st.markdown("")
    c_search, c_export = st.columns([5, 1], vertical_alignment="bottom", gap="medium")
    with c_search:
        search_q = st.text_input(
            "Search",
            label_visibility="collapsed",
            placeholder="Search by name, segment, or domain…",
            key="intel_search",
        )
    with c_export:
        filtered = _filter_portfolio(enriched, search_q)
        st.download_button(
            label="Export CSV",
            data=_rows_to_csv_bytes(filtered),
            file_name="vendor_intelligence_portfolio.csv",
            mime="text/csv",
            key="intel_export_csv",
            use_container_width=True,
        )

    with st.expander("New vendor? (YAML — not added in this UI)", expanded=False):
        st.caption(
            "Edit your vendors YAML on disk, then use **Admin / Operator → Sync vendors from YAML**."
        )
        st.code(str(vendors_yaml), language=None)
        if st.button("Remind me on Admin tab", key="intel_how_sync"):
            st.session_state["admin_highlight_sync"] = True
            st.info("Open **Admin / Operator** and click **Sync vendors from YAML**.")

    st.divider()
    st.markdown("### Portfolio")
    st.caption(
        f"**{len(filtered)}** in view · Summaries from ingestion; hints are pattern-based, not validated metrics. "
        "**Icons** are site favicons from each **Domain** (external lookup)."
    )

    _row_px = 36
    _table_h = max(288, min(580, 108 + len(filtered) * _row_px)) if len(filtered) else 176
    if not filtered:
        st.dataframe(pd.DataFrame(), use_container_width=True, height=_table_h, hide_index=True)
    else:
        st.dataframe(
            _portfolio_display_dataframe(filtered),
            use_container_width=True,
            hide_index=True,
            height=_table_h,
            row_height=_row_px,
            column_config=_portfolio_column_config(),
        )

    names = [r["canonical_name"] for r in filtered]
    if not names:
        st.info("No vendors match the filter.")
        return

    st.divider()
    st.markdown("### Vendor report")
    pick = st.selectbox(
        "Focus vendor",
        options=names,
        key="intel_report_pick",
        help="Same markdown as CLI report export.",
    )

    row_pick = next((r for r in filtered if r["canonical_name"] == pick), None)

    conn = None
    try:
        conn = connect(db_path)
        init_schema(conn)
        v = vendor_repo.find_vendor_by_canonical_name(conn, pick)
        if not v:
            st.warning("Vendor not found.")
            return
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
            st.caption("From this vendor’s generated report — header, footprint, and ingestion summary only.")
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


def render_admin_operator(
    db_path: Path,
    vendors_yaml: Path,
    exports_dir: Path,
) -> None:
    st.subheader("Admin / Operator")
    st.caption("CLI parity: paths (sidebar), ingest, score, exports, and operation log.")
    if st.session_state.pop("admin_highlight_sync", None):
        st.success("Use **Sync vendors from YAML** below after editing your config.")

    if st.button("Sync vendors from YAML", type="primary", key="admin_sync"):
        exports_dir.mkdir(parents=True, exist_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        code = _run_cli(["vendors", "sync", "--config", str(vendors_yaml), "--db", str(db_path)])
        if code == 0:
            st.success("Sync completed.")
        else:
            st.error("Sync failed — see log.")

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
            "Select vendor",
            options=names if names else ["(sync vendors first)"],
            disabled=not names,
            key="admin_vendor_select",
        )
        disabled_run = not names or vendor == "(sync vendors first)"

        st.markdown("##### Advanced crawl (optional)")
        c1, c2, c3 = st.columns(3)
        with c1:
            max_pages_in = st.text_input("Max pages", placeholder="default 40", key="admin_max_pages")
        with c2:
            max_depth_in = st.text_input("Max depth", placeholder="default 2", key="admin_max_depth")
        with c3:
            delay_in = st.text_input("Delay (seconds)", placeholder="default 0.75", key="admin_delay")

        st.markdown("##### Scoring")
        score_after_run = st.checkbox(
            "Score after run (for **Run + score**; enables `--score`)",
            value=True,
            key="admin_score_after",
        )
        all_evidence_when_scoring = st.checkbox(
            "All evidence when scoring (`--all-evidence`)",
            value=False,
            key="admin_all_evidence",
        )

        st.markdown("##### Actions")
        b1, b2, b3, b4 = st.columns(4)
        max_pages = _optional_int(max_pages_in)
        max_depth = _optional_int(max_depth_in)
        delay = _optional_float(delay_in)

        with b1:
            if st.button("Run ingest", disabled=disabled_run, key="admin_run_ingest"):
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
                code = _run_cli(args)
                st.success("Ingest finished.") if code == 0 else st.error("Ingest failed — see log.")

        with b2:
            if st.button("Run + score", disabled=disabled_run, key="admin_run_score"):
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
                code = _run_cli(args)
                st.success("Run + score finished.") if code == 0 else st.error("Run + score failed — see log.")

        with b3:
            if st.button("Export scorecard", disabled=disabled_run, key="admin_export_scorecard"):
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
                st.success("Scorecard exported.") if code == 0 else st.error("Export failed — see log.")

        with b4:
            if st.button("Export report", disabled=disabled_run, key="admin_export_report"):
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
                st.success("Report exported.") if code == 0 else st.error("Export failed — see log.")

        st.markdown("##### Output / log")
        if st.button("Clear log", key="admin_clear_log"):
            st.session_state.log_lines = []
        log_text = "\n".join(st.session_state.get("log_lines", []))
        st.code(log_text or "(no output yet)", language="bash")

    with col_side:
        render_latest_score_panel(db_path, vendor, disabled_run=disabled_run)


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

    tab_intel, tab_admin = st.tabs(["Vendor Intelligence", "Admin / Operator"])
    with tab_intel:
        render_vendor_intelligence(db_path, vendors_yaml)
    with tab_admin:
        render_admin_operator(db_path, vendors_yaml, exports_dir)


if __name__ == "__main__":
    main()
