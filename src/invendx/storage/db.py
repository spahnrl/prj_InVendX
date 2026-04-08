from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


def connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA user_version")
    version = cur.fetchone()[0]
    if version >= SCHEMA_VERSION:
        return

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS vendors (
            vendor_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            primary_domain TEXT NOT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            seed_urls_json TEXT NOT NULL DEFAULT '{}',
            primary_segment TEXT NOT NULL DEFAULT '',
            github_org TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(canonical_name, primary_domain)
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            vendor_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
        );

        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            vendor_id TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            run_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_date TEXT,
            source_title TEXT,
            evidence_type TEXT NOT NULL,
            product_area TEXT,
            entity_1 TEXT,
            entity_2 TEXT,
            claim_text TEXT NOT NULL,
            confidence TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '',
            score_impact_category TEXT,
            raw_text_excerpt TEXT,
            parser_version TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            dedupe_hash TEXT,
            FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_evidence_vendor ON evidence(vendor_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence(run_id);

        CREATE TABLE IF NOT EXISTS score_runs (
            score_run_id TEXT PRIMARY KEY,
            vendor_id TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ruleset_version TEXT NOT NULL,
            FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
        );

        CREATE TABLE IF NOT EXISTS score_line_items (
            line_id TEXT PRIMARY KEY,
            score_run_id TEXT NOT NULL,
            category TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            points REAL NOT NULL,
            rationale TEXT,
            evidence_ids_json TEXT NOT NULL,
            FOREIGN KEY (score_run_id) REFERENCES score_runs(score_run_id)
        );

        CREATE TABLE IF NOT EXISTS vendor_summaries (
            vendor_id TEXT PRIMARY KEY,
            source_count INTEGER NOT NULL,
            evidence_count INTEGER NOT NULL,
            last_evidence_at TEXT,
            confidence_rollup REAL NOT NULL,
            profile_metrics_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
        );
        """
    )
    cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
