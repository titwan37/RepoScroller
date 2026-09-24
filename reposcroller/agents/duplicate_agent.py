"""LangGraph duplicate resolution, maturity ranking, and conversational interrogation agent."""

from pathlib import Path
from typing import Dict, Any, List, Optional
from langgraph.graph import StateGraph, END
from reposcroller.config import settings
from reposcroller.agents.state import InterrogationState, CandidateDocument
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.integrity.hasher import compute_sha256
from reposcroller.integrity.simhash import compute_simhash
from reposcroller.extraction.text_extractor import extract_document_data


def make_ingest_node(repo: DocumentRepository):
    """Node: Hash and extract query inputs."""
    def ingest_or_hash(state: InterrogationState) -> Dict[str, Any]:
        computed_sha = state.get("sha256_hash")
        computed_sim = None
        q_text = state.get("query_text")

        query_val = state.get("query", "")
        if state.get("file_path"):
            fpath = Path(state["file_path"])
            if fpath.exists():
                try:
                    computed_sha = compute_sha256(fpath)
                    text, _ = extract_document_data(fpath)
                    q_text = text
                    computed_sim = compute_simhash(text)
                    if not query_val:
                        query_val = fpath.stem.replace("_", " ").replace("-", " ")
                except Exception:
                    pass

        if q_text and not computed_sim:
            computed_sim = compute_simhash(q_text)

        return {
            "query": query_val,
            "computed_sha256": computed_sha,
            "computed_simhash": computed_sim,
            "query_text": q_text,
            "candidates": state.get("candidates") or [],
        }
    return ingest_or_hash


def make_exact_check_node(repo: DocumentRepository):
    """Node: Exact SHA-256 match check against SQLite ledger."""
    def check_exact_match(state: InterrogationState) -> Dict[str, Any]:
        sha = state.get("computed_sha256")
        if not sha:
            return {"exact_match": None}

        doc = repo.get_document_by_sha256(sha)
        if doc:
            cand: CandidateDocument = {
                "sha256_hash": doc["sha256_hash"],
                "canonical_filename": doc["canonical_filename"],
                "simhash": doc["simhash"],
                "doc_type": doc["doc_type"],
                "lifecycle_status": doc["lifecycle_status"],
                "completeness_score": doc["completeness_score"],
                "maturity_score": doc["maturity_score"],
                "match_type": "exact",
                "similarity_score": 1.0,
                "hamming_distance": 0,
                "locations": doc.get("locations", []),
                "parents": doc.get("parents", []),
                "children": doc.get("children", []),
            }
            return {
                "exact_match": doc,
                "status_category": "EXACT_MATCH",
                "candidates": [cand],
                "canonical_document": doc,
            }
        return {"exact_match": None}
    return check_exact_match


def make_fuzzy_search_node(repo: DocumentRepository):
    """Node: Search near-duplicates via SimHash and lexical FTS5."""
    def fuzzy_search(state: InterrogationState) -> Dict[str, Any]:
        if state.get("exact_match"):
            return {}

        candidates: List[CandidateDocument] = []
        seen_shas = set()

        # 1. SimHash near-duplicate scan
        simhash = state.get("computed_simhash")
        if simhash and simhash != "0000000000000000":
            near_docs = repo.find_near_duplicates_simhash(
                query_simhash=simhash,
                max_hamming=settings.SIMHASH_HAMMING_THRESHOLD
            )
            for nd in near_docs:
                full_doc = repo.get_document_by_sha256(nd["sha256_hash"])
                if full_doc and nd["sha256_hash"] not in seen_shas:
                    seen_shas.add(nd["sha256_hash"])
                    candidates.append({
                        "sha256_hash": full_doc["sha256_hash"],
                        "canonical_filename": full_doc["canonical_filename"],
                        "simhash": full_doc["simhash"],
                        "doc_type": full_doc["doc_type"],
                        "lifecycle_status": full_doc["lifecycle_status"],
                        "completeness_score": full_doc["completeness_score"],
                        "maturity_score": full_doc["maturity_score"],
                        "match_type": "simhash_near",
                        "similarity_score": nd["similarity_score"],
                        "hamming_distance": nd["hamming_distance"],
                        "locations": full_doc.get("locations", []),
                        "parents": full_doc.get("parents", []),
                        "children": full_doc.get("children", []),
                    })

        # 2. FTS5 Lexical Search with user query string
        query = state.get("query", "").strip()
        if query:
            fts_results = repo.search_keyword_fts(query, limit=10)
            for r in fts_results:
                sha = r["sha256_hash"]
                if sha not in seen_shas:
                    seen_shas.add(sha)
                    full_doc = repo.get_document_by_sha256(sha)
                    if full_doc:
                        candidates.append({
                            "sha256_hash": full_doc["sha256_hash"],
                            "canonical_filename": full_doc["canonical_filename"],
                            "simhash": full_doc["simhash"],
                            "doc_type": full_doc["doc_type"],
                            "lifecycle_status": full_doc["lifecycle_status"],
                            "completeness_score": full_doc["completeness_score"],
                            "maturity_score": full_doc["maturity_score"],
                            "match_type": "fts_keyword",
                            "similarity_score": 0.5,
                            "hamming_distance": 16,
                            "locations": full_doc.get("locations", []),
                            "parents": full_doc.get("parents", []),
                            "children": full_doc.get("children", []),
                        })

        return {"candidates": candidates}
    return fuzzy_search


def make_lineage_resolution_node(repo: DocumentRepository):
    """Node: Analyze candidates and resolve single source of truth / canonical version."""
    def resolve_lineage(state: InterrogationState) -> Dict[str, Any]:
        candidates = state.get("candidates", [])
        if not candidates:
            return {
                "status_category": "NOT_FOUND",
                "canonical_document": None,
            }

        if state.get("status_category") == "EXACT_MATCH":
            return {}

        # Sort candidates by:
        # 1. Similarity score (descending)
        # 2. Maturity score (descending)
        # 3. Has primary source storage location
        def score_candidate(cand: CandidateDocument) -> float:
            base = cand.get("similarity_score", 0.0) * 0.5 + cand.get("maturity_score", 0.0) * 0.4
            locations = cand.get("locations", [])
            has_primary = any(loc.get("is_primary_source") for loc in locations)
            return base + (0.1 if has_primary else 0.0)

        candidates.sort(key=score_candidate, reverse=True)
        canonical = candidates[0]

        has_near_dup = any(c.get("match_type") == "simhash_near" for c in candidates)
        if has_near_dup:
            cat = "EVOLVED_VERSION" if canonical.get("maturity_score", 0) > 0.6 else "DRAFT_EXISTS"
        else:
            cat = "MULTIPLE_MATCHES" if len(candidates) > 1 else "RELATED_DOCUMENT"

        return {
            "candidates": candidates,
            "canonical_document": canonical,
            "status_category": cat,
        }
    return resolve_lineage


def make_format_response_node():
    """Node: Formats final human-readable interrogation answer and recommendation."""
    def format_response(state: InterrogationState) -> Dict[str, Any]:
        cat = state.get("status_category", "NOT_FOUND")
        canonical = state.get("canonical_document")
        candidates = state.get("candidates", [])

        if cat == "EXACT_MATCH" and canonical:
            fname = canonical["canonical_filename"]
            locs = canonical.get("locations", [])
            paths_str = "\n".join([f"- `{l.get('absolute_path')}` ({l.get('storage_root')})" for l in locs])
            answer = (
                f"**Exact Copy Available:** Bit-for-bit duplicate found for **{fname}**.\n\n"
                f"**Cryptographic Hash (SHA-256):** `{canonical['sha256_hash']}`\n"
                f"**Status:** {canonical.get('lifecycle_status', 'final').upper()}\n"
                f"**Maturity Score:** {canonical.get('maturity_score', 1.0)}\n\n"
                f"**Known Locations ({len(locs)}):**\n{paths_str}"
            )
            recommendation = "Do not re-upload or replicate. Reference the existing primary source."

        elif cat in ["EVOLVED_VERSION", "DRAFT_EXISTS"] and canonical:
            fname = canonical["canonical_filename"]
            locs = canonical.get("locations", [])
            paths_str = "\n".join([f"- `{l.get('absolute_path')}`" for l in locs])
            status = canonical.get("lifecycle_status", "unknown").upper()
            maturity = canonical.get("maturity_score", 0.0)

            answer = (
                f"**Existing Version Found:** An existing document matching **{fname}** is in the repository.\n\n"
                f"**Canonical Candidate:** `{fname}` ({status}, Maturity: {maturity})\n"
                f"**Locations:**\n{paths_str}\n\n"
                f"**Related Lineage Variants ({len(candidates)}):**\n"
            )
            for c in candidates[1:4]:
                answer += f"- `{c['canonical_filename']}` ({c.get('lifecycle_status')}, similarity: {c.get('similarity_score')})\n"

            recommendation = (
                f"The canonical copy is at `{locs[0]['absolute_path'] if locs else 'repository'}`. "
                "Verify if your copy is an amendment or should be linked as a child revision."
            )

        elif cat == "RELATED_DOCUMENT" and canonical:
            fname = canonical["canonical_filename"]
            locs = canonical.get("locations", [])
            paths_str = "\n".join([f"- `{l.get('absolute_path')}` ({l.get('storage_root')})" for l in locs]) if locs else "- Primary repository ledger"
            status = canonical.get('lifecycle_status', 'final').upper()
            maturity = canonical.get('maturity_score', 1.0)
            snippet = canonical.get('text_snippet', '')

            answer = (
                f"**Document Found:** **{fname}** is registered in the repository.\n\n"
                f"**Cryptographic Hash (SHA-256):** `{canonical['sha256_hash']}`\n"
                f"**Status:** {status}\n"
                f"**Maturity Score:** {maturity}\n\n"
                f"**Known Locations ({len(locs)}):**\n{paths_str}"
            )
            if snippet:
                answer += f"\n\n**Document Content / Snippet:**\n> {snippet}"

            recommendation = "The document exists in the repository. Reference the existing primary source."

        elif cat == "MULTIPLE_MATCHES":
            answer = f"Found {len(candidates)} related documents matching query:\n"
            for c in candidates[:5]:
                snip = f" — *{c.get('text_snippet')[:80]}...*" if c.get('text_snippet') else ""
                answer += f"- **{c['canonical_filename']}** ({c.get('lifecycle_status')}, Maturity: {c.get('maturity_score')}){snip}\n"
            recommendation = "Specify exact filename or select a document to inspect details."

        else:
            answer = "No matching copy or related document was found in any registered storage root."
            recommendation = "Document is unique and safe to ingest as a new original record."

        sources = []
        for c in candidates:
            sources.extend(c.get("locations", []))

        return {
            "answer": answer,
            "recommendation": recommendation,
            "sources": sources,
        }
    return format_response


def create_duplicate_resolver_graph(repo: Optional[DocumentRepository] = None):
    """Build and compile the LangGraph StateGraph workflow."""
    active_repo = repo or DocumentRepository()

    builder = StateGraph(InterrogationState)

    builder.add_node("ingest", make_ingest_node(active_repo))
    builder.add_node("exact_check", make_exact_check_node(active_repo))
    builder.add_node("fuzzy_search", make_fuzzy_search_node(active_repo))
    builder.add_node("lineage_resolution", make_lineage_resolution_node(active_repo))
    builder.add_node("format_response", make_format_response_node())

    builder.set_entry_point("ingest")
    builder.add_edge("ingest", "exact_check")

    def route_after_exact(state: InterrogationState):
        if state.get("exact_match"):
            return "format_response"
        return "fuzzy_search"

    builder.add_conditional_edges(
        "exact_check",
        route_after_exact,
        {"format_response": "format_response", "fuzzy_search": "fuzzy_search"}
    )

    builder.add_edge("fuzzy_search", "lineage_resolution")
    builder.add_edge("lineage_resolution", "format_response")
    builder.add_edge("format_response", END)

    return builder.compile()


class DuplicateResolverAgent:
    """High-level interface to invoke the LangGraph interrogation workflow."""

    def __init__(self, repo: Optional[DocumentRepository] = None):
        self.repo = repo or DocumentRepository()
        self.graph = create_duplicate_resolver_graph(self.repo)

    def interrogate(self,
                    query: str = "",
                    file_path: Optional[str] = None,
                    sha256_hash: Optional[str] = None,
                    query_text: Optional[str] = None) -> Dict[str, Any]:
        """Run the compiled LangGraph agent to resolve duplicates and canonical source."""
        init_state: InterrogationState = {
            "query": query,
            "file_path": file_path,
            "sha256_hash": sha256_hash,
            "query_text": query_text,
            "candidates": [],
        }
        final_state = self.graph.invoke(init_state)
        return {
            "status_category": final_state.get("status_category"),
            "answer": final_state.get("answer"),
            "recommendation": final_state.get("recommendation"),
            "canonical_document": final_state.get("canonical_document"),
            "candidates": final_state.get("candidates", []),
            "sources": final_state.get("sources", []),
        }
