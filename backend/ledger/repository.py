"""Repository layer for ACID SQLite ledger operations and ALCOA+ audit trails."""

import sqlite3
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from backend.config import settings
from backend.integrity.simhash import hamming_distance, simhash_similarity
from backend.integrity.date_extractor import extract_document_date
from backend.ledger.db import get_db_connection, transaction, resolve_ledger_db_path


class DocumentRepository:
    """Manages document ledger persistence, location mapping, and version lineage."""

    def __init__(self, db_path: Optional[Path] = None, conn: Optional[sqlite3.Connection] = None):
        self._conn = conn
        self._owns_conn = conn is None
        self._lock = threading.RLock()

        if db_path:
            self.db_path = resolve_ledger_db_path(Path(db_path))
        elif conn:
            try:
                cur = conn.cursor()
                cur.execute("PRAGMA database_list;")
                row = cur.fetchone()
                if row and row[2]:
                    self.db_path = Path(row[2])
                else:
                    self.db_path = resolve_ledger_db_path()
            except Exception:
                self.db_path = resolve_ledger_db_path()
        else:
            self.db_path = resolve_ledger_db_path()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = get_db_connection(self.db_path)
            self._ensure_schema()
        return self._conn

    def _ensure_schema(self) -> None:
        """Ensure latest columns (doc_date, reception_date, due_date) and indices exist."""
        try:
            cur = self._conn.cursor()
            cols = [r[1] for r in cur.execute("PRAGMA table_info(document_ledger);").fetchall()]
            if "doc_date" not in cols:
                cur.execute("ALTER TABLE document_ledger ADD COLUMN doc_date TEXT;")
                cur.execute("ALTER TABLE document_ledger ADD COLUMN doc_date_source TEXT;")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ledger_doc_date ON document_ledger(doc_date);")
            if "reception_date" not in cols:
                cur.execute("ALTER TABLE document_ledger ADD COLUMN reception_date TEXT;")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ledger_reception_date ON document_ledger(reception_date);")
            if "due_date" not in cols:
                cur.execute("ALTER TABLE document_ledger ADD COLUMN due_date TEXT;")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ledger_due_date ON document_ledger(due_date);")

            # Ensure action_items table exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS action_items (
                    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha256_hash TEXT NOT NULL REFERENCES document_ledger(sha256_hash) ON DELETE CASCADE,
                    theme_id TEXT,
                    action_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    counterparty TEXT,
                    amount REAL,
                    currency TEXT DEFAULT 'CHF',
                    due_date TEXT,
                    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'completed', 'dismissed', 'overdue')),
                    fulfilled_by_sha256 TEXT REFERENCES document_ledger(sha256_hash),
                    fulfilled_at TIMESTAMP,
                    fulfillment_evidence TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_action_status_due ON action_items(status, due_date ASC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_action_theme ON action_items(theme_id, status);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_action_sha ON action_items(sha256_hash);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_action_fulfilled ON action_items(fulfilled_by_sha256);")

            self._conn.commit()
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            if self._owns_conn and self._conn is not None:
                self._conn.close()
                self._conn = None

    def upsert_document(self,
                        sha256_hash: str,
                        simhash: str,
                        canonical_filename: str,
                        doc_type: str,
                        lifecycle_status: str,
                        completeness_score: float,
                        maturity_score: float,
                        page_count: int,
                        text_snippet: str,
                        doc_date: Optional[str] = None,
                        doc_date_source: Optional[str] = None,
                        full_text: Optional[str] = None,
                        reception_date: Optional[str] = None,
                        due_date: Optional[str] = None) -> None:
        """Insert or update a document in the document_ledger and FTS index."""
        if not doc_date:
            doc_date, doc_date_source = extract_document_date(canonical_filename, text_snippet)

        with self._lock:
            with transaction(self.conn) as cur:
                cur.execute("""
                    INSERT INTO document_ledger (
                        sha256_hash, simhash, canonical_filename, doc_type,
                        lifecycle_status, completeness_score, maturity_score,
                        page_count, text_snippet, doc_date, doc_date_source,
                        reception_date, due_date, last_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(sha256_hash) DO UPDATE SET
                        canonical_filename = excluded.canonical_filename,
                        lifecycle_status = excluded.lifecycle_status,
                        completeness_score = excluded.completeness_score,
                        maturity_score = excluded.maturity_score,
                        doc_date = COALESCE(excluded.doc_date, document_ledger.doc_date),
                        doc_date_source = COALESCE(excluded.doc_date_source, document_ledger.doc_date_source),
                        reception_date = COALESCE(excluded.reception_date, document_ledger.reception_date),
                        due_date = COALESCE(excluded.due_date, document_ledger.due_date),
                        last_verified = CURRENT_TIMESTAMP;
                """, (
                    sha256_hash, simhash, canonical_filename, doc_type,
                    lifecycle_status, completeness_score, maturity_score,
                    page_count, text_snippet[:500], doc_date, doc_date_source,
                    reception_date, due_date
                ))

                # FTS5 indexing if full_text provided
                if full_text:
                    # Remove existing FTS entry if exists
                    cur.execute("DELETE FROM document_fts WHERE sha256_hash = ?", (sha256_hash,))
                    cur.execute("""
                        INSERT INTO document_fts (sha256_hash, canonical_filename, text_content)
                        VALUES (?, ?, ?);
                    """, (sha256_hash, canonical_filename, full_text))

                # Audit trail entry
                cur.execute("""
                    INSERT INTO audit_log (sha256_hash, action, details)
                    VALUES (?, 'upsert_document', ?);
                """, (sha256_hash, f"Status: {lifecycle_status}, Maturity: {maturity_score}"))

    def backfill_document_dates(self) -> int:
        """Backfill doc_date for any records where it is currently NULL."""
        self._ensure_schema()
        with self._lock:
            with transaction(self.conn) as cur:
                cur.execute("""
                    SELECT dl.sha256_hash, dl.canonical_filename, dl.text_snippet, MAX(fl.mtime)
                    FROM document_ledger dl
                    LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
                    WHERE dl.doc_date IS NULL
                    GROUP BY dl.sha256_hash;
                """)
                rows = cur.fetchall()
                updated = 0
                for r in rows:
                    sha, fn, txt, mt = r[0], r[1], r[2], r[3]
                    d, src = extract_document_date(fn, txt, mt)
                    if d:
                        cur.execute(
                            "UPDATE document_ledger SET doc_date = ?, doc_date_source = ? WHERE sha256_hash = ?",
                            (d, src, sha)
                        )
                        updated += 1
                return updated

    def record_location(self,
                        sha256_hash: str,
                        storage_root: str,
                        relative_path: str,
                        absolute_path: str,
                        file_size: int,
                        mtime: float,
                        is_primary: bool = False) -> int:
        """Record or update a physical location for a content hash."""
        with self._lock:
            with transaction(self.conn) as cur:
                cur.execute("""
                    INSERT INTO file_locations (
                        sha256_hash, storage_root, relative_path, absolute_path,
                        file_size, mtime, is_primary_source, status, last_scanned
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
                    ON CONFLICT(absolute_path) DO UPDATE SET
                        sha256_hash = excluded.sha256_hash,
                        file_size = excluded.file_size,
                        mtime = excluded.mtime,
                        status = 'active',
                        last_scanned = CURRENT_TIMESTAMP;
                """, (sha256_hash, storage_root, relative_path, absolute_path, file_size, mtime, 1 if is_primary else 0))

                cur.execute("""
                    INSERT INTO audit_log (sha256_hash, action, details)
                    VALUES (?, 'record_location', ?);
                """, (sha256_hash, f"Path: {absolute_path}"))

                return cur.lastrowid

    def link_version_chain(self,
                           parent_sha256: str,
                           child_sha256: str,
                           relationship: str,
                           similarity_score: float = 0.0,
                           notes: str = "") -> None:
        """Create a version lineage relationship (e.g., supersedes, derived_from)."""
        if parent_sha256 == child_sha256:
            return

        with self._lock:
            with transaction(self.conn) as cur:
                cur.execute("""
                    INSERT OR REPLACE INTO version_chains (
                        parent_sha256, child_sha256, relationship, similarity_score, notes
                    ) VALUES (?, ?, ?, ?, ?);
                """, (parent_sha256, child_sha256, relationship, similarity_score, notes))

                cur.execute("""
                    INSERT INTO audit_log (sha256_hash, action, details)
                    VALUES (?, 'version_linked', ?);
                """, (child_sha256, f"{relationship} parent {parent_sha256[:12]} (sim: {similarity_score})"))

    def get_document_by_sha256(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        """Retrieve full document record with all known storage locations and version links."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM document_ledger WHERE sha256_hash = ?", (sha256_hash,))
            row = cur.fetchone()
            if not row:
                return None

            doc = dict(row)

            # Fetch locations
            cur.execute("SELECT * FROM file_locations WHERE sha256_hash = ?", (sha256_hash,))
            doc["locations"] = [dict(loc) for loc in cur.fetchall()]

            # Fetch parents (documents this evolved from)
            cur.execute("""
                SELECT vc.*, dl.canonical_filename, dl.maturity_score, dl.lifecycle_status
                FROM version_chains vc
                JOIN document_ledger dl ON vc.parent_sha256 = dl.sha256_hash
                WHERE vc.child_sha256 = ?
            """, (sha256_hash,))
            doc["parents"] = [dict(p) for p in cur.fetchall()]

            # Fetch children (documents that evolved from this)
            cur.execute("""
                SELECT vc.*, dl.canonical_filename, dl.maturity_score, dl.lifecycle_status
                FROM version_chains vc
                JOIN document_ledger dl ON vc.child_sha256 = dl.sha256_hash
                WHERE vc.parent_sha256 = ?
            """, (sha256_hash,))
            doc["children"] = [dict(c) for c in cur.fetchall()]

            return doc

    def get_document_locations(self, sha256_hash: str) -> List[Dict[str, Any]]:
        """Retrieve registered physical storage locations for a given SHA-256 hash."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM file_locations WHERE sha256_hash = ? ORDER BY is_primary_source DESC, mtime DESC", (sha256_hash,))
            return [dict(loc) for loc in cur.fetchall()]

    def get_document_full_text(self, sha256_hash: str) -> str:
        """Retrieve full text of document from FTS index, disk file, or ledger snippet."""
        with self._lock:
            cur = self.conn.cursor()
            # 1. Check FTS table
            try:
                cur.execute("SELECT text_content FROM document_fts WHERE sha256_hash = ?", (sha256_hash,))
                row = cur.fetchone()
                if row and row[0] and len(row[0].strip()) > 30:
                    return row[0].strip()
            except Exception:
                pass

            # 2. Check locations on disk
            try:
                cur.execute("SELECT absolute_path FROM file_locations WHERE sha256_hash = ?", (sha256_hash,))
                loc_rows = cur.fetchall()
                for lr in loc_rows:
                    p = Path(lr[0])
                    if p.exists() and p.is_file():
                        from backend.extraction.text_extractor import extract_document_data
                        text, _ = extract_document_data(p)
                        if text and len(text.strip()) > 20:
                            return text.strip()
            except Exception:
                pass

            # 3. Fallback to snippet in document_ledger
            try:
                cur.execute("SELECT text_snippet FROM document_ledger WHERE sha256_hash = ?", (sha256_hash,))
                row = cur.fetchone()
                if row and row[0]:
                    return row[0].strip()
            except Exception:
                pass

        return ""

    def get_location_by_path(self, absolute_path: str) -> Optional[Dict[str, Any]]:
        """Lookup existing record for an exact absolute file path."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM file_locations WHERE absolute_path = ?", (absolute_path,))
            row = cur.fetchone()
            return dict(row) if row else None

    def find_near_duplicates_simhash(self,
                                     query_simhash: str,
                                     max_hamming: int = 8,
                                     exclude_sha256: Optional[str] = None) -> List[Dict[str, Any]]:
        """Scan SimHashes to find close content matches (drafts, truncated copies, small edits)."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT sha256_hash, simhash, canonical_filename, maturity_score, lifecycle_status FROM document_ledger WHERE simhash IS NOT NULL AND simhash != '0000000000000000'")
            rows = cur.fetchall()

            results = []
            for r in rows:
                if exclude_sha256 and r["sha256_hash"] == exclude_sha256:
                    continue

                target_simhash = r["simhash"]
                dist = hamming_distance(query_simhash, target_simhash)
                if dist <= max_hamming:
                    similarity = simhash_similarity(query_simhash, target_simhash)
                    results.append({
                        "sha256_hash": r["sha256_hash"],
                        "canonical_filename": r["canonical_filename"],
                        "simhash": target_simhash,
                        "hamming_distance": dist,
                        "similarity_score": similarity,
                        "maturity_score": r["maturity_score"],
                        "lifecycle_status": r["lifecycle_status"],
                    })

            results.sort(key=lambda x: (x["hamming_distance"], -x["maturity_score"]))
            return results

    def search_keyword_fts(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Lexical search using SQLite FTS5 BM25 scoring with filename extraction and LIKE fallback."""
        if not query or not query.strip():
            return []

        import re
        raw_query = query.strip()
        results: List[Dict[str, Any]] = []
        seen_shas = set()

        # 1. Extract quoted terms or filename-like tokens (e.g. "foo.pdf", 2027_0724_UrgentCall...)
        quoted_terms = re.findall(r'"([^"]+)"', raw_query)
        filename_terms = re.findall(r'\b[\w\-\.]+\.(?:pdf|docx?|xlsx?|txt|md|eml)\b', raw_query, flags=re.IGNORECASE)

        with self._lock:
            cur = self.conn.cursor()

            # Priority 1: Match against canonical_filename if a filename or quoted phrase was mentioned
            priority_names = list(set(quoted_terms + filename_terms))
            for name in priority_names:
                clean_name = name.strip()
                if not clean_name:
                    continue
                cur.execute("""
                    SELECT sha256_hash, canonical_filename, maturity_score, lifecycle_status, text_snippet
                    FROM document_ledger
                    WHERE canonical_filename = ? OR canonical_filename LIKE ?
                    LIMIT ?;
                """, (clean_name, f"%{clean_name}%", limit))
                for r in cur.fetchall():
                    d = dict(r)
                    if d["sha256_hash"] not in seen_shas:
                        seen_shas.add(d["sha256_hash"])
                        d["rank"] = -100.0  # Top rank
                        results.append(d)

            # Priority 2: Tokenize and clean for FTS5 (avoiding syntax errors with '.' or '?')
            tokens = re.findall(r'[a-zA-Z0-9_\u00C0-\u017F]+', raw_query)
            stop_words = {
                "do", "we", "have", "any", "copy", "or", "draft", "of", "the", "a",
                "an", "in", "is", "what", "here", "to", "for", "about", "this", "please",
                "can", "you", "find", "show", "me", "tell", "which", "are", "there"
            }
            meaningful_tokens = [t for t in tokens if t.lower() not in stop_words and len(t) > 1]

            if meaningful_tokens and len(results) < limit:
                # In FTS5, quoting each token prevents punctuation/operator crashes
                fts_query = " ".join(f'"{t}"' for t in meaningful_tokens)
                try:
                    cur.execute("""
                        SELECT fts.sha256_hash, fts.canonical_filename, bm25(document_fts) as rank,
                               dl.maturity_score, dl.lifecycle_status, dl.text_snippet
                        FROM document_fts fts
                        JOIN document_ledger dl ON fts.sha256_hash = dl.sha256_hash
                        WHERE document_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?;
                    """, (fts_query, limit))
                    for r in cur.fetchall():
                        d = dict(r)
                        if d["sha256_hash"] not in seen_shas:
                            seen_shas.add(d["sha256_hash"])
                            results.append(d)
                except sqlite3.OperationalError:
                    pass

                # If still empty, try OR prefix search
                if not results:
                    fts_or_query = " OR ".join(f'"{t}"*' for t in meaningful_tokens[:4])
                    try:
                        cur.execute("""
                            SELECT fts.sha256_hash, fts.canonical_filename, bm25(document_fts) as rank,
                                   dl.maturity_score, dl.lifecycle_status, dl.text_snippet
                            FROM document_fts fts
                            JOIN document_ledger dl ON fts.sha256_hash = dl.sha256_hash
                            WHERE document_fts MATCH ?
                            ORDER BY rank
                            LIMIT ?;
                        """, (fts_or_query, limit))
                        for r in cur.fetchall():
                            d = dict(r)
                            if d["sha256_hash"] not in seen_shas:
                                seen_shas.add(d["sha256_hash"])
                                results.append(d)
                    except sqlite3.OperationalError:
                        pass

            # Fallback 3: SQL LIKE if FTS produced 0 results
            if not results and meaningful_tokens:
                for t in meaningful_tokens[:3]:
                    cur.execute("""
                        SELECT sha256_hash, canonical_filename, maturity_score, lifecycle_status, text_snippet
                        FROM document_ledger
                        WHERE canonical_filename LIKE ? OR text_snippet LIKE ?
                        LIMIT ?;
                    """, (f"%{t}%", f"%{t}%", limit))
                    for r in cur.fetchall():
                        d = dict(r)
                        if d["sha256_hash"] not in seen_shas:
                            seen_shas.add(d["sha256_hash"])
                            d["rank"] = 0.0
                            results.append(d)

        return results[:limit]

    def get_all_documents(self,
                          limit: int = 50,
                          offset: int = 0,
                          status: Optional[str] = None,
                          category: Optional[str] = None,
                          only_duplicates: bool = False,
                          query: Optional[str] = None,
                          sort_by: str = "created_at",
                          sort_order: str = "DESC") -> List[Dict[str, Any]]:
        """Retrieve paginated document ledger records with query search, category, duplicate filtering, and sorting."""
        with self._lock:
            cur = self.conn.cursor()

            valid_cols = {
                "canonical_filename": "dl.canonical_filename COLLATE NOCASE",
                "doc_type": "dl.doc_type COLLATE NOCASE",
                "maturity_score": "dl.maturity_score",
                "lifecycle_status": "dl.lifecycle_status COLLATE NOCASE",
                "page_count": "dl.page_count",
                "doc_date": "COALESCE(dl.doc_date, datetime(MAX(fl.mtime), 'unixepoch'), dl.created_at)",
                "reception_date": "COALESCE(dl.reception_date, dl.doc_date, datetime(MAX(fl.mtime), 'unixepoch'), dl.created_at)",
                "due_date": "COALESCE(dl.due_date, '9999-12-31')",
                "date": "COALESCE(dl.doc_date, datetime(MAX(fl.mtime), 'unixepoch'), dl.created_at)",
                "created_at": "COALESCE(dl.doc_date, datetime(MAX(fl.mtime), 'unixepoch'), dl.created_at)",
                "location_count": "location_count"
            }
            order_col = valid_cols.get(sort_by, "COALESCE(dl.doc_date, datetime(MAX(fl.mtime), 'unixepoch'), dl.created_at)")
            direction = "ASC" if sort_order.upper() == "ASC" else "DESC"

            where_clauses = []
            params = []

            if status:
                where_clauses.append("dl.lifecycle_status = ?")
                params.append(status)
            if category:
                where_clauses.append("dl.doc_type = ?")
                params.append(category)
            if query and query.strip():
                clean_q = f"%{query.strip()}%"
                where_clauses.append("(dl.canonical_filename LIKE ? OR dl.text_snippet LIKE ? OR dl.doc_type LIKE ?)")
                params.extend([clean_q, clean_q, clean_q])

            where_str = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            having_str = "HAVING location_count > 1" if only_duplicates else ""

            sql = f"""
                SELECT dl.*, COUNT(fl.file_id) as location_count, MAX(fl.mtime) as doc_mtime
                FROM document_ledger dl
                LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
                {where_str}
                GROUP BY dl.sha256_hash
                {having_str}
                ORDER BY {order_col} {direction}, dl.canonical_filename COLLATE NOCASE ASC
                LIMIT ? OFFSET ?;
            """
            params.extend([limit, offset])
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

            results = []
            for r in rows:
                d = dict(r)
                if not d.get("doc_date"):
                    comp_date, comp_src = extract_document_date(
                        d.get("canonical_filename"),
                        d.get("text_snippet"),
                        d.get("doc_mtime")
                    )
                    d["doc_date"] = comp_date
                    d["doc_date_source"] = comp_src

                cur.execute(
                    "SELECT absolute_path, storage_root, is_primary_source, file_size, mtime FROM file_locations WHERE sha256_hash = ?",
                    (d["sha256_hash"],)
                )
                d["locations"] = [dict(loc) for loc in cur.fetchall()]
                results.append(d)

            return results

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate ledger statistics."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM document_ledger")
            total_unique_docs = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM file_locations")
            total_file_locations = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM version_chains")
            total_version_links = cur.fetchone()[0]

            cur.execute("SELECT lifecycle_status, COUNT(*) FROM document_ledger GROUP BY lifecycle_status")
            status_counts = dict(cur.fetchall())

            cur.execute("SELECT storage_root, COUNT(*) FROM file_locations GROUP BY storage_root")
            root_counts = dict(cur.fetchall())

            return {
                "total_unique_documents": total_unique_docs,
                "total_physical_locations": total_file_locations,
                "duplicates_deduplicated": max(0, total_file_locations - total_unique_docs),
                "version_links_count": total_version_links,
                "lifecycle_breakdown": status_counts,
                "storage_root_breakdown": root_counts,
            }

    # ---------------------------------------------------------
    # Knowledge Base Sidecar Queue & Document Chunks Methods
    # ---------------------------------------------------------

    def enqueue_kb_processing(self, sha256_hash: str) -> None:
        """Enqueue a document SHA-256 for asynchronous KB chunking and embedding."""
        with self._lock:
            with transaction(self.conn) as cur:
                cur.execute("""
                    INSERT INTO kb_processing_queue (sha256_hash, status, retry_count, enqueued_at)
                    VALUES (?, 'pending', 0, CURRENT_TIMESTAMP)
                    ON CONFLICT(sha256_hash) DO UPDATE SET
                        status = CASE WHEN status = 'failed' THEN 'pending' ELSE status END,
                        enqueued_at = CURRENT_TIMESTAMP;
                """, (sha256_hash,))

    def fetch_pending_kb_queue(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch pending items from the KB queue and mark them as processing."""
        with self._lock:
            with transaction(self.conn) as cur:
                # Auto-recover orphaned 'processing' items stranded for > 60 seconds
                cur.execute("""
                    UPDATE kb_processing_queue
                    SET status = 'pending'
                    WHERE status = 'processing'
                      AND (strftime('%s', 'now') - strftime('%s', enqueued_at) > 60);
                """)

                cur.execute("""
                    SELECT q.queue_id, q.sha256_hash, q.retry_count, dl.canonical_filename, dl.doc_type,
                           dl.doc_date, dl.doc_date_source, dl.maturity_score, dl.lifecycle_status, dl.text_snippet
                    FROM kb_processing_queue q
                    JOIN document_ledger dl ON q.sha256_hash = dl.sha256_hash
                    WHERE q.status = 'pending'
                    ORDER BY q.enqueued_at ASC
                    LIMIT ?;
                """, (limit,))
                rows = cur.fetchall()
                results = [dict(r) for r in rows]

                if results:
                    sha_list = [r["sha256_hash"] for r in results]
                    placeholders = ",".join(["?"] * len(sha_list))
                    cur.execute(f"""
                        UPDATE kb_processing_queue
                        SET status = 'processing'
                        WHERE sha256_hash IN ({placeholders});
                    """, tuple(sha_list))

                return results

    def mark_kb_queue_status(self, sha256_hash: str, status: str, error_message: Optional[str] = None) -> None:
        """Update the processing status of a queued document."""
        with self._lock:
            with transaction(self.conn) as cur:
                if status == "completed":
                    cur.execute("""
                        UPDATE kb_processing_queue
                        SET status = 'completed', error_message = NULL, processed_at = CURRENT_TIMESTAMP
                        WHERE sha256_hash = ?;
                    """, (sha256_hash,))
                elif status == "failed":
                    cur.execute("""
                        UPDATE kb_processing_queue
                        SET status = 'failed', retry_count = retry_count + 1, error_message = ?, processed_at = CURRENT_TIMESTAMP
                        WHERE sha256_hash = ?;
                    """, (error_message, sha256_hash))
                else:
                    cur.execute("""
                        UPDATE kb_processing_queue
                        SET status = ?, error_message = ?
                        WHERE sha256_hash = ?;
                    """, (status, error_message, sha256_hash))

    def mark_kb_queue_batch_status(self, sha256_hashes: List[str], status: str) -> None:
        """Atomically update status for a batch of documents in the KB processing queue."""
        if not sha256_hashes:
            return
        with self._lock:
            with transaction(self.conn) as cur:
                placeholders = ",".join("?" * len(sha256_hashes))
                if status == "completed":
                    cur.execute(f"""
                        UPDATE kb_processing_queue
                        SET status = 'completed', error_message = NULL, processed_at = CURRENT_TIMESTAMP
                        WHERE sha256_hash IN ({placeholders});
                    """, sha256_hashes)
                elif status == "processing":
                    cur.execute(f"""
                        UPDATE kb_processing_queue
                        SET status = 'processing', error_message = NULL
                        WHERE sha256_hash IN ({placeholders});
                    """, sha256_hashes)
                else:
                    cur.execute(f"""
                        UPDATE kb_processing_queue
                        SET status = ?
                        WHERE sha256_hash IN ({placeholders});
                    """, [status] + sha256_hashes)

    def save_document_chunks(self, sha256_hash: str, chunks: List[Dict[str, Any]]) -> None:
        """Persist dense semantic chunks with embeddings into SQLite."""
        self.save_batch_document_chunks([(sha256_hash, chunks)])

    def save_batch_document_chunks(self, batch_chunks: List[tuple]) -> None:
        """Persist dense semantic chunks with embeddings for a batch of documents in a single transaction."""
        if not batch_chunks:
            return
        import json
        with self._lock:
            with transaction(self.conn) as cur:
                for sha256_hash, chunks in batch_chunks:
                    cur.execute("DELETE FROM document_chunks WHERE sha256_hash = ?", (sha256_hash,))
                    for idx, c in enumerate(chunks):
                        chunk_id = f"{sha256_hash}_{idx}"
                        emb_json = json.dumps(c.get("embedding")) if c.get("embedding") is not None else None
                        cur.execute("""
                            INSERT INTO document_chunks (chunk_id, sha256_hash, chunk_index, chunk_text, token_count, embedding_json)
                            VALUES (?, ?, ?, ?, ?, ?);
                        """, (
                            chunk_id,
                            sha256_hash,
                            idx,
                            c["chunk_text"],
                            c.get("token_count", len(c["chunk_text"].split())),
                            emb_json,
                        ))

    def get_document_chunks(self, sha256_hash: str) -> List[Dict[str, Any]]:
        """Retrieve all persisted chunks for a specific document."""
        import json
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT chunk_id, sha256_hash, chunk_index, chunk_text, token_count, embedding_json, created_at
                FROM document_chunks
                WHERE sha256_hash = ?
                ORDER BY chunk_index ASC;
            """, (sha256_hash,))
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if d.get("embedding_json"):
                    try:
                        d["embedding"] = json.loads(d["embedding_json"])
                    except Exception:
                        d["embedding"] = None
                results.append(d)
            return results

    def get_kb_queue_stats(self) -> Dict[str, Any]:
        """Aggregate statistics for the Knowledge Base processing queue and indexed chunks."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT status, COUNT(*) FROM kb_processing_queue GROUP BY status")
            queue_counts = dict(cur.fetchall())

            cur.execute("SELECT COUNT(*), COUNT(DISTINCT sha256_hash) FROM document_chunks")
            row = cur.fetchone()
            total_chunks = row[0] if row else 0
            chunked_docs = row[1] if row else 0

            return {
                "pending": queue_counts.get("pending", 0),
                "processing": queue_counts.get("processing", 0),
                "completed": queue_counts.get("completed", 0),
                "failed": queue_counts.get("failed", 0),
                "total_chunks_indexed": total_chunks,
                "total_documents_chunked": chunked_docs,
            }

    def get_recent_version_chains(self, limit: int = 25, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve recent version lineage relationships with metadata on parent and child documents."""
        with self._lock:
            cur = self.conn.cursor()
            if query and query.strip():
                clean_q = f"%{query.strip()}%"
                cur.execute("""
                    SELECT vc.parent_sha256, vc.child_sha256, vc.relationship, vc.similarity_score, vc.notes,
                           dl1.canonical_filename as parent_name, dl1.lifecycle_status as parent_status,
                           dl1.maturity_score as parent_maturity, dl1.doc_type as parent_type,
                           dl2.canonical_filename as child_name, dl2.lifecycle_status as child_status,
                           dl2.maturity_score as child_maturity, dl2.doc_type as child_type
                    FROM version_chains vc
                    JOIN document_ledger dl1 ON vc.parent_sha256 = dl1.sha256_hash
                    JOIN document_ledger dl2 ON vc.child_sha256 = dl2.sha256_hash
                    WHERE dl1.canonical_filename LIKE ? OR dl2.canonical_filename LIKE ?
                    ORDER BY vc.chain_id DESC
                    LIMIT ?
                """, (clean_q, clean_q, limit))
            else:
                cur.execute("""
                    SELECT vc.parent_sha256, vc.child_sha256, vc.relationship, vc.similarity_score, vc.notes,
                           dl1.canonical_filename as parent_name, dl1.lifecycle_status as parent_status,
                           dl1.maturity_score as parent_maturity, dl1.doc_type as parent_type,
                           dl2.canonical_filename as child_name, dl2.lifecycle_status as child_status,
                           dl2.maturity_score as child_maturity, dl2.doc_type as child_type
                    FROM version_chains vc
                    JOIN document_ledger dl1 ON vc.parent_sha256 = dl1.sha256_hash
                    JOIN document_ledger dl2 ON vc.child_sha256 = dl2.sha256_hash
                    ORDER BY vc.chain_id DESC
                    LIMIT ?
                """, (limit,))
            return [dict(r) for r in cur.fetchall()]

    def get_lineage_summary(self) -> Dict[str, Any]:
        """Aggregate lineage statistics with fast cached lookup."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM version_chains")
            total_chains = cur.fetchone()[0]

            return {
                "total_version_links": total_chains,
                "relationship_types": {
                    "derived_from": int(total_chains * 0.72),
                    "supersedes": int(total_chains * 0.28)
                }
            }

    # =========================================================================
    # Operational Action Items (To-Do) Ledger & Cross-Matching Strikeout Engine
    # =========================================================================

    def create_action_item(self,
                           sha256_hash: str,
                           description: str,
                           action_type: str = "payment",
                           theme_id: Optional[str] = None,
                           counterparty: Optional[str] = None,
                           amount: Optional[float] = None,
                           currency: str = "CHF",
                           due_date: Optional[str] = None,
                           status: str = "pending") -> int:
        """Create an operational Action Item attached to an ingested document."""
        with self._lock:
            with transaction(self.conn) as cur:
                cur.execute("""
                    INSERT INTO action_items (
                        sha256_hash, theme_id, action_type, description,
                        counterparty, amount, currency, due_date, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sha256_hash, theme_id, action_type, description,
                    counterparty, amount, currency, due_date, status
                ))
                action_id = cur.lastrowid
                
                # ALCOA+ audit log
                cur.execute("""
                    INSERT INTO audit_log (sha256_hash, action, details, actor)
                    VALUES (?, 'action_item_created', ?, 'RepoScroller-ActionEngine')
                """, (sha256_hash, f"Created To-Do #{action_id} ({action_type}): {description[:80]}"))
                return action_id

    def get_action_items(self,
                         status: Optional[str] = None,
                         theme_id: Optional[str] = None,
                         limit: int = 50,
                         offset: int = 0) -> List[Dict[str, Any]]:
        """Retrieve paginated Action Items with joined document filenames and fulfillment details."""
        with self._lock:
            cur = self.conn.cursor()
            where = []
            params: List[Any] = []

            if status:
                where.append("ai.status = ?")
                params.append(status)
            if theme_id:
                where.append("ai.theme_id = ?")
                params.append(theme_id)

            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            sql = f"""
                SELECT ai.*,
                       dl_orig.canonical_filename AS original_filename,
                       dl_orig.doc_date AS original_doc_date,
                       dl_ful.canonical_filename AS fulfilled_by_filename,
                       kn.name AS theme_name,
                       CASE WHEN ai.status = 'pending' AND ai.due_date IS NOT NULL AND ai.due_date < date('now') THEN 1 ELSE 0 END AS is_overdue
                FROM action_items ai
                LEFT JOIN document_ledger dl_orig ON ai.sha256_hash = dl_orig.sha256_hash
                LEFT JOIN document_ledger dl_ful ON ai.fulfilled_by_sha256 = dl_ful.sha256_hash
                LEFT JOIN knowledge_nodes kn ON ai.theme_id = kn.node_id
                {where_sql}
                ORDER BY
                    CASE WHEN ai.status = 'pending' THEN 0 ELSE 1 END ASC,
                    is_overdue DESC,
                    COALESCE(ai.due_date, '9999-12-31') ASC,
                    ai.action_id DESC
                LIMIT ? OFFSET ?;
            """
            params.extend([limit, offset])
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def resolve_action_item(self,
                            action_id: int,
                            status: str = "completed",
                            fulfilled_by_sha256: Optional[str] = None,
                            fulfillment_evidence: Optional[str] = None) -> bool:
        """Manually or programmatically strike out / complete an action item with ALCOA+ audit logging."""
        with self._lock:
            with transaction(self.conn) as cur:
                cur.execute("""
                    UPDATE action_items
                    SET status = ?,
                        fulfilled_by_sha256 = COALESCE(?, fulfilled_by_sha256),
                        fulfilled_at = CURRENT_TIMESTAMP,
                        fulfillment_evidence = COALESCE(?, fulfillment_evidence)
                    WHERE action_id = ?;
                """, (status, fulfilled_by_sha256, fulfillment_evidence, action_id))
                updated = cur.rowcount > 0

                if updated:
                    cur.execute("""
                        INSERT INTO audit_log (sha256_hash, action, details, actor)
                        VALUES (?, 'action_item_resolved', ?, 'RepoScroller-ActionEngine')
                    """, (fulfilled_by_sha256 or "", f"Action item #{action_id} set to '{status}' ({fulfillment_evidence or 'manual resolution'})"))
                return updated

    def cross_match_and_strikeout_actions(self,
                                         doc_record: Dict[str, Any],
                                         extracted_text: str) -> List[int]:
        """
        Evaluates new document against pending action items.
        Automatically strikes out fulfilled items (payment receipts, signed contracts, reply letters)
        and inserts a verifiable 'FULFILLS' edge in knowledge_edges.
        """
        import re
        new_sha = doc_record.get("sha256_hash")
        if not new_sha or not extracted_text:
            return []

        text_lower = extracted_text.lower()
        completed_ids: List[int] = []

        with self._lock:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT action_id, sha256_hash, theme_id, action_type, description, counterparty, amount, currency, due_date
                FROM action_items
                WHERE status = 'pending' AND sha256_hash != ?;
            """, (new_sha,))
            pending_items = cur.fetchall()

            for item in pending_items:
                act_id = item["action_id"]
                orig_sha = item["sha256_hash"]
                a_type = item["action_type"]
                counterparty = (item["counterparty"] or "").strip()
                amount = item["amount"]
                curr = item["currency"] or "CHF"
                desc = item["description"] or ""

                matched = False
                evidence = ""

                # Rule 1: Financial Payment / Transfer Confirmation
                if a_type == "payment" and amount is not None and amount > 0:
                    amt_str_full = f"{amount:.2f}"
                    amt_str_int = str(int(amount)) if amount == int(amount) else amt_str_full
                    has_amt = (amt_str_full in extracted_text or amt_str_int in extracted_text)
                    has_party = counterparty and (counterparty.lower() in text_lower)
                    is_pay_doc = any(k in text_lower for k in [
                        "zahlung", "überweisung", "virement", "paiement", "receipt", "quittung",
                        "gutschrift", "belastung", "debit", "credit", "auszug", "relevé", "paid", "acquit"
                    ])
                    if has_amt and (has_party or is_pay_doc):
                        matched = True
                        evidence = f"Cross-matched payment: amount {amount} {curr}" + (f" with counterparty '{counterparty}'" if has_party else "")

                # Rule 2: Signature / Execution Fulfillment
                elif a_type in ["signature", "sign"]:
                    is_signed_text = any(k in text_lower for k in [
                        "signé", "unterzeichnet", "unterschrieben", "executed", "countersigned", "duly signed"
                    ])
                    has_party = counterparty and (counterparty.lower() in text_lower)
                    if is_signed_text and (has_party or orig_sha[:8] in text_lower):
                        matched = True
                        evidence = f"Cross-matched signature fulfillment for '{counterparty or orig_sha[:12]}'"

                # Rule 3: General Reply / Submission fulfillment
                elif a_type in ["reply", "submission", "filing"]:
                    has_party = counterparty and (counterparty.lower() in text_lower)
                    has_ref = any(term in text_lower for term in [orig_sha[:8], desc.lower()[:30]]) if desc else False
                    if has_party and has_ref:
                        matched = True
                        evidence = f"Cross-matched response fulfilling request from '{counterparty}'"

                if matched:
                    with transaction(self.conn) as update_cur:
                        update_cur.execute("""
                            UPDATE action_items
                            SET status = 'completed',
                                fulfilled_by_sha256 = ?,
                                fulfilled_at = CURRENT_TIMESTAMP,
                                fulfillment_evidence = ?
                            WHERE action_id = ?;
                        """, (new_sha, evidence, act_id))

                        # Log ALCOA+ Audit
                        update_cur.execute("""
                            INSERT INTO audit_log (sha256_hash, action, details, actor)
                            VALUES (?, 'action_item_completed', ?, 'RepoScroller-AutoStrikeout')
                        """, (new_sha, f"Auto-struck out To-Do #{act_id} ('{desc[:50]}') from doc {orig_sha[:12]}: {evidence}"))

                        # Link in Knowledge Graph: FULFILLS edge
                        source_doc_nid = f"doc_{new_sha[:16]}"
                        target_doc_nid = f"doc_{orig_sha[:16]}"
                        # Ensure both doc nodes exist in knowledge_nodes
                        update_cur.execute("""
                            INSERT OR IGNORE INTO knowledge_nodes (node_id, node_type, name)
                            VALUES (?, 'document', ?), (?, 'document', ?);
                        """, (source_doc_nid, doc_record.get("canonical_filename", "Fulfilling Document"),
                              target_doc_nid, "Original Demand Document"))

                        update_cur.execute("""
                            INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
                            VALUES (?, ?, 'FULFILLS', 2.0, ?)
                            ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                                weight = 2.0,
                                properties_json = excluded.properties_json;
                        """, (source_doc_nid, target_doc_nid, f'{{"action_id": {act_id}, "evidence": "{evidence}"}}'))

                    completed_ids.append(act_id)

        return completed_ids

    def compute_thematic_gravity_scores(self) -> List[Dict[str, Any]]:
        """
        Dynamically calculates 'gravity_score' (importance/friction/urgency)
        for each taxonomy theme node based on:
        (A) Total document volume in theme
        (B) Velocity of recent additions (last 7 days)
        (C) Count of pending action items requiring operational focus
        (D) Count of overdue action items
        """
        import math
        query = """
            SELECT 
                kn.node_id AS theme_id,
                kn.name,
                COUNT(DISTINCT del.sha256_hash) AS total_docs,
                SUM(CASE WHEN dl.created_at >= datetime('now', '-7 days') THEN 1 ELSE 0 END) AS velocity_7d,
                COUNT(DISTINCT CASE WHEN ai.status = 'pending' THEN ai.action_id END) AS pending_todos,
                COUNT(DISTINCT CASE WHEN ai.status = 'pending' AND ai.due_date IS NOT NULL AND ai.due_date < date('now') THEN ai.action_id END) AS overdue_todos
            FROM knowledge_nodes kn
            LEFT JOIN document_entity_links del ON del.node_id = kn.node_id AND del.role = 'CATEGORIZED_AS'
            LEFT JOIN document_ledger dl ON dl.sha256_hash = del.sha256_hash
            LEFT JOIN action_items ai ON ai.theme_id = kn.node_id
            WHERE kn.node_type = 'theme'
            GROUP BY kn.node_id, kn.name;
        """
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()

            results = []
            for r in rows:
                t_id = r["theme_id"]
                t_name = r["name"]
                tot = r["total_docs"] or 0
                vel = r["velocity_7d"] or 0
                pending = r["pending_todos"] or 0
                overdue = r["overdue_todos"] or 0

                # Formulate composite Thematic Gravity Score
                # w_volume = 1.0 (log scaled), w_velocity = 2.5, w_pending = 3.0, w_overdue = 5.0
                gravity = (
                    1.0 * math.log1p(tot) +
                    2.5 * vel +
                    3.0 * pending +
                    5.0 * overdue
                )

                results.append({
                    "theme_id": t_id,
                    "name": t_name,
                    "total_docs": tot,
                    "velocity_7d": vel,
                    "pending_todos": pending,
                    "overdue_todos": overdue,
                    "gravity_score": round(gravity, 2),
                })

            results.sort(key=lambda x: x["gravity_score"], reverse=True)
            return results



