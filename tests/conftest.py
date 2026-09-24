"""Pytest fixtures for temporary databases, sample documents, and test environment."""

import pytest
import sqlite3
from pathlib import Path
from reposcroller.ledger.db import get_db_connection, init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.integrity.maturity import MaturityEvaluator
from reposcroller.core.synchronizer import DocumentSynchronizer


@pytest.fixture
def temp_db(tmp_path: Path):
    """Provides a fresh SQLite database initialized with the full schema."""
    db_file = tmp_path / "test_ledger.db"
    init_db(db_file)
    conn = get_db_connection(db_file)
    yield conn
    conn.close()


@pytest.fixture
def repo(temp_db: sqlite3.Connection):
    """Provides a DocumentRepository bound to the test database."""
    return DocumentRepository(conn=temp_db)


@pytest.fixture
def synchronizer(repo: DocumentRepository):
    """Provides a DocumentSynchronizer using the test repository."""
    evaluator = MaturityEvaluator()
    return DocumentSynchronizer(repository=repo, maturity_evaluator=evaluator)


@pytest.fixture
def sample_files(tmp_path: Path):
    """Creates a realistic set of test documents (draft, final signed, truncated, exact duplicate)."""
    root_a = tmp_path / "storage_root_a"
    root_b = tmp_path / "storage_root_b"
    root_a.mkdir()
    root_b.mkdir()

    # 1. Final signed contract in root_a
    contract_final = root_a / "Contract_Acme_2024_signed.txt"
    contract_final.write_text(
        "Agreement between Alice and Bob.\nTerms and conditions.\nSigned: Alice and Bob.\nDate: 2024-05-15\nUnterschrift: Alice\nQualifizierte elektronische Signatur.",
        encoding="utf-8"
    )

    # 2. Draft contract in root_b (similar text, but draft)
    contract_draft = root_b / "Contract_Acme_2024_draft.txt"
    contract_draft.write_text(
        "Agreement between Alice and Bob.\nTerms and conditions.\n[Draft for review]\nDate: 2024-05-10",
        encoding="utf-8"
    )

    # 3. Exact bitwise copy of the final contract in root_b (different folder!)
    contract_copy = root_b / "Contract_Acme_2024_backup.txt"
    contract_copy.write_bytes(contract_final.read_bytes())

    # 4. Truncated document
    contract_truncated = root_a / "Contract_Acme_partial.txt"
    contract_truncated.write_text(
        "Agreement between Alice and Bob... [cut] [truncated]",
        encoding="utf-8"
    )

    return {
        "root_a": str(root_a),
        "root_b": str(root_b),
        "final": contract_final,
        "draft": contract_draft,
        "copy": contract_copy,
        "truncated": contract_truncated,
    }
