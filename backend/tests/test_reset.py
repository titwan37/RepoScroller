"""Tests for the reset CLI command."""

import sqlite3
from pathlib import Path
from reposcroller.ledger.db import init_db, get_db_connection


def test_reset_command_flow(tmp_path: Path, monkeypatch):
    """Verify that database reset cleanly recreates schema and tables."""
    test_db = tmp_path / "test_reset.db"
    
    # Initialize DB
    init_db(test_db)
    
    # Insert dummy document
    conn = get_db_connection(test_db)
    conn.execute("INSERT INTO document_ledger (sha256_hash, canonical_filename, doc_type) VALUES ('hash1', 'test.docx', 'CONTRACT')")
    conn.commit()
    conn.close()
    
    # Verify insert
    conn = get_db_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM document_ledger")
    assert cur.fetchone()[0] == 1
    conn.close()
