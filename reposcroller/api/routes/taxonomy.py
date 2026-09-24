"""Multilingual Taxonomy & Dynamic Topic Refinement API routes."""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from reposcroller.ai.taxonomy import TaxonomyManager, TaxonomyCategory, TaxonomyRefiner

router = APIRouter(prefix="/taxonomy", tags=["Taxonomy & Topics"])


class MergeRequest(BaseModel):
    source_category_id: str
    target_category_id: str


class RefineRequest(BaseModel):
    sample_size: int = 100


@router.get("/")
def list_taxonomy() -> Dict[str, Any]:
    """Retrieve full global multilingual taxonomy (EN, FR, DE) with live document counts."""
    mgr = TaxonomyManager()
    categories = mgr.get_all_categories()
    return {
        "count": len(categories),
        "categories": [c.model_dump() for c in categories]
    }


@router.post("/categories")
def create_or_update_category(cat: TaxonomyCategory) -> Dict[str, Any]:
    """Add or update a canonical category in the global taxonomy."""
    mgr = TaxonomyManager()
    mgr.upsert_category(cat)
    return {"status": "saved", "category": cat.model_dump()}


@router.post("/merge")
def merge_topics(req: MergeRequest) -> Dict[str, Any]:
    """ASSOCIATION: Group/merge two categories (e.g. cross-language synonyms), re-tagging all documents."""
    mgr = TaxonomyManager()
    if not mgr.get_category(req.source_category_id):
        raise HTTPException(status_code=404, detail=f"Source category '{req.source_category_id}' not found")
    if not mgr.get_category(req.target_category_id):
        raise HTTPException(status_code=404, detail=f"Target category '{req.target_category_id}' not found")

    reassigned = mgr.merge_categories(req.source_category_id, req.target_category_id)
    return {
        "status": "merged",
        "source": req.source_category_id,
        "target": req.target_category_id,
        "documents_reassigned": reassigned
    }


@router.post("/refine")
def trigger_taxonomy_refinement(req: RefineRequest) -> Dict[str, Any]:
    """Trigger LLM-driven topic clustering: associates synonyms and dissociates broad categories into subtopics."""
    refiner = TaxonomyRefiner()
    result = refiner.run_refinement(sample_size=req.sample_size)
    return result
