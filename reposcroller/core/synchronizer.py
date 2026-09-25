"""Synchronizer pipeline orchestrating SHA-256 identity, text extraction, SimHash, and ALCOA+ ledger."""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from reposcroller.config import settings
from reposcroller.integrity.hasher import compute_sha256, compute_file_stats
from reposcroller.integrity.simhash import compute_simhash
from reposcroller.integrity.maturity import MaturityEvaluator
from reposcroller.integrity.date_extractor import extract_document_date
from reposcroller.extraction.text_extractor import extract_document_data
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ai.analyzer import DocumentAnalyzer


class DocumentSynchronizer:
    """Processes a single file, handles duplicate detection, and records in SQLite WAL ledger."""

    def __init__(self,
                 repository: Optional[DocumentRepository] = None,
                 maturity_evaluator: Optional[MaturityEvaluator] = None,
                 analyzer: Optional[DocumentAnalyzer] = None):
        self.repo = repository or DocumentRepository()
        self.maturity_evaluator = maturity_evaluator or MaturityEvaluator()
        from reposcroller.ai.taxonomy import TaxonomyManager
        tax_mgr = TaxonomyManager(db_conn=self.repo.conn)
        self.analyzer = analyzer or DocumentAnalyzer(taxonomy_manager=tax_mgr)

    def process_file(self,
                     file_path: Path,
                     storage_root: str,
                     force_reprocess: bool = False) -> Dict[str, Any]:
        """Ingest or verify a file from a storage root.
        
        Returns a status dictionary detailing whether the document was ingested,
        recognized as an exact duplicate, or updated.
        """
        abs_path = str(file_path.resolve())
        rel_path = os.path.relpath(abs_path, storage_root) if abs_path.startswith(storage_root) else file_path.name

        try:
            file_size, mtime = compute_file_stats(file_path)
        except (FileNotFoundError, PermissionError, OSError) as e:
            return {"status": "error", "error": f"Cannot stat file: {e}", "path": abs_path}

        # Check existing location record (fast path)
        existing_loc = self.repo.get_location_by_path(abs_path)
        if existing_loc and not force_reprocess:
            if existing_loc["mtime"] == mtime and existing_loc["file_size"] == file_size:
                return {
                    "status": "unchanged",
                    "sha256": existing_loc["sha256_hash"],
                    "path": abs_path,
                }

        # Step 1: Content-addressable SHA-256 computation
        try:
            sha256_hash = compute_sha256(file_path)
        except Exception as e:
            return {"status": "error", "error": f"Failed hashing content: {e}", "path": abs_path}

        # Step 2: Check if bit-identical document already exists in ledger
        existing_doc = self.repo.get_document_by_sha256(sha256_hash)
        is_primary = ("lexspace" in storage_root.lower() or "lawsuite" in storage_root.lower())

        if existing_doc:
            # Exact duplicate found in another location!
            self.repo.record_location(
                sha256_hash=sha256_hash,
                storage_root=storage_root,
                relative_path=rel_path,
                absolute_path=abs_path,
                file_size=file_size,
                mtime=mtime,
                is_primary=is_primary,
            )
            return {
                "status": "exact_duplicate_recorded",
                "sha256": sha256_hash,
                "canonical_filename": existing_doc["canonical_filename"],
                "lifecycle_status": existing_doc["lifecycle_status"],
                "path": abs_path,
                "existing_locations_count": len(existing_doc["locations"]),
            }

        # Step 3: New document - Extract text & structural metadata
        text, metadata = extract_document_data(file_path)
        metadata["file_size"] = file_size
        metadata["mtime"] = mtime

        # Step 4: Locality-Sensitive Hashing (SimHash)
        simhash_val = compute_simhash(text)

        # Step 5: Maturity, Lifecycle, & AI Categorization
        eval_result = self.maturity_evaluator.evaluate(
            file_path=file_path,
            text=text,
            metadata=metadata
        )

        analysis = self.analyzer.analyze(
            text=text,
            filename=file_path.name,
            metadata=metadata
        )

        doc_type = analysis.document_category
        text_snippet = f"[{analysis.document_category.upper()}] {analysis.summary}" if analysis.summary else (text[:500] if text else f"[File: {file_path.name}]")

        # Extract substantive document date (filename prefix, content, or mtime)
        doc_date, doc_date_source = extract_document_date(
            filename=file_path.name,
            text=text,
            mtime=mtime
        )

        # Step 6: Atomically commit to SQLite WAL document ledger or record duplicate
        with self.repo._lock:
            existing_doc = self.repo.get_document_by_sha256(sha256_hash)
            if existing_doc:
                self.repo.record_location(
                    sha256_hash=sha256_hash,
                    storage_root=storage_root,
                    relative_path=rel_path,
                    absolute_path=abs_path,
                    file_size=file_size,
                    mtime=mtime,
                    is_primary=is_primary,
                )
                return {
                    "status": "exact_duplicate_recorded",
                    "sha256": sha256_hash,
                    "canonical_filename": existing_doc["canonical_filename"],
                    "lifecycle_status": existing_doc["lifecycle_status"],
                    "path": abs_path,
                    "existing_locations_count": len(existing_doc["locations"]),
                }

            self.repo.upsert_document(
                sha256_hash=sha256_hash,
                simhash=simhash_val,
                canonical_filename=file_path.name,
                doc_type=doc_type,
                lifecycle_status=eval_result["lifecycle_status"],
                completeness_score=eval_result["completeness_score"],
                maturity_score=eval_result["maturity_score"],
                page_count=metadata.get("page_count", 1),
                text_snippet=text_snippet,
                doc_date=doc_date,
                doc_date_source=doc_date_source,
                full_text=text,
            )

            # Record physical location
            self.repo.record_location(
                sha256_hash=sha256_hash,
                storage_root=storage_root,
                relative_path=rel_path,
                absolute_path=abs_path,
                file_size=file_size,
                mtime=mtime,
                is_primary=is_primary,
            )


        # Step 7: Check for near-duplicates and link version chains
        near_matches = self.repo.find_near_duplicates_simhash(
            query_simhash=simhash_val,
            max_hamming=settings.SIMHASH_HAMMING_THRESHOLD,
            exclude_sha256=sha256_hash
        )

        linked_chains = []
        for match in near_matches:
            match_sha = match["sha256_hash"]
            match_maturity = match["maturity_score"]
            sim_score = match["similarity_score"]

            if eval_result["maturity_score"] > match_maturity:
                # New document is more mature -> supersedes old
                rel = "supersedes"
                self.repo.link_version_chain(
                    parent_sha256=match_sha,
                    child_sha256=sha256_hash,
                    relationship=rel,
                    similarity_score=sim_score,
                    notes=f"Higher maturity ({eval_result['maturity_score']} vs {match_maturity})"
                )
            else:
                rel = "derived_from"
                self.repo.link_version_chain(
                    parent_sha256=sha256_hash,
                    child_sha256=match_sha,
                    relationship=rel,
                    similarity_score=sim_score,
                    notes=f"Lower or equal maturity ({eval_result['maturity_score']} vs {match_maturity})"
                )
            linked_chains.append({"target": match_sha, "relationship": rel, "similarity": sim_score})

        # Step 8: Enqueue for asynchronous Knowledge Base sidecar processing (Chunking, Embedding, Entities)
        self.repo.enqueue_kb_processing(sha256_hash)

        return {
            "status": "ingested",
            "sha256": sha256_hash,
            "simhash": simhash_val,
            "maturity_score": eval_result["maturity_score"],
            "lifecycle_status": eval_result["lifecycle_status"],
            "linked_versions": linked_chains,
            "path": abs_path,
        }

