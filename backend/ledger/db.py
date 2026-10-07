"""Database connection management and initialization with SQLite WAL mode."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, Optional
import logging
# pyrefly: ignore [missing-import]
from backend.config import settings
from .schema import SCHEMA_SQL


logger = logging.getLogger("reposcroller.db")

def _is_valid_ledger_db(path: Optional[Path]) -> bool:
    """Verify that a path exists, has substantial data (>4KB), and contains the core document_ledger table."""
    if not path:
        return False
    p = Path(path)
    if not p.exists():
        return False
    try:
        # 4096 bytes is just the empty SQLite file header
        if p.stat().st_size <= 4096:
            return False
        conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_ledger';")
            return cur.fetchone() is not None
        finally:
            conn.close()
    except Exception:
        return False


_last_logged_resolved_path: Optional[Path] = None


def resolve_ledger_db_path(configured_path: Path = None) -> Path:
    """Resolve the active database path.
    
    If an explicit custom path (different from settings.DB_PATH) is provided,
    it is honored directly (e.g. for unit tests or temporary databases).
    
    If no path is provided, or the default settings.DB_PATH is requested:
    checks if settings.DB_PATH exists and is a valid populated database.
    If not, it automatically falls back to reposcroller_showcase.db.
    """
    global _last_logged_resolved_path

    if configured_path and configured_path != settings.DB_PATH:
        return Path(configured_path)

    target = settings.DB_PATH
    if target == Path(":memory:") or str(target) == ":memory:":
        return target

    if _is_valid_ledger_db(target):
        _last_logged_resolved_path = target
        return target

    def _select_fallback(path: Path, msg: str) -> Path:
        global _last_logged_resolved_path
        if _last_logged_resolved_path != path:
            logger.info(msg)
            _last_logged_resolved_path = path
        return path

    # Fallback 1: Look for showcase db in the same parent folder
    showcase_path = target.parent / "reposcroller_showcase.db"
    if _is_valid_ledger_db(showcase_path):
        return _select_fallback(
            showcase_path,
            f"Primary ledger not found or empty at {target}. Falling back to showcase slice: {showcase_path}"
        )

    # Fallback 2: Look in backend/data/ directory
    data_dir_showcase = target.parent / "data" / "reposcroller_showcase.db"
    if _is_valid_ledger_db(data_dir_showcase):
        return _select_fallback(
            data_dir_showcase,
            f"Primary ledger not found. Using showcase database from backend/data: {data_dir_showcase}"
        )

    # Fallback 3: Look relative to current working directory
    cwd_showcase = Path("reposcroller_showcase.db").absolute()
    if _is_valid_ledger_db(cwd_showcase):
        return _select_fallback(cwd_showcase, f"Using showcase database from current working directory: {cwd_showcase}")

    cwd_data_showcase = Path("backend/data/reposcroller_showcase.db").absolute()
    if _is_valid_ledger_db(cwd_data_showcase):
        return _select_fallback(cwd_data_showcase, f"Using showcase database from backend/data: {cwd_data_showcase}")

    # Fallback 4: Look relative to project root
    root_data_showcase = Path(__file__).resolve().parent.parent / "data" / "reposcroller_showcase.db"
    if _is_valid_ledger_db(root_data_showcase):
        return _select_fallback(root_data_showcase, f"Using showcase database from project root: {root_data_showcase}")

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
    """Execute DDL statements to ensure all schema tables, indices, and structures exist."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(document_ledger)")
        columns = [row["name"] for row in cur.fetchall()]
        if columns:
            if "reception_date" not in columns:
                try:
                    cur.execute("ALTER TABLE document_ledger ADD COLUMN reception_date TEXT;")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
            if "due_date" not in columns:
                try:
                    cur.execute("ALTER TABLE document_ledger ADD COLUMN due_date TEXT;")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
        
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
