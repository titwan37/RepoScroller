"""API routes for system diagnostics, health telemetry, and live log streaming."""

import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Query
from reposcroller.api.diagnostics import diagnostic_buffer, get_system_health

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])
logger = logging.getLogger("reposcroller.api.diagnostics")


class FrontendErrorPayload(BaseModel):
    message: str = Field(..., description="Error or diagnostic message")
    stack: Optional[str] = Field(None, description="Javascript stack trace or details")
    level: str = Field("ERROR", description="Severity level: ERROR, WARNING, INFO")
    url: Optional[str] = Field(None, description="Origin URL or endpoint")
    extra: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Contextual metadata")


@router.get("/logs")
def get_diagnostic_logs(
    since_id: int = Query(0, ge=0, description="Fetch records strictly newer than this sequence ID"),
    limit: int = Query(200, ge=1, le=500, description="Maximum log records to return"),
    min_level: Optional[str] = Query(None, description="Minimum severity: DEBUG, INFO, WARNING, ERROR"),
    source: Optional[str] = Query(None, description="Filter by source: backend or frontend")
):
    """Fetch buffered diagnostic logs for live frontend console monitoring."""
    logs = diagnostic_buffer.get_logs(since_id=since_id, limit=limit, min_level=min_level)
    if source:
        logs = [l for l in logs if l.get("source") == source]
    return {
        "count": len(logs),
        "latest_id": logs[-1]["id"] if logs else since_id,
        "logs": logs
    }


@router.get("/health")
def get_diagnostics_health():
    """Retrieve detailed runtime health, storage mount connectivity, and database status."""
    return get_system_health()


@router.get("/workload")
def get_workload_telemetry(force: bool = Query(False, description="Force real-time network probe of nodes")):
    """Retrieve real-time telemetry on PC1 Localhost (Chat) vs PC2 Remote (CUDA Embeddings)."""
    from reposcroller.ai.telemetry import workload_telemetry
    from reposcroller.api.routes.sidecar import _worker
    data = workload_telemetry.get_node_probes(force=force)
    worker_status = _worker.get_continuous_status()
    data["pipeline"] = worker_status.get("pipeline", {})
    data["zoo"] = workload_telemetry.get_zoo_overview()
    data["chat_routing"] = workload_telemetry.get_chat_routing()
    return data


@router.get("/zoo")
def get_zoo_telemetry():
    """Retrieve unified real-time telemetry across the 5 subsystems ('The Zoo': PDF I/O, LAN, SQLite WAL, Embeddings, Chat)."""
    from reposcroller.ai.telemetry import workload_telemetry
    return workload_telemetry.get_zoo_overview()


@router.get("/ollama/ps")
def get_ollama_ps(node: str = Query("pc1", pattern="^(pc1|pc2)$")):
    """Proxy /api/ps probe to PC1 (127.0.0.1:11434) or PC2 (nitro-an51755:11434) for resilient browser telemetry."""
    import httpx
    from reposcroller.config import settings
    target_url = "http://127.0.0.1:11434/api/ps" if node == "pc1" else (
        settings.OLLAMA_EMBED_BASE_URL.rstrip("/") + "/api/ps" if settings.OLLAMA_EMBED_BASE_URL else "http://nitro-an51755:11434/api/ps"
    )
    try:
        with httpx.Client(timeout=3.5) as client:
            resp = client.get(target_url)
            if resp.status_code == 200:
                data = resp.json()
                data["node"] = node
                data["target_url"] = target_url
                data["online"] = True
                return data
    except Exception as e:
        logger.debug(f"Ollama ps probe failed for {node} ({target_url}): {e}")
    return {"models": [], "node": node, "target_url": target_url, "online": False}



@router.post("/clear")
def clear_diagnostic_logs():
    """Clear the buffered diagnostic logs."""
    diagnostic_buffer.clear()
    logger.info("Diagnostic log buffer cleared by client request.")
    return {"status": "cleared"}


@router.post("/report")
def report_frontend_error(payload: FrontendErrorPayload):
    """Ingest a frontend exception or diagnostic event into the unified log."""
    extra = payload.extra or {}
    if payload.url:
        extra["url"] = payload.url

    entry = diagnostic_buffer.log_frontend_issue(
        message=payload.message,
        stack=payload.stack,
        level=payload.level,
        extra=extra
    )
    return {"status": "recorded", "id": entry["id"]}


@router.post("/test-issue")
def trigger_test_issue(level: str = Query("WARNING", pattern="^(INFO|WARNING|ERROR)$")):
    """Trigger a synthetic diagnostic log for UI verification."""
    if level == "ERROR":
        logger.error("Synthetic test error generated: Database lock simulation or parity mismatch")
    elif level == "WARNING":
        logger.warning("Synthetic test warning: Network SMB share latency spike detected (>450ms)")
    else:
        logger.info("Synthetic test info: Background health check passed")
    return {"status": "triggered", "level": level}
