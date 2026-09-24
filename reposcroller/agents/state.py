"""Typed state definitions for the LangGraph duplicate resolution workflow."""

from typing import TypedDict, List, Dict, Any, Optional


class CandidateDocument(TypedDict, total=False):
    sha256_hash: str
    canonical_filename: str
    simhash: str
    doc_type: str
    lifecycle_status: str
    completeness_score: float
    maturity_score: float
    match_type: str  # exact, simhash_near, fts_keyword
    similarity_score: float
    hamming_distance: int
    locations: List[Dict[str, Any]]
    parents: List[Dict[str, Any]]
    children: List[Dict[str, Any]]


class InterrogationState(TypedDict, total=False):
    # Input
    query: str
    file_path: Optional[str]
    sha256_hash: Optional[str]
    query_text: Optional[str]

    # Intermediate artifacts
    computed_sha256: Optional[str]
    computed_simhash: Optional[str]
    exact_match: Optional[Dict[str, Any]]
    candidates: List[CandidateDocument]
    canonical_document: Optional[Dict[str, Any]]
    status_category: str  # EXACT_MATCH, EVOLVED_VERSION, DRAFT_EXISTS, NOT_FOUND, MULTIPLE_MATCHES

    # Final Output
    answer: str
    recommendation: str
    sources: List[Dict[str, Any]]
