"""Database connection management and initialization with SQLite WAL mode."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Generator
import logging
# pyrefly: ignore [missing-import]
from backend.config import settings
from .schema import SCHEMA_SQL


logger = logging.getLogger("reposcroller.db")

def resolve_ledger_db_path(configured_path: Path = None) -> Path:
    """Resolve the active database path."""
    if configured_path:
        return configured_path
        
    target = settings.DB_PATH
    if target == Path(":memory:"):
        return target

    if target.exists():
        return target

    # Fallback 1: Look for showcase db in the same parent folder
    showcase_path = target.parent / "reposcroller_showcase.db"
    if showcase_path.exists():
        logger.info("Primary ledger not found at %s. Falling back to showcase slice: %s", target, showcase_path)
        return showcase_path

    # Fallback 2: Look in backend/data/ directory
    data_dir_showcase = target.parent / "data" / "reposcroller_showcase.db"
    if data_dir_showcase.exists():
        logger.info("Primary ledger not found. Using showcase database from backend.data directory: %s", data_dir_showcase)
        return data_dir_showcase

    # Fallback 3: Look relative to current working directory
    cwd_showcase = Path("reposcroller_showcase.db")
    if cwd_showcase.exists():
        return cwd_showcase.absolute()

    cwd_data_showcase = Path("backend/data/reposcroller_showcase.db")
    if cwd_data_showcase.exists():
        return cwd_data_showcase.absolute()

    return target

def get_db_connection(db_path: Path = None) -> sqlite3.Connection:
    """Create and configure a SQLite connection with WAL journal mode."""
    target_path = resolve_ledger_db_path(db_path)
    if target_path != Path(":memory:") and str(target_path) != ":memory:":
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
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# def init_db(db_path: Path = None) -> None:
#     """Execute DDL statements to initialize all tables, indices, and FTS5 structures."""
#     conn = get_db_connection(db_path)
#     try:
#         conn.executescript(SCHEMA_SQL)
#         conn.commit()
#     finally:
#         conn.close()


def init_db(db_path: Path = None) -> None:
    """Execute DDL statements only if tables do not already exist."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_ledger';")
        if not cur.fetchone():
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
