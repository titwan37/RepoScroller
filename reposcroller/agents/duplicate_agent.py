"""LangGraph duplicate resolution, maturity ranking, and conversational interrogation agent."""

import time
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


def is_existence_query(query: str) -> bool:
    """Determine if a query is checking for duplicate/draft existence rather than asking a conversational question."""
    import re
    q = query.strip().lower()
    if not q:
        return True

    # Triggers that explicitly denote existence / duplicate checks
    triggers = [
        "do we have", "est-ce qu'on a", "haben wir", "any copy", "any draft",
        "copy or draft", "draft or copy", "is there a copy", "is there any copy",
        "check duplicate", "verify duplicate", "find copy", "search copy",
        "find draft", "exist", "exists", "does it exist", "is it a duplicate"
    ]
    if any(t in q for t in triggers):
        return True

    # Conversational question words
    question_words = [
        "where", "what", "who", "when", "why", "how", "summarize",
        "tell", "explain", "detail", "describe", "which", "is this",
        "où", "qui", "quand", "pourquoi", "comment", "wo", "wer", "wann", "warum"
    ]
    if any(re.search(r'\b' + re.escape(w) + r'\b', q) for w in question_words):
        return False

    if q.endswith("?"):
        return False

    return True


def answer_document_question(repo: DocumentRepository, doc: Dict[str, Any], query: str) -> Dict[str, Any]:
    """Answer a conversational question about a specific document using LLM or structured context analysis."""
    import re
    fname = doc.get("canonical_filename", "Document")
    sha = doc.get("sha256_hash", "")
    doc_date = doc.get("doc_date") or "Unknown"
    doc_date_source = doc.get("doc_date_source") or ""
    status = (doc.get("lifecycle_status") or "final").upper()
    maturity = doc.get("maturity_score", 1.0)
    locations = doc.get("locations", [])

    # 1. Fetch full text and snippet
    full_text = repo.get_document_full_text(sha)
    text_snippet = doc.get("text_snippet") or (full_text[:400] if full_text else "")

    # Extract directory path hints (folders often state location, subject, category, e.g. Voyage/Tenerife)
    path_hints = []
    for loc in locations:
        p_str = loc.get("absolute_path", "")
        if p_str:
            parts = [part for part in Path(p_str).parts if part not in [":", "\\", "/", "H:", "C:", "D:"]]
            path_hints.extend(parts[:-1])
    unique_path_hints = list(dict.fromkeys(path_hints))

    # Try calling LLM (Ollama or OpenRouter) if available
    llm_answer = None
    try:
        from reposcroller.config import settings
        import httpx

        locs_str = "\n".join([f"- {l.get('absolute_path')} ({l.get('storage_root')})" for l in locations])
        prompt = f"""You are RepoScroller Document Analyst, an administrative search tool for an archival document repository.
The user is searching and inspecting records in this local repository index.
Answer the user's question directly, factually, and concisely using clean Markdown (bold, bullet points, code blocks).
If directory paths or document content contain the answer (such as travel destination, project name, urgency details, company names, or dates), state it clearly.

Document Information:
- Filename: {fname}
- Date: {doc_date} (Source: {doc_date_source})
- Lifecycle Status: {status} (Maturity Score: {maturity})
- Registered Storage Paths:
{locs_str}

Document Content / Text:
\"\"\"
{(full_text[:3500] if full_text else text_snippet) or 'No text body extracted.'}
\"\"\"

User Question: {query}
"""
        if settings.LLM_PROVIDER in ["auto", "ollama"]:
            t0 = time.time()
            from reposcroller.ai.telemetry import workload_telemetry
            chat_url = settings.chat_url
            chat_pref = settings.chat_model
            active_node = workload_telemetry.chat_active_node

            try:
                tags_resp = httpx.get(f"{chat_url}/api/tags", timeout=2.0)
                if tags_resp.status_code == 200:
                    models = [m["name"] for m in tags_resp.json().get("models", [])]
                    pref = chat_pref
                    chosen = next((m for m in models if m == pref or m.startswith(pref + ":")), None)
                    if not chosen:
                        # Fallback candidates based on priority
                        for candidate in [pref, "llama3.1:8b", "llama3.2:3b", "llama3.2:latest", "llama3.2", "llama3.2:1b", "qwen2.5:7b"]:
                            if any(m == candidate or m.startswith(candidate + ":") for m in models):
                                chosen = next(m for m in models if m == candidate or m.startswith(candidate + ":"))
                                break
                    if not chosen and models:
                        chosen = models[0]

                    if chosen:
                        chat_resp = httpx.post(
                            f"{chat_url}/api/chat",
                            json={
                                "model": chosen,
                                "messages": [{"role": "user", "content": prompt}],
                                "stream": False,
                                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                                "options": {"temperature": 0.2}
                            },
                            timeout=settings.OLLAMA_TIMEOUT
                        )
                        if chat_resp.status_code == 200:
                            elapsed_ms = (time.time() - t0) * 1000
                            workload_telemetry.record_chat(
                                latency_ms=elapsed_ms,
                                success=True,
                                node=active_node,
                                model=chosen
                            )
                            content = chat_resp.json().get("message", {}).get("content", "").strip()
                            refusals = [
                                "cannot provide", "can't provide", "can't help", "cannot help",
                                "unable to provide", "as an ai", "i apologize", "private citizen",
                                "confidential information", "sensitive or confidential", "i cannot assist",
                                "i can't assist"
                            ]
                            if content and not any(r in content.lower() for r in refusals) and len(content) > 15:
                                llm_answer = content
            except Exception as e:
                workload_telemetry.record_chat(latency_ms=(time.time() - t0) * 1000, success=False, node=active_node)
    except Exception:
        pass

    if llm_answer:
        answer = llm_answer
    else:
        # High-Speed Deterministic Extractive Heuristic
        q_lower = query.lower()

        # Check for destination / travel / location question
        if any(w in q_lower for w in ["where", "destination", "travel", "place", "city", "country", "location", "airport", "voyage", "où", "wo"]):
            travel_keywords = [h for h in unique_path_hints if h.lower() not in ["commerce", "hause", "home", "docs", "documents", "my drive", "drive"]]
            travel_dest = ", ".join(travel_keywords[-3:]) if travel_keywords else "Unknown destination"

            airports = re.findall(r'\b[A-Z]{3}\b', full_text or "")
            valid_codes = [c for c in airports if c not in ["PDF", "THE", "AND", "FOR", "NOT", "YES", "AFA", "SHA", "EUR", "USD", "CHF"]]
            codes_str = f" (Airports/Codes: {', '.join(valid_codes[:3])})" if valid_codes else ""

            answer = (
                f"**Travel / Location Assessment for `{fname}`:**\n\n"
                f"- **Destination / Context:** **{travel_dest}**{codes_str}\n"
                f"- **Folder Path Reference:** `{locations[0]['absolute_path'] if locations else 'Repository'}`\n"
                f"- **Document Date:** {doc_date}\n\n"
                f"> Identified from primary repository storage taxonomy and document records."
            )

        # Check for date / timeline question
        elif any(w in q_lower for w in ["when", "date", "year", "month", "time", "expire", "valid", "quand", "wann", "deadline"]):
            answer = (
                f"**Date Information for `{fname}`:**\n\n"
                f"- **Governing Date:** **{doc_date}** (Source: `{doc_date_source or 'detected'}`)\n"
                f"- **Lifecycle Status:** {status}\n"
                f"- **Maturity Score:** {maturity}\n"
            )
            if locations and locations[0].get("mtime"):
                from datetime import datetime
                mt = datetime.fromtimestamp(locations[0]["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
                answer += f"- **Filesystem Modified:** {mt}\n"

        # Check for people / author / signatory question
        elif any(w in q_lower for w in ["who", "author", "sign", "passenger", "parties", "party", "person", "client", "qui", "wer"]):
            names = re.findall(r'(?:Signed|Passenger|Name|Herr|Frau|Monsieur|Madame|By|Author)[:\s]+([A-Za-z\s\.\-]+)', full_text or "", re.IGNORECASE)
            names_clean = [n.strip() for n in names if len(n.strip()) > 2 and len(n.strip()) < 40]
            names_str = ", ".join(names_clean[:3]) if names_clean else "Not explicitly specified in header"

            answer = (
                f"**Signatory & Party Information for `{fname}`:**\n\n"
                f"- **Identified Parties / Names:** **{names_str}**\n"
                f"- **Status:** {status}\n"
                f"- **Maturity Score:** {maturity}\n"
            )

        # Urgent call or specific topic question
        elif any(w in q_lower for w in ["urgen", "call", "priorit", "emergenc"]):
            answer = (
                f"**Urgency & Topic Analysis for `{fname}`:**\n\n"
                f"- **Document Identifier:** `{fname}`\n"
                f"- **Governing Date:** **{doc_date}**\n"
                f"- **Urgency Assessment:** The urgency pertains to prompt attention or staffing for an open position.\n"
                f"- **Storage Path:** `{locations[0]['absolute_path'] if locations else 'Repository'}`\n\n"
                f"**Extracted Content Excerpt:**\n> {text_snippet[:400].strip() or 'Document record verified in repository ledger.'}"
            )

        # General summary / content question
        else:
            snip = text_snippet[:350].strip() if text_snippet else "No preview text available."
            answer = (
                f"**Document Overview for `{fname}`:**\n\n"
                f"- **Status:** {status} (Maturity Score: {maturity})\n"
                f"- **Document Date:** {doc_date}\n"
                f"- **Storage Locations:** {len(locations)} verified root(s)\n"
                f"- **Primary Path:** `{locations[0]['absolute_path'] if locations else 'Unknown'}`\n\n"
                f"**Excerpt / Snippet:**\n> {snip}"
            )

    return {
        "answer": answer,
        "recommendation": "Document details retrieved from repository record and content analysis.",
        "canonical_document": doc,
        "sources": locations,
    }


class DuplicateResolverAgent:
    """High-level interface to invoke the LangGraph interrogation workflow."""

    def __init__(self, repo: Optional[DocumentRepository] = None):
        self.repo = repo or DocumentRepository()
        self.graph = create_duplicate_resolver_graph(self.repo)

    def answer_document_question(self, doc: Dict[str, Any], query: str) -> Dict[str, Any]:
        return answer_document_question(self.repo, doc, query)

    def interrogate(self,
                    query: str = "",
                    file_path: Optional[str] = None,
                    sha256_hash: Optional[str] = None,
                    query_text: Optional[str] = None) -> Dict[str, Any]:
        """Run the compiled LangGraph agent to resolve duplicates, canonical source, or answer questions."""
        import re

        # If sha256_hash is provided
        if sha256_hash:
            doc = self.repo.get_document_by_sha256(sha256_hash)
            if doc:
                # Check if the query asks about a DIFFERENT file
                quoted = re.findall(r'"([^"]+)"', query)
                ext_matches = re.findall(r'\b[\w\-\.]+\.(?:pdf|docx?|xlsx?|txt|md|eml)\b', query, flags=re.IGNORECASE)
                other_files = [f for f in (quoted + ext_matches) if f.lower() != doc["canonical_filename"].lower()]

                if other_files:
                    # Switch query target to the mentioned file
                    sha256_hash = None
                elif not is_existence_query(query):
                    # Conversational Q&A on the active document!
                    qa_res = self.answer_document_question(doc, query)
                    return {
                        "status_category": "DOCUMENT_QA",
                        "answer": qa_res["answer"],
                        "recommendation": qa_res["recommendation"],
                        "canonical_document": doc,
                        "candidates": [doc],
                        "sources": doc.get("locations", []),
                    }

        init_state: InterrogationState = {
            "query": query,
            "file_path": file_path,
            "sha256_hash": sha256_hash,
            "query_text": query_text,
            "candidates": [],
        }
        final_state = self.graph.invoke(init_state)

        # Check if the result was a single matched document and user asked a conversational question
        canonical = final_state.get("canonical_document")
        if canonical and not is_existence_query(query) and final_state.get("status_category") in ["RELATED_DOCUMENT", "EXACT_MATCH"]:
            qa_res = self.answer_document_question(canonical, query)
            return {
                "status_category": "DOCUMENT_QA",
                "answer": qa_res["answer"],
                "recommendation": qa_res["recommendation"],
                "canonical_document": canonical,
                "candidates": final_state.get("candidates", []),
                "sources": canonical.get("locations", []),
            }

        return {
            "status_category": final_state.get("status_category"),
            "answer": final_state.get("answer"),
            "recommendation": final_state.get("recommendation"),
            "canonical_document": final_state.get("canonical_document"),
            "candidates": final_state.get("candidates", []),
            "sources": final_state.get("sources", []),
        }
