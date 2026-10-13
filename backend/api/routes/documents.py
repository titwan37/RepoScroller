"""Document ledger, inspection, and pre-flight duplicate check endpoints."""

import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any
import html
from fastapi import APIRouter, Query, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from backend.ledger.repository import DocumentRepository
from backend.integrity.hasher import compute_bytes_sha256
from backend.integrity.simhash import compute_simhash
from backend.agents.duplicate_agent import DuplicateResolverAgent

router = APIRouter(prefix="/documents", tags=["Documents"])


import logging
import os
import sys
import subprocess
import urllib.parse

logger = logging.getLogger("backend.api.documents")


class DuplicateCheckRequest(BaseModel):
    sha256_hash: Optional[str] = None
    query_text: Optional[str] = None
    filename: Optional[str] = None


class OpenFileRequest(BaseModel):
    file_path: Optional[str] = None
    path: Optional[str] = None
    sha256_hash: Optional[str] = None
    sha256: Optional[str] = None
    reveal: bool = False


@router.get("/ledger")
def list_documents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by lifecycle_status: draft, review, final, truncated"),
    category: Optional[str] = Query(None, description="Filter by doc_type / category"),
    only_duplicates: bool = Query(False, description="Filter to documents with >1 physical locations"),
    query: Optional[str] = Query(None, description="Search keyword across filename and text snippet"),
    sort_by: str = Query("doc_date", description="Sort by column: doc_date, reception_date, due_date, canonical_filename, doc_type, maturity_score, lifecycle_status, location_count"),
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


def _sanitize_file_path(path_str: str) -> str:
    """Normalize file URIs, UNC paths, and Windows drive slashes."""
    if not path_str:
        return ""
    p = path_str.strip().strip('"').strip("'")
    if p.startswith("file:////"):
        p = "\\\\" + p[8:]
    elif p.startswith("file:///"):
        p = p[8:]
    elif p.startswith("file://"):
        p = "\\\\" + p[7:]

    p = urllib.parse.unquote(p).strip().strip('"').strip("'")
    if len(p) >= 3 and p[0] in ("/", "\\") and p[2] == ":" and p[1].isalpha():
        p = p[1:]
    return p


@router.post("/open-file")
@router.post("/open-local")
def open_file_endpoint(req: OpenFileRequest) -> Dict[str, Any]:
    """Open a file or reveal it in File Explorer on the local machine with automatic browser preview fallback."""
    raw_path = (req.file_path or req.path or "").strip()
    sha = (req.sha256_hash or req.sha256 or "").strip()
    target_path = _sanitize_file_path(raw_path)

    repo = DocumentRepository()
    if not target_path and sha:
        locations = repo.get_document_locations(sha)
        if locations:
            primary_loc = next((loc for loc in locations if loc.get("is_primary_source")), locations[0])
            target_path = _sanitize_file_path(primary_loc.get("absolute_path") or "")

    if not target_path:
        raise HTTPException(status_code=400, detail="Missing file path or SHA-256 with registered locations to open")

    # Locate file on disk
    norm_path = os.path.normpath(target_path)
    file_exists = os.path.exists(norm_path)

    # If target_path doesn't exist directly, check registered alternate locations
    if not file_exists and sha:
        locations = repo.get_document_locations(sha)
        for loc in locations:
            cand = _sanitize_file_path(loc.get("absolute_path") or "")
            cand_norm = os.path.normpath(cand)
            if os.path.exists(cand_norm):
                norm_path = cand_norm
                target_path = cand
                file_exists = True
                break

    view_url = f"/api/v1/documents/raw?path={urllib.parse.quote(target_path)}"
    if sha:
        view_url = f"/api/v1/documents/{sha}/view"

    try:
        if sys.platform == "win32":
            if not file_exists:
                raise FileNotFoundError(f"File not found on local disk: {norm_path}")

            logger.info(f"norm_path: {norm_path}, reveal: {req.reveal}")
            if req.reveal:
                if os.path.isdir(norm_path):
                    os.startfile(norm_path)
                elif os.path.isfile(norm_path):
                    subprocess.Popen(f'explorer.exe /select,"{norm_path}"')
                else:
                    parent = os.path.dirname(norm_path)
                    if parent and os.path.isdir(parent):
                        os.startfile(parent)
                    else:
                        raise FileNotFoundError(f"Path does not exist: {norm_path}")
            else:
                os.startfile(norm_path)

            return {
                "status": "success",
                "mode": "local_process",
                "message": f"Successfully launched {norm_path}",
                "path": norm_path,
                "view_url": view_url,
                "revealed": req.reveal
            }
        elif sys.platform == "darwin":
            if not file_exists:
                raise FileNotFoundError(f"File not found on disk: {target_path}")
            if req.reveal:
                subprocess.Popen(["open", "-R", target_path])
            else:
                subprocess.Popen(["open", target_path])
            return {
                "status": "success",
                "mode": "local_process",
                "message": f"Successfully launched {target_path}",
                "path": target_path,
                "view_url": view_url,
                "revealed": req.reveal
            }
        else:
            # Linux / Headless server / Remote deployment
            has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            if has_display and file_exists:
                if req.reveal:
                    subprocess.Popen(["xdg-open", str(Path(target_path).parent)])
                else:
                    subprocess.Popen(["xdg-open", target_path])
                return {
                    "status": "success",
                    "mode": "local_process",
                    "message": f"Successfully launched {target_path}",
                    "path": target_path,
                    "view_url": view_url,
                    "revealed": req.reveal
                }
            else:
                # Headless server or remote web deployment: signal frontend to open in browser
                return {
                    "status": "remote_fallback",
                    "mode": "browser_open",
                    "view_url": view_url,
                    "message": "Remote server cannot launch local desktop applications. Opening directly in browser.",
                    "path": target_path,
                    "revealed": req.reveal
                }
    except Exception as e:
        logger.error(f"Failed to open '{target_path}': {e}")
        status_code = 404 if isinstance(e, FileNotFoundError) else 500
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": str(e),
                "view_url": view_url,
                "message": f"Could not launch locally: {str(e)}"
            }
        )


def _render_sovereign_preview_html(doc: dict, target_path: str, sha256_hash: str) -> HTMLResponse:
    """Generate a rich, sovereign local storage preview page when viewing files remotely."""
    fname = html.escape(doc.get("canonical_filename") or "Document Preview")
    dt = html.escape(doc.get("doc_date") or "--")
    cat = html.escape((doc.get("doc_type") or "Document").replace("_", " ").title())
    status = html.escape((doc.get("lifecycle_status") or "draft").upper())
    maturity = int((doc.get("maturity_score") or 0) * 100)
    escaped_path = html.escape(target_path)
    snippet = html.escape(doc.get("text_snippet") or "No text snippet recorded in ledger.")
    escaped_sha = html.escape(sha256_hash or "")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{fname} - RepoScroller Sovereign Preview</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {{
      --bg: #0b0f19;
      --card-bg: #111827;
      --border: #1f2937;
      --accent: #38bdf8;
      --text: #f3f4f6;
      --muted: #9ca3af;
      --amber: #f59e0b;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 2.5rem 1rem;
      display: flex;
      justify-content: center;
    }}
    .container {{
      max-width: 820px;
      width: 100%;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 2.2rem;
      box-shadow: 0 10px 30px rgba(0,0,0,0.6);
    }}
    .badge {{
      display: inline-block;
      padding: 0.25rem 0.65rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      background: rgba(245, 158, 11, 0.15);
      color: var(--amber);
      border: 1px solid rgba(245, 158, 11, 0.3);
      margin-bottom: 1.2rem;
    }}
    h1 {{
      font-size: 1.35rem;
      margin: 0 0 0.5rem 0;
      word-break: break-all;
      line-height: 1.4;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 1rem;
      margin: 1.5rem 0;
      background: rgba(255,255,255,0.02);
      padding: 1.2rem;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.05);
    }}
    .meta-item label {{
      font-size: 0.75rem;
      color: var(--muted);
      display: block;
      margin-bottom: 0.25rem;
    }}
    .meta-item span {{
      font-size: 0.9rem;
      font-weight: 500;
    }}
    .path-box {{
      background: #000;
      padding: 0.9rem 1rem;
      border-radius: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.82rem;
      color: #7dd3fc;
      word-break: break-all;
      margin: 0.8rem 0 1.2rem 0;
      border: 1px solid #1e293b;
    }}
    .snippet-box {{
      background: rgba(0,0,0,0.3);
      padding: 1.2rem;
      border-radius: 8px;
      border-left: 3px solid var(--accent);
      margin: 1rem 0 1.5rem 0;
      font-size: 0.88rem;
      line-height: 1.6;
      color: #e2e8f0;
      white-space: pre-wrap;
      max-height: 350px;
      overflow-y: auto;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-top: 1rem;
    }}
    .btn {{
      padding: 0.65rem 1.2rem;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      border: none;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      transition: background 0.15s ease;
    }}
    .btn-primary {{
      background: var(--accent);
      color: #0b0f19;
      font-weight: 600;
    }}
    .btn-primary:hover {{
      background: #7dd3fc;
    }}
    .btn-secondary {{
      background: #1f2937;
      color: #f3f4f6;
      border: 1px solid #374151;
    }}
    .btn-secondary:hover {{
      background: #374151;
    }}
    .notice {{
      font-size: 0.8rem;
      color: var(--muted);
      margin-top: 2rem;
      border-top: 1px solid var(--border);
      padding-top: 1.2rem;
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <div class="container">
    <span class="badge">🔒 Sovereign Local Storage</span>
    <h1>📄 {fname}</h1>
    <p style="color: var(--muted); font-size: 0.88rem; margin: 0.25rem 0 1.2rem 0;">
      This file resides securely on your private local storage (LAN / NAS) and is not mirrored in the cloud.
    </p>

    <div class="meta-grid">
      <div class="meta-item"><label>Document Date</label><span>{dt}</span></div>
      <div class="meta-item"><label>Category</label><span>{cat}</span></div>
      <div class="meta-item"><label>Status</label><span>{status}</span></div>
      <div class="meta-item"><label>Maturity Score</label><span>{maturity}%</span></div>
    </div>

    <label style="font-size: 0.8rem; color: var(--muted);">Physical Network Path:</label>
    <div class="path-box" id="docPath">{escaped_path}</div>

    <div class="actions">
      <button class="btn btn-primary" onclick="copyPath()">📋 Copy Local Path</button>
      <a class="btn btn-secondary" href="http://127.0.0.1:8090/api/v1/documents/{escaped_sha}/view" target="_blank">↗ Open on Local PC1 (127.0.0.1:8090)</a>
    </div>

    <h3 style="font-size: 0.95rem; margin-top: 2rem; color: var(--accent);">📝 Ledger Text Extract</h3>
    <div class="snippet-box">{snippet}</div>

    <div class="notice">
      💡 <strong>Why am I seeing this preview?</strong> You are browsing RepoScroller via the remote cloud host (<code>afastudio.ch</code>). For data privacy and sovereign architecture, raw document files on <code>\\\\SyNAS</code> and Google Drive are kept strictly on your local network.
    </div>
  </div>

  <script>
    function copyPath() {{
      const path = document.getElementById('docPath').textContent;
      navigator.clipboard.writeText(path).then(() => {{
        alert('Copied to clipboard! You can paste this path into Windows File Explorer or Run dialog (Win + R).');
      }}).catch(() => {{
        prompt('Copy this path:', path);
      }});
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_content, status_code=200)


@router.get("/raw")
def get_raw_document(
    request: Request,
    path: str = Query(..., description="Absolute or normalized path of the document"),
    download: bool = Query(False, description="Force file download instead of inline view")
):
    """Serve/stream a raw document file directly to the browser for viewing or download."""
    clean_path = _sanitize_file_path(path)
    norm_path = os.path.normpath(clean_path)

    p = Path(norm_path)
    repo = DocumentRepository()
    doc = None
    sha = None

    if not p.exists() or not p.is_file():
        cur = repo.conn.cursor()
        cur.execute("""
            SELECT sha256_hash FROM document_locations 
            WHERE absolute_path = ? OR relative_path = ?
            LIMIT 1
        """, (clean_path, clean_path))
        row = cur.fetchone()
        if not row:
            cur.execute("""
                SELECT sha256_hash FROM document_ledger
                WHERE canonical_filename = ?
                LIMIT 1
            """, (p.name,))
            row = cur.fetchone()

        if row:
            sha = row[0]
            doc = repo.get_document_by_sha256(sha)
            locations = repo.get_document_locations(sha)
            for loc in locations:
                alt = Path(_sanitize_file_path(loc.get("absolute_path") or ""))
                if alt.exists() and alt.is_file():
                    p = alt
                    break

    if not p.exists() or not p.is_file():
        accept = request.headers.get("accept", "")
        if ("text/html" in accept or "*/*" in accept) and doc:
            return _render_sovereign_preview_html(doc, clean_path, sha or "")
        raise HTTPException(status_code=404, detail=f"File not found on server storage: {clean_path}")

    suffix = p.suffix.lower()
    media_type = "application/pdf" if suffix == ".pdf" else (
        "text/plain" if suffix in (".txt", ".md", ".log", ".yaml", ".json") else None
    )
    disp_type = "attachment" if download else "inline"
    return FileResponse(
        path=str(p),
        filename=p.name,
        media_type=media_type,
        content_disposition_type=disp_type
    )


@router.get("/{sha256_hash}/view")
def view_document_inline(sha256_hash: str, request: Request):
    """View document inline in the browser tab by SHA-256 (PDF or text)."""
    repo = DocumentRepository()
    doc = repo.get_document_by_sha256(sha256_hash)
    if not doc:
        raise HTTPException(status_code=404, detail="Document hash not found in ledger")
    locations = doc.get("locations", [])
    if not locations:
        raise HTTPException(status_code=404, detail="No registered physical file locations for this document")

    # Find the first existing location
    target_path = None
    for loc in locations:
        cand = _sanitize_file_path(loc.get("absolute_path") or "")
        if Path(cand).exists() and Path(cand).is_file():
            target_path = cand
            break

    if not target_path:
        primary_loc = next((loc for loc in locations if loc.get("is_primary_source")), locations[0])
        target_path = _sanitize_file_path(primary_loc.get("absolute_path") or "")

    p = Path(target_path)
    if not p.exists() or not p.is_file():
        accept = request.headers.get("accept", "")
        if "text/html" in accept or "*/*" in accept:
            return _render_sovereign_preview_html(doc, target_path, sha256_hash)
        raise HTTPException(status_code=404, detail=f"File not found on disk: {target_path}")

    suffix = p.suffix.lower()
    media_type = "application/pdf" if suffix == ".pdf" else (
        "text/plain" if suffix in (".txt", ".md", ".log", ".yaml", ".json") else None
    )
    filename = doc.get("canonical_filename") or p.name
    return FileResponse(
        path=str(p),
        filename=filename,
        media_type=media_type,
        content_disposition_type="inline"
    )


@router.get("/{sha256_hash}/download")
def download_document_file(sha256_hash: str):
    """Download the physical document file associated with this SHA-256."""
    repo = DocumentRepository()
    doc = repo.get_document_by_sha256(sha256_hash)
    if not doc:
        raise HTTPException(status_code=404, detail="Document hash not found in ledger")
    locations = doc.get("locations", [])
    if not locations:
        raise HTTPException(status_code=404, detail="No registered physical file locations for this document")

    # Check for first existing physical location
    target_path = None
    for loc in locations:
        cand = _sanitize_file_path(loc.get("absolute_path") or "")
        if Path(cand).exists() and Path(cand).is_file():
            target_path = cand
            break

    if not target_path:
        primary_loc = next((loc for loc in locations if loc.get("is_primary_source")), locations[0])
        target_path = _sanitize_file_path(primary_loc.get("absolute_path") or "")

    p = Path(target_path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail=f"File not found on local disk: {target_path}")
    filename = doc.get("canonical_filename") or p.name
    return FileResponse(path=str(p), filename=filename, content_disposition_type="attachment")


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
