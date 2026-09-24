"""Repository layer for ACID SQLite ledger operations and ALCOA+ audit trails."""

import sqlite3
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from reposcroller.config import settings
from reposcroller.integrity.simhash import hamming_distance, simhash_similarity
from reposcroller.integrity.date_extractor import extract_document_date
from reposcroller.ledger.db import get_db_connection, transaction


class DocumentRepository:
    """Manages document ledger persistence, location mapping, and version lineage."""

    def __init__(self, db_path: Optional[Path] = None, conn: Optional[sqlite3.Connection] = None):
        self._conn = conn
        self._owns_conn = conn is None
        self._lock = threading.RLock()

        if db_path:
            self.db_path = Path(db_path)
        elif conn:
            try:
                cur = conn.cursor()
                cur.execute("PRAGMA database_list;")
                row = cur.fetchone()
                if row and row[2]:
                    self.db_path = Path(row[2])
                else:
                    self.db_path = settings.DB_PATH
            except Exception:
                self.db_path = settings.DB_PATH
        else:
            self.db_path = settings.DB_PATH

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = get_db_connection(self.db_path)
            self._ensure_schema()
        return self._conn

    def _ensure_schema(self) -> None:
        """Ensure latest columns (doc_date, doc_date_source) and indices exist."""
        try:
            cur = self._conn.cursor()
            cols = [r[1] for r in cur.execute("PRAGMA table_info(document_ledger);").fetchall()]
            if "doc_date" not in cols:
                cur.execute("ALTER TABLE document_ledger ADD COLUMN doc_date TEXT;")
                cur.execute("ALTER TABLE document_ledger ADD COLUMN doc_date_source TEXT;")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ledger_doc_date ON document_ledger(doc_date);")
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
                        full_text: Optional[str] = None) -> None:
        """Insert or update a document in the document_ledger and FTS index."""
        if not doc_date:
            doc_date, doc_date_source = extract_document_date(canonical_filename, text_snippet)

        with self._lock:
            with transaction(self.conn) as cur:
                cur.execute("""
                    INSERT INTO document_ledger (
                        sha256_hash, simhash, canonical_filename, doc_type,
                        lifecycle_status, completeness_score, maturity_score,
                        page_count, text_snippet, doc_date, doc_date_source, last_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(sha256_hash) DO UPDATE SET
                        canonical_filename = excluded.canonical_filename,
                        lifecycle_status = excluded.lifecycle_status,
                        completeness_score = excluded.completeness_score,
                        maturity_score = excluded.maturity_score,
                        doc_date = COALESCE(excluded.doc_date, document_ledger.doc_date),
                        doc_date_source = COALESCE(excluded.doc_date_source, document_ledger.doc_date_source),
                        last_verified = CURRENT_TIMESTAMP;
                """, (
                    sha256_hash, simhash, canonical_filename, doc_type,
                    lifecycle_status, completeness_score, maturity_score,
                    page_count, text_snippet[:500], doc_date, doc_date_source
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
                        from reposcroller.extraction.text_extractor import extract_document_data
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

    def search_keyword_fts(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
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
                          sort_by: str = "created_at",
                          sort_order: str = "DESC") -> List[Dict[str, Any]]:
        """Retrieve paginated document ledger records with category, duplicate filtering, and sorting."""
        with self._lock:
            cur = self.conn.cursor()

            valid_cols = {
                "canonical_filename": "dl.canonical_filename COLLATE NOCASE",
                "doc_type": "dl.doc_type COLLATE NOCASE",
                "maturity_score": "dl.maturity_score",
                "lifecycle_status": "dl.lifecycle_status COLLATE NOCASE",
                "page_count": "dl.page_count",
                "doc_date": "COALESCE(dl.doc_date, datetime(MAX(fl.mtime), 'unixepoch'), dl.created_at)",
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
