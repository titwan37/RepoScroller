"""Database connection management and initialization with SQLite WAL mode."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Generator
from reposcroller.config import settings
from reposcroller.ledger.schema import SCHEMA_SQL


def get_db_connection(db_path: Path = None) -> sqlite3.Connection:
    """Create and configure a SQLite connection with WAL journal mode."""
    target_path = db_path or settings.DB_PATH
    if target_path != Path(":memory:"):
        target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(target_path),
        timeout=settings.SQLITE_TIMEOUT,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA encoding = 'UTF-8';")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path = None) -> None:
    """Execute DDL statements to initialize all tables, indices, and FTS5 structures."""
    conn = get_db_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    """Provide a transactional cursor context manager."""
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
