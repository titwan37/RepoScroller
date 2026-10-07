# API routes for Operational Action Items (To-Dos) and Thematic Gravity Intelligence.
# Reload touch: 2026-10-07 22:18
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from backend.ledger.repository import DocumentRepository

router = APIRouter(prefix="/actions", tags=["Action Items & Thematic Gravity"])


class ResolveActionRequest(BaseModel):
    status: str = Field(default="completed", description="completed, dismissed, pending")
    fulfilled_by_sha256: Optional[str] = Field(default=None, description="SHA-256 of fulfilling document")
    fulfillment_evidence: Optional[str] = Field(default=None, description="Details or verification note")


class CreateActionRequest(BaseModel):
    sha256_hash: str = Field(..., description="Document SHA-256 hash")
    description: str = Field(..., description="Action description")
    action_type: str = Field(default="payment", description="payment, signature, reply, review, submission")
    theme_id: Optional[str] = Field(default=None, description="Taxonomy theme slug")
    counterparty: Optional[str] = Field(default=None, description="Counterparty name")
    amount: Optional[float] = Field(default=None, description="Monetary sum")
    currency: str = Field(default="CHF", description="Currency (CHF, EUR, USD)")
    due_date: Optional[str] = Field(default=None, description="ISO YYYY-MM-DD")


@router.get("/todos")
def list_action_items(
    status: Optional[str] = Query(default=None, description="Filter by status: pending, completed, dismissed"),
    theme_id: Optional[str] = Query(default=None, description="Filter by theme ID"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """Retrieve paginated operational action items (To-Dos) with document metadata and fulfillment links."""
    status_val = status if isinstance(status, str) else (None if status is None else str(status))
    theme_val = theme_id if isinstance(theme_id, str) else (None if theme_id is None else str(theme_id))
    limit_val = limit if isinstance(limit, int) else 100
    offset_val = offset if isinstance(offset, int) else 0

    repo = DocumentRepository()
    raw_items = repo.get_action_items(status=status_val, theme_id=theme_val, limit=limit_val, offset=offset_val)
    
    # Accurate database aggregate metrics
    cur = repo.conn.cursor()
    cur.execute("SELECT COUNT(*) FROM action_items")
    total_items = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM action_items WHERE status = 'pending'")
    pending_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM action_items WHERE status = 'completed'")
    completed_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM action_items WHERE status = 'pending' AND due_date IS NOT NULL AND due_date < date('now')")
    overdue_count = cur.fetchone()[0]

    # Normalize fields for UI compatibility
    todos = []
    for it in raw_items:
        todo = dict(it)
        todo["id"] = it.get("action_id")
        todo["title"] = it.get("description")
        todo["amount_due"] = it.get("amount")
        todo["target_entity"] = it.get("counterparty")
        todo["document_sha256"] = it.get("sha256_hash")
        todo["canonical_filename"] = it.get("original_filename")
        todos.append(todo)

    return {
        "status": "success",
        "total_returned": len(todos),
        "limit": limit,
        "offset": offset,
        "metrics": {
            "total_items": total_items,
            "pending_count": pending_count,
            "completed_count": completed_count,
            "overdue_count": overdue_count,
        },
        "todos": todos,
        "items": todos,
    }


@router.post("/{action_id}/resolve")
def resolve_action_item(action_id: int, req: ResolveActionRequest) -> Dict[str, Any]:
    """Mark an action item as completed or dismissed, attributing the fulfilling document for ALCOA+ compliance."""
    repo = DocumentRepository()
    success = repo.resolve_action_item(
        action_id=action_id,
        status=req.status,
        fulfilled_by_sha256=req.fulfilled_by_sha256,
        fulfillment_evidence=req.fulfillment_evidence,
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Action item #{action_id} not found")
    return {
        "status": "success",
        "action_id": action_id,
        "new_status": req.status,
        "fulfilled_by_sha256": req.fulfilled_by_sha256,
    }


@router.post("/create")
def create_action_item(req: CreateActionRequest) -> Dict[str, Any]:
    """Manually create an operational action item attached to a document."""
    repo = DocumentRepository()
    action_id = repo.create_action_item(
        sha256_hash=req.sha256_hash,
        description=req.description,
        action_type=req.action_type,
        theme_id=req.theme_id,
        counterparty=req.counterparty,
        amount=req.amount,
        currency=req.currency,
        due_date=req.due_date,
        status="pending",
    )
    return {
        "status": "success",
        "action_id": action_id,
        "sha256_hash": req.sha256_hash,
    }


@router.get("/thematic-gravity")
def get_thematic_gravity() -> Dict[str, Any]:
    """Retrieve real-time Thematic Gravity Scores across all lifecycle domains (volume, velocity, open obligations)."""
    repo = DocumentRepository()
    gravity_scores = repo.compute_thematic_gravity_scores()
    return {
        "status": "success",
        "themes_count": len(gravity_scores),
        "gravity_ranking": gravity_scores,
    }


@router.post("/cross-match-all")
def trigger_cross_match_pass() -> Dict[str, Any]:
    """Run a cross-matching auto-strikeout pass across recent documents against open pending To-Dos."""
    repo = DocumentRepository()
    recent_docs = repo.get_all_documents(limit=100, offset=0)
    total_struck_out = 0
    details = []

    for doc in recent_docs:
        sha = doc["sha256_hash"]
        text = repo.get_document_full_text(sha)
        if text:
            struck = repo.cross_match_and_strikeout_actions(doc, text)
            if struck:
                total_struck_out += len(struck)
                details.append({
                    "fulfilling_sha256": sha,
                    "filename": doc.get("canonical_filename"),
                    "struck_action_ids": struck,
                })

    return {
        "status": "success",
        "total_struck_out": total_struck_out,
        "matches": details,
    }
