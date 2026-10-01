"""Re-indexing and classification backfill script for Career Cover Letters & Application Letters."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Dict, Any, List

from backend.config import settings
from backend.ai.analyzer import DocumentAnalyzer
from backend.ai.taxonomy import TaxonomyManager, DEFAULT_TAXONOMY, TaxonomyCategory

logger = logging.getLogger("reindex_career")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def get_db_path() -> Path:
    return getattr(settings, "DB_PATH", Path(__file__).resolve().parent.parent / "data" / "reposcroller_ledger.db")


def reindex_career_documents(db_path: Path = None, verbose: bool = True) -> Dict[str, Any]:
    """Re-index and backfill misclassified application letters, cover letters, and profile documents."""
    if db_path is None:
        db_path = get_db_path()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    stats = {
        "taxonomy_categories_synced": 0,
        "scanned_documents": 0,
        "reclassified_to_career_cover_letter": 0,
        "reclassified_to_career_profile": 0,
        "reclassified_to_career_cv": 0,
        "reclassified_to_career_job_description": 0,
        "chunks_updated": 0,
    }

    try:
        # 1. Synchronize refreshed taxonomy into global_taxonomy table
        tax_mgr = TaxonomyManager(db_conn=conn)
        for cat_item in DEFAULT_TAXONOMY:
            tax_mgr.upsert_category(TaxonomyCategory(**cat_item))
            stats["taxonomy_categories_synced"] += 1
        conn.commit()
        if verbose:
            logger.info("Synchronized global_taxonomy table with refreshed career and corporate governance keywords.")

        # 2. Find candidate documents: CVs, resumes, lebenslauf, application letters, cover letters, bewerbungen, profiles, and job descriptions
        cur.execute("""
            SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.text_snippet,
                   COALESCE(fl.relative_path, '') as relative_path,
                   COALESCE(fl.storage_root, '') as storage_root
            FROM document_ledger dl
            LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
            WHERE 
                LOWER(dl.canonical_filename) LIKE '%cv%'
                OR LOWER(dl.canonical_filename) LIKE '%lebenslauf%'
                OR LOWER(dl.canonical_filename) LIKE '%curriculum%'
                OR LOWER(dl.canonical_filename) LIKE '%resume%'
                OR LOWER(fl.relative_path) LIKE '%-cv%'
                OR LOWER(fl.relative_path) LIKE '%/cv/%'
                OR LOWER(fl.relative_path) LIKE '%\\cv\\%'
                OR LOWER(dl.canonical_filename) LIKE '%application%letter%'
                OR LOWER(dl.canonical_filename) LIKE '%cover%letter%'
                OR LOWER(dl.canonical_filename) LIKE '%bewerbung%'
                OR LOWER(dl.canonical_filename) LIKE '%candidature%'
                OR LOWER(dl.canonical_filename) LIKE '%motivation%'
                OR LOWER(dl.canonical_filename) LIKE '%profile%'
                OR LOWER(dl.canonical_filename) LIKE '%profil%'
                OR LOWER(dl.canonical_filename) LIKE '%jobdescription%'
                OR LOWER(dl.canonical_filename) LIKE '%job_description%'
                OR LOWER(dl.canonical_filename) LIKE '%job-description%'
                OR LOWER(dl.canonical_filename) LIKE '%stellenbeschreibung%'
                OR LOWER(dl.canonical_filename) LIKE '%stellenausschreibung%'
                OR (dl.doc_type IN ('tax_assessment', 'technical_architecture', 'corporate_governance', 'formal_correspondence', 'lease_contract', 'employment_contract', 'other', 'identity_credentials')
                    AND (dl.text_snippet LIKE '%bewerb%' OR dl.text_snippet LIKE '%candidat%' OR dl.text_snippet LIKE '%cover%' OR dl.text_snippet LIKE '%hiring%' OR dl.text_snippet LIKE '%Job Details%' OR dl.text_snippet LIKE '%job_title%' OR dl.text_snippet LIKE '%curriculum%' OR dl.text_snippet LIKE '%lebenslauf%'))
            GROUP BY dl.sha256_hash
        """)
        candidates = cur.fetchall()
        stats["scanned_documents"] = len(candidates)
        if verbose:
            logger.info(f"Scanning {len(candidates)} candidate documents for career reclassification...")

        analyzer = DocumentAnalyzer(provider="mock", taxonomy_manager=tax_mgr)

        reclassified_docs = []

        for idx, row in enumerate(candidates):
            sha = row["sha256_hash"]
            fn = row["canonical_filename"]
            old_type = row["doc_type"]
            text_snippet = row["text_snippet"] or ""
            rel_path = row["relative_path"]
            storage_root = row["storage_root"]
            meta = {"path": f"{storage_root}\\{rel_path}"} if (storage_root or rel_path) else {}

            # Read first chunk if available for best extraction and summary quality
            cur.execute("SELECT chunk_text FROM document_chunks WHERE sha256_hash = ? ORDER BY chunk_index ASC LIMIT 1", (sha,))
            chunk_row = cur.fetchone()
            analysis_text = chunk_row[0] if (chunk_row and chunk_row[0]) else text_snippet
            analysis = analyzer._heuristic_analyze(analysis_text, fn, meta)
            new_type = analysis.document_category

            if (new_type != old_type and new_type.startswith("career_")) or \
               (new_type.startswith("career_") and "[LEASE_CONTRACT]" in text_snippet):
                reclassified_docs.append({
                    "sha256": sha,
                    "filename": fn,
                    "old_type": old_type,
                    "new_type": new_type,
                    "summary": analysis.summary
                })

            if verbose and (idx + 1) % 1000 == 0:
                logger.info(f"Evaluated {idx + 1}/{len(candidates)} candidates... Found {len(reclassified_docs)} career reclassifications so far.")

        if verbose:
            logger.info(f"Applying updates for {len(reclassified_docs)} reclassified documents...")

        # 3. Apply updates to document_ledger and document_chunks
        for item in reclassified_docs:
            sha = item["sha256"]
            new_type = item["new_type"]
            old_type = item["old_type"]

            # Update document_ledger
            new_snippet = f"[{new_type.upper()}] {item['summary']}"
            cur.execute("""
                UPDATE document_ledger
                SET doc_type = ?,
                    text_snippet = ?,
                    last_verified = CURRENT_TIMESTAMP
                WHERE sha256_hash = ?
            """, (new_type, new_snippet, sha))

            # Update chunk headers in document_chunks
            cur.execute("SELECT chunk_id, chunk_text FROM document_chunks WHERE sha256_hash = ?", (sha,))
            for ch in cur.fetchall():
                ch_id = ch["chunk_id"]
                ch_text = ch["chunk_text"]
                old_cat_header = f"Category: {old_type.upper()}"
                new_cat_header = f"Category: {new_type.upper()}"
                if old_cat_header in ch_text:
                    updated_text = ch_text.replace(old_cat_header, new_cat_header)
                    cur.execute("UPDATE document_chunks SET chunk_text = ? WHERE chunk_id = ?", (updated_text, ch_id))
                    stats["chunks_updated"] += 1

            if new_type == "career_cover_letter":
                stats["reclassified_to_career_cover_letter"] += 1
            elif new_type == "career_profile":
                stats["reclassified_to_career_profile"] += 1
            elif new_type == "career_cv":
                stats["reclassified_to_career_cv"] += 1
            elif new_type == "career_job_description":
                stats["reclassified_to_career_job_description"] += 1

        conn.commit()

        if verbose:
            logger.info("=== Career Documents Reclassification Complete ===")
            logger.info(f"Total documents reclassified to career_job_description: {stats['reclassified_to_career_job_description']}")
            logger.info(f"Total documents reclassified to career_cover_letter:    {stats['reclassified_to_career_cover_letter']}")
            logger.info(f"Total documents reclassified to career_profile:         {stats['reclassified_to_career_profile']}")
            logger.info(f"Total documents reclassified to career_cv:              {stats['reclassified_to_career_cv']}")
            logger.info(f"Total chunks updated:                                  {stats['chunks_updated']}")

        return stats

    finally:
        conn.close()


if __name__ == "__main__":
    reindex_career_documents()
