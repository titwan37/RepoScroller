"""Document ledger, inspection, and pre-flight duplicate check endpoints."""

import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.integrity.hasher import compute_bytes_sha256
from reposcroller.integrity.simhash import compute_simhash
from reposcroller.agents.duplicate_agent import DuplicateResolverAgent

router = APIRouter(prefix="/documents", tags=["Documents"])


import logging
import os
import sys
import subprocess

logger = logging.getLogger("reposcroller.api.documents")


class DuplicateCheckRequest(BaseModel):
    sha256_hash: Optional[str] = None
    query_text: Optional[str] = None
    filename: Optional[str] = None


class OpenFileRequest(BaseModel):
    file_path: Optional[str] = None
    path: Optional[str] = None
    reveal: bool = False


@router.get("/ledger")
def list_documents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by lifecycle_status: draft, review, final, truncated"),
    category: Optional[str] = Query(None, description="Filter by doc_type / category"),
    only_duplicates: bool = Query(False, description="Filter to documents with >1 physical locations"),
    query: Optional[str] = Query(None, description="Search keyword across filename and text snippet"),
    sort_by: str = Query("doc_date", description="Sort by column: doc_date, canonical_filename, doc_type, maturity_score, lifecycle_status, location_count"),
    sort_order: str = Query("DESC", description="Sort direction: ASC or DESC")
) -> Dict[str, Any]:
    """Retrieve paginated document ledger records with optional query search, category, duplicate filter, and column sorting."""
    repo = DocumentRepository()
    docs = repo.get_all_documents(
        limit=limit,
        offset=offset,
        status=status,
        category=category,
        only_duplicates=only_duplicates,
        query=query,
        sort_by=sort_by,
        sort_order=sort_order
    )
    stats = repo.get_stats()
    return {
        "total_records": stats["total_unique_documents"],
        "returned": len(docs),
        "limit": limit,
        "offset": offset,
        "items": docs,
    }


@router.post("/open-file")
def open_file_endpoint(req: OpenFileRequest) -> Dict[str, Any]:
    """Open a file or reveal it in File Explorer on the local machine (supports UNC paths)."""
    target_path = (req.file_path or req.path or "").strip()
    if not target_path:
        raise HTTPException(status_code=400, detail="Missing file path to open")

    try:
        if sys.platform == "win32":
            norm_path = os.path.normpath(target_path)
            logger.info(f"norm_path: {norm_path}")
            logger.info(f"req.reveal: {req.reveal}")
            if req.reveal:
                logger.info(f"is directory: {os.path.isdir(norm_path)}")
                logger.info(f"is file: {os.path.isfile(norm_path)}")
                if os.path.isdir(norm_path):
                    # If it's a directory, open the folder directly in Explorer
                    os.startfile(norm_path)
                elif os.path.isfile(norm_path):
                    # If it's a file, highlight it in Explorer.
                    # CRITICAL: /select must NOT be quoted; only the path itself must be quoted.
                    subprocess.Popen(f'explorer.exe /select,"{norm_path}"')
                else:
                    parent = os.path.dirname(norm_path)
                    if parent and os.path.isdir(parent):
                        os.startfile(parent)
                    else:
                        raise FileNotFoundError(f"Path does not exist: {norm_path}")
            else:
                if os.path.exists(norm_path):
                    os.startfile(norm_path)
                else:
                    raise FileNotFoundError(f"File not found: {norm_path}")
        elif sys.platform == "darwin":
            if req.reveal:
                subprocess.Popen(["open", "-R", target_path])
            else:
                subprocess.Popen(["open", target_path])
        else:
            if req.reveal:
                subprocess.Popen(["xdg-open", str(Path(target_path).parent)])
            else:
                subprocess.Popen(["xdg-open", target_path])

        return {
            "status": "success",
            "message": f"Successfully launched {target_path}",
            "path": target_path,
            "revealed": req.reveal
        }
    except Exception as e:
        logger.error(f"Failed to open '{target_path}': {e}")
        raise HTTPException(status_code=500, detail=f"Could not open file: {str(e)}")


@router.get("/stats")
def get_ledger_stats() -> Dict[str, Any]:
    """Get aggregate repository statistics (total files, duplicates, lifecycle breakdown)."""
    repo = DocumentRepository()
    return repo.get_stats()


@router.get("/lineage/chains")
def get_lineage_chains(
    limit: int = Query(25, ge=1, le=200, description="Max lineage chains to retrieve"),
    query: Optional[str] = Query(None, description="Optional search filter for filename")
) -> Dict[str, Any]:
    """Retrieve version lineage chains showing evolutionary document versions and parent-child derivations."""
    repo = DocumentRepository()
    chains = repo.get_recent_version_chains(limit=limit, query=query)
    summary = repo.get_lineage_summary()
    return {
        "status": "success",
        "count": len(chains),
        "summary": summary,
        "chains": chains
    }


@router.get("/lineage/summary")
def get_lineage_summary_endpoint() -> Dict[str, Any]:
    """Retrieve overall lineage summary and relationship breakdown."""
    repo = DocumentRepository()
    return {
        "status": "success",
        "summary": repo.get_lineage_summary()
    }


@router.get("/{sha256_hash}")
def get_document_details(sha256_hash: str) -> Dict[str, Any]:
    """Retrieve full document detail, all storage locations, and lineage history."""
    repo = DocumentRepository()
    doc = repo.get_document_by_sha256(sha256_hash)
    if not doc:
        raise HTTPException(status_code=404, detail="Document hash not found in ledger")
    return doc


@router.post("/check-duplicate")
async def check_duplicate(
    file: Optional[UploadFile] = File(None),
    sha256_hash: Optional[str] = Form(None),
    query_text: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """Pre-flight duplicate check: verify if a file or hash already exists before writing to disk."""
    agent = DuplicateResolverAgent()

    if file:
        content = await file.read()
        computed_sha = compute_bytes_sha256(content)

        # Temporary write to evaluate extraction if needed
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "temp.tmp").suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = agent.interrogate(
                file_path=tmp_path,
                sha256_hash=computed_sha,
                query=file.filename or ""
            )
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass

        return result

    elif sha256_hash or query_text:
        return agent.interrogate(
            sha256_hash=sha256_hash,
            query_text=query_text,
            query=""
        )
    else:
        raise HTTPException(status_code=400, detail="Must provide either an uploaded file, sha256_hash, or query_text")


@router.get("/audit/trail")
def get_audit_trail(limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    """Retrieve ALCOA+ audit trail entries."""
    repo = DocumentRepository()
    cur = repo.conn.cursor()
    cur.execute("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,))
    logs = [dict(r) for r in cur.fetchall()]
    return {"count": len(logs), "logs": logs}
