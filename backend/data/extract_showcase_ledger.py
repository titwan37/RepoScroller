#!/usr/bin/env python3
"""
RepoScroller Showcase Ledger Slicer
Extracts a self-contained showcase slice from reposcroller_ledger.db
or preserves an existing reposcroller_showcase.db.
"""

import sqlite3
import os
import sys

SOURCE_DB = "reposcroller_ledger.db"
TARGET_DB = "reposcroller_showcase.db"
# SAMPLE_DOC_LIMIT = 500  # Set to ~500-1000 for a compact ~2MB - 10MB footprint
SAMPLE_DOC_LIMIT = 1250  # 1/4th of previous limit (5000 -> 1250)


def get_table_names(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, type, sql FROM sqlite_master WHERE type IN ('table', 'index', 'view', 'trigger') AND name NOT LIKE 'sqlite_%';")
    return cur.fetchall()


def build_showcase():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_db_path = os.path.join(script_dir, SOURCE_DB)
    target_db_path = os.path.join(script_dir, TARGET_DB)

    # If the full 7GB ledger is not on this machine, check if the showcase DB is already present
    if not os.path.exists(source_db_path):
        if os.path.exists(target_db_path):
            size_mb = os.path.getsize(target_db_path) / (1024**2)
            print(f"[INFO] '{SOURCE_DB}' not found, but pre-existing '{TARGET_DB}' ({size_mb:.2f} MB) is ready. Skipping generation.")
            sys.exit(0)
        else:
            print(f"[ERROR] Neither '{source_db_path}' nor '{target_db_path}' exists. Cannot prepare showcase data.")
            sys.exit(1)

    print(f"[*] Reading full ledger from: {source_db_path} ({os.path.getsize(source_db_path) / (1024**3):.2f} GB)")

    if os.path.exists(target_db_path):
        os.remove(target_db_path)

    src = sqlite3.connect(source_db_path)
    dst = sqlite3.connect(target_db_path)

    dst.execute("PRAGMA journal_mode = OFF;")
    dst.execute("PRAGMA synchronous = OFF;")

    src_cur = src.cursor()
    dst_cur = dst.cursor()

    # 1. Clone Schema DDL
    print("[*] Replicating database schema and indexes...")
    schema_objects = get_table_names(src)
    for obj_name, obj_type, sql in schema_objects:
        if sql and not obj_name.endswith(('_fts_idx', '_docsize', '_config', '_data', '_idx', '_content')):
            try:
                dst_cur.execute(sql)
            except Exception:
                pass
    dst.commit()

    # 2. Select Anchor Document SHA-256 Hashes
    print(f"[*] Selecting top {SAMPLE_DOC_LIMIT} showcase document records...")
    query_anchors = f"""
        SELECT sha256_hash FROM document_ledger
        ORDER BY 
            maturity_score DESC,
            doc_date DESC,
            created_at DESC
        LIMIT {SAMPLE_DOC_LIMIT};
    """
    src_cur.execute(query_anchors)
    selected_shas = [row[0] for row in src_cur.fetchall()]
    print(f"[+] Selected {len(selected_shas)} core anchor documents.")

    src_cur.execute("CREATE TEMP TABLE target_doc_shas (sha256_hash TEXT PRIMARY KEY);")
    src_cur.executemany("INSERT INTO temp.target_doc_shas (sha256_hash) VALUES (?);", [(s,) for s in selected_shas])
    src.commit()

    # 3. Copy Filtered Tables
    tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';").fetchall()]

    for tbl in tables:
        if any(tbl.endswith(sfx) for sfx in ['_segments', '_segdir', '_stat', '_idx', '_data', '_config', '_content', '_docsize']):
            continue

        col_info = src.execute(f"PRAGMA table_info({tbl});").fetchall()
        col_names = [c[1] for c in col_info]
        placeholders = ",".join(["?"] * len(col_names))

        if tbl == "document_ledger":
            src_cur.execute("SELECT * FROM document_ledger WHERE sha256_hash IN (SELECT sha256_hash FROM temp.target_doc_shas)")
        elif tbl == "document_fts":
            src_cur.execute("SELECT * FROM document_fts WHERE sha256_hash IN (SELECT sha256_hash FROM temp.target_doc_shas)")
        elif tbl == "version_chains":
            src_cur.execute("""
                SELECT * FROM version_chains 
                WHERE parent_sha256 IN (SELECT sha256_hash FROM temp.target_doc_shas)
                   OR child_sha256 IN (SELECT sha256_hash FROM temp.target_doc_shas)
            """)
        elif "sha256_hash" in col_names:
            src_cur.execute(f"SELECT * FROM {tbl} WHERE sha256_hash IN (SELECT sha256_hash FROM temp.target_doc_shas)")
        elif tbl in ("knowledge_nodes", "knowledge_edges"):
            src_cur.execute(f"SELECT * FROM {tbl} LIMIT 3000;")
        else:
            src_cur.execute(f"SELECT * FROM {tbl} LIMIT 1000;")

        rows = src_cur.fetchall()
        if rows:
            dst_cur.executemany(f"INSERT OR IGNORE INTO {tbl} VALUES ({placeholders})", rows)
            dst.commit()

    src_cur.execute("DROP TABLE IF EXISTS temp.target_doc_shas;")
    src.close()

    print("[*] Compacting database and setting WAL mode...")
    dst.execute("PRAGMA journal_mode = WAL;")
    dst.execute("VACUUM;")
    dst.close()

    final_size_mb = os.path.getsize(target_db_path) / (1024**2)
    print(f"\n[SUCCESS] Showcase database created: {target_db_path} ({final_size_mb:.2f} MB)")


if __name__ == "__main__":
    build_showcase()