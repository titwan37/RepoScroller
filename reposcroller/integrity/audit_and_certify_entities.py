#!/usr/bin/env python3
"""Audit and certify candidate entities in SQLite using Ollama LLM validation."""

import re
import json
import logging
from typing import List, Dict, Any, Optional
import httpx

from reposcroller.config import settings
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ledger.db import transaction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("audit_certifier")

# Candidate verification batch size for Ollama context window
BATCH_SIZE = 25

LLM_VERIFY_PROMPT = """You are a strict data validation and knowledge-graph certification engine.
    Review the candidate entities extracted from a document repository.

    Rules:
    1. "person": Must be a bona fide human name (First Last). Reject roles, titles (e.g. "Software Engineer"), section titles ("Table of Contents"), or phrases.
    2. "organization": Must be a genuine company, firm, institution, or legal entity. Reject technical terms (e.g. "Memory Bank", "Cache Line"), UI labels, generic phrases ("Confidential"), or department titles.
    3. "contract_type": Must be an enforceable legal instrument (e.g. "NDA", "Employment Contract", "Lease"). Reject architecture papers, whitepapers, or manuals.
    4. "currency": Canonical monetary unit (ISO code or symbol: CHF, EUR, USD, GBP, JPY).
    5. "financial_pillar": Contractual financial classifications (rent, salary, mortgage, fee, fine, interest, insurance_premium).
    6. "valid": Set to false if it is noise, hallucinated, a document fragment, or boilerplate.
    7. "certified_type": If valid, classify into: person | organization | contract_type | document_category | statute | location | currency | financial_pillar. If invalid, set "rejected".

    Candidate Entities:
    {candidates_json}

    Respond strictly with a JSON array conforming to this schema:
    [
    {{"name": "...", "valid": true, "certified_type": "organization", "reason": "real enterprise"}},
    {{"name": "...", "valid": false, "certified_type": "rejected", "reason": "technical phrase"}}
    ]
    Do NOT write markdown formatting, backticks, or commentary outside the JSON array.
    """


def clean_llm_json_response(raw_text: str) -> List[Dict[str, Any]]:
    """Clean markdown fences and extract JSON array safely."""
    text = raw_text.strip()
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        text = match.group(0)
    else:
        text = re.sub(r'^(?:```json)?\s*', '', text, flags=re.IGNORECASE) 
        text = re.sub(r'\s*```$', '', text)
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception as err:
        logger.warning(f"Failed to parse LLM JSON response: {err}. Raw snippet: {raw_text[:120]}...")
    return []

def verify_batch_with_llm(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Send candidate batch to local Ollama chat endpoint."""
    simplified_candidates = [
        {"node_id": c["node_id"], "name": c["name"], "current_type": c["node_type"]}
        for c in candidates
    ]
    prompt = LLM_VERIFY_PROMPT.format(candidates_json=json.dumps(simplified_candidates, indent=2))

    chat_url = f"{settings.chat_url.rstrip('/')}/api/chat"
    target_model = settings.chat_model or settings.OLLAMA_MODEL_PC2

    try:
        resp = httpx.post(
            chat_url,
            json={
                "model": target_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                        "temperature": 0.0,
                        "num_ctx": 4096
                    }
                },
                timeout=180.0
            )
        if resp.status_code == 200:
            content = resp.json().get("message", {}).get("content", "")
            return clean_llm_json_response(content)
        else:
            logger.error(f"Ollama returned HTTP {resp.status_code}: {resp.text}")
    except Exception as exc:
        logger.error(f"Error querying Ollama at {chat_url}: {exc}")

    return []

def run_certification_audit(max_candidates: int = 2000, dry_run: bool = False, repo: Optional[DocumentRepository] = None, batch_size: int = BATCH_SIZE) -> Dict[str, Any]:
    """Fetch suspicious low-connectivity entities, verify with LLM, and purge or recategorize."""
    if repo is None:
        repo = DocumentRepository()

    logger.info("Querying candidate entities with degree <= 1 or doc_count <= 1...")

    # 1. Fetch unverified/suspicious nodes (degree 0-1, isolated or leaf nodes)
    with repo._lock:
        cur = repo.conn.cursor()
        cur.execute("""
            SELECT n.node_id, n.node_type, n.name,
                COUNT(DISTINCT l.sha256_hash) AS doc_count,
                (SELECT COUNT(*) FROM knowledge_edges e 
                    WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree
            FROM knowledge_nodes n
            LEFT JOIN document_entity_links l ON n.node_id = l.node_id
            WHERE n.node_type IN ('person', 'organization', 'contract_type')
            GROUP BY n.node_id, n.node_type, n.name
            HAVING degree <= 1 AND doc_count <= 2
            ORDER BY degree ASC, doc_count ASC
            LIMIT ?;
        """, (max_candidates,))
        candidates = [dict(r) for r in cur.fetchall()]

    total_candidates = len(candidates)
    logger.info(f"Retrieved {total_candidates} candidates for LLM certification.")
    if not total_candidates:
        return {
            "status": "idle",
            "total_candidates": 0,
            "purged_count": 0,
            "recategorized_count": 0,
            "retained_count": 0,
            "dry_run": dry_run
        }

    purged_count = 0
    recertified_count = 0
    retained_count = 0

    # 2. Process in batches
    for i in range(0, total_candidates, batch_size):
        batch = candidates[i:i + batch_size]
        logger.info(f"Verifying batch {i // batch_size + 1}/{(total_candidates + batch_size - 1) // batch_size} ({len(batch)} entities)...")
        
        verifications = verify_batch_with_llm(batch)
        verif_map = {v.get("name", "").strip().lower(): v for v in verifications if isinstance(v, dict)}

        nodes_to_delete = []
        nodes_to_update = []

        for item in batch:
            name_clean = item["name"].strip().lower()
            v = verif_map.get(name_clean)
            
            if not v:
                # If LLM omitted it or failed, check heuristic string length / garbage filters
                if len(item["name"]) <= 2 or len(item["name"]) > 60:
                    nodes_to_delete.append(item["node_id"])
                continue

            is_valid = v.get("valid", True)
            certified_type = v.get("certified_type", item["node_type"]).lower()

            if not is_valid or certified_type == "rejected":
                nodes_to_delete.append(item["node_id"])
            elif certified_type != item["node_type"] and certified_type in {
                "person", "organization", "contract_type", "document_category", "statute", "location"
            }:
                nodes_to_update.append((certified_type, item["node_id"]))
            else:
                retained_count += 1

        # 3. Apply changes to DB in a safe transaction
        if not dry_run and (nodes_to_delete or nodes_to_update):
            with repo._lock:
                with transaction(repo.conn) as cur:
                    if nodes_to_delete:
                        placeholders = ",".join("?" for _ in nodes_to_delete)
                        cur.execute(f"DELETE FROM document_entity_links WHERE node_id IN ({placeholders});", nodes_to_delete)
                        cur.execute(f"DELETE FROM knowledge_edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders});", nodes_to_delete + nodes_to_delete)
                        cur.execute(f"DELETE FROM knowledge_nodes WHERE node_id IN ({placeholders});", nodes_to_delete)
                    
                    for new_type, nid in nodes_to_update:
                        cur.execute("UPDATE knowledge_nodes SET node_type = ? WHERE node_id = ?;", (new_type, nid))

        purged_count += len(nodes_to_delete)
        recertified_count += len(nodes_to_update)

    logger.info("=== Certification Run Finished ===")
    logger.info(f"Purged False Positives: {purged_count}")
    logger.info(f"Recategorized Entities: {recertified_count}")
    logger.info(f"Retained Certified Entities: {retained_count}")

    return {
        "status": "completed",
        "total_candidates": total_candidates,
        "purged_count": purged_count,
        "recategorized_count": recertified_count,
        "retained_count": retained_count,
        "dry_run": dry_run
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Audit and clean hallucinated entities using LLM validation.")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum number of candidate entities to audit.")
    parser.add_argument("--dry-run", action="store_true", help="Run LLM checks without modifying the database.")
    args = parser.parse_args()

    run_certification_audit(max_candidates=args.limit, dry_run=args.dry_run)