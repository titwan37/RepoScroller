"""Multilingual Taxonomy & Dynamic Topic Refinement API routes."""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from reposcroller.ai.taxonomy import TaxonomyManager, TaxonomyCategory, TaxonomyRefiner, TaxonomyEvolutionEngine

router = APIRouter(prefix="/taxonomy", tags=["Taxonomy & Topics"])


class MergeRequest(BaseModel):
    source_category_id: str
    target_category_id: str


class RefineRequest(BaseModel):
    sample_size: int = 100


class EvolutionRequest(BaseModel):
    dry_run: bool = True
    limit: int = 500
    source_root_filter: Optional[str] = None
    target_version: str = "v1.0.0"


class SyncSkillRequest(BaseModel):
    skill_path: Optional[str] = None


@router.get("/")
def list_taxonomy() -> Dict[str, Any]:
    """Retrieve full global multilingual taxonomy (EN, FR, DE) with live document counts."""
    mgr = TaxonomyManager()
    categories = mgr.get_all_categories()
    return {
        "count": len(categories),
        "categories": [c.model_dump() for c in categories]
    }


@router.get("/versions")
def list_taxonomy_versions() -> Dict[str, Any]:
    """List all registered taxonomy versions in the ledger."""
    mgr = TaxonomyManager()
    versions = mgr.get_registered_versions()
    return {
        "count": len(versions),
        "versions": versions
    }


@router.post("/sync-skill")
def sync_taxonomy_from_skill(req: Optional[SyncSkillRequest] = None) -> Dict[str, Any]:
    """Sync taxonomy categories and metadata from declarative .skill.md specification."""
    mgr = TaxonomyManager()
    path = req.skill_path if req and req.skill_path else None
    return mgr.sync_from_skill(skill_path=path)


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


@router.get("/evolution/status")
def get_taxonomy_evolution_status(target_version: str = Query("v1.0.0", description="Target taxonomy version")) -> Dict[str, Any]:
    """Get document distribution by taxonomy version and pending evolution counts."""
    engine = TaxonomyEvolutionEngine()
    return engine.get_evolution_status(target_version=target_version)


@router.post("/evolve")
def evolve_document_taxonomy(req: EvolutionRequest) -> Dict[str, Any]:
    """
    Evolve documents to the target taxonomy version.
    Supports dry_run=True (preview) or dry_run=False (persist to ledger and enqueue to KB sidecar).
    """
    engine = TaxonomyEvolutionEngine()
    result = engine.evolve_ledger(
        dry_run=req.dry_run,
        limit=req.limit,
        source_root_filter=req.source_root_filter,
        target_version=req.target_version
    )
    return result
