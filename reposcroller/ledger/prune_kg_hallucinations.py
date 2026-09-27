"""Standalone Offline Knowledge Graph Pruning & Recategorization Script.

Purges regex hallucinations, OCR noise, and decoupled document categories,
with optional batch LLM semantic verification via Ollama (/api/chat).

Usage:
    uv run python reposcroller/ledger/prune_kg_hallucinations.py --dry-run
    uv run python reposcroller/ledger/prune_kg_hallucinations.py --deterministic-only
    uv run python reposcroller/ledger/prune_kg_hallucinations.py --verify-llm --limit 200
"""

import argparse
import json
import logging
import re
import sys
from typing import List, Dict, Any, Tuple
import httpx

from reposcroller.config import settings
from reposcroller.ledger.repository import DocumentRepository

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("reposcroller.prune_kg")

KNOWN_CONTRACT_TYPES = {
    "employment_contract", "lease_contract", "lease_agreement", "nda",
    "service_agreement", "consulting_agreement", "license_agreement",
    "procurement_contract", "arbeitsvertrag", "mietvertrag",
    "dienstleistungsvertrag", "legal_contract"
}

KNOWN_LOCATIONS = {
    "zug", "kanton zug", "canton zug", "zurich", "zürich", "kanton zürich",
    "ottenbach", "steinhausen", "baar", "cham", "rotkreuz", "affoltern",
    "affoltern am albis", "geneva", "genève", "bern", "basel", "luzern",
    "st. gallen", "lugano", "winterthur", "switzerland", "schweiz", "suisse"
}

ORG_BLACKLIST_PATTERNS = [
    r"^memory bank$", r"^data bank$", r"^power bank$", r"^piggy bank$",
    r"^court order", r"^order document regarding", r"^supreme court decision",
    r"^system architecture", r"^technical architecture", r"^table of contents",
    r"^general terms", r"^confidential", r"^all rights reserved",
    r"vor dem kantonsgericht", r"an das kantonsgericht", r"^verschiebung",
    r"^kontoauszug", r"^buchungsanzeige", r"^belastung", r"^gutschrift",
    r"^peugeot motocycles sa$"
]

PERSON_BLACKLIST_PATTERNS = [
    r"^table of contents", r"^executive summary", r"^general terms",
    r"^project manager", r"^software engineer", r"^managing director",
    r"^technical overview", r"^dear sir", r"^yours sincerely",
    r"^first party", r"^second party", r"^unterschrift", r"^signature",
    r"^signed by", r"^arbeitgeber", r"^arbeitnehmer", r"^vermieter", r"^mieter"
]


def run_deterministic_pruning(repo: DocumentRepository, dry_run: bool = True) -> Dict[str, int]:
    """Execute fast, deterministic database pruning and recategorization."""
    stats = {
        "recategorized_doc_types": 0,
        "reclassified_locations": 0,
        "purged_ocr_noise": 0,
        "purged_blacklisted": 0,
    }

    with repo._lock:
        cur = repo.conn.cursor()

        # 1. Recategorize non-contract doc_types out of 'contract_type' into 'document_category'
        cur.execute("SELECT node_id, name FROM knowledge_nodes WHERE node_type = 'contract_type';")
        contract_nodes = cur.fetchall()
        for r in contract_nodes:
            nid, name = r["node_id"], r["name"]
            norm = name.strip().lower().replace(" ", "_")
            # If not a recognized true legal contract type
            is_contract = any(k in norm for k in KNOWN_CONTRACT_TYPES)
            if not is_contract:
                logger.info(f"[Recategorize] contract_type -> document_category: '{name}' ({nid})")
                stats["recategorized_doc_types"] += 1
                if not dry_run:
                    cur.execute("UPDATE knowledge_nodes SET node_type = 'document_category' WHERE node_id = ?;", (nid,))

        # 2. Reclassify locations wrongly stamped as 'organization' or 'person'
        cur.execute("SELECT node_id, name, node_type FROM knowledge_nodes WHERE node_type IN ('organization', 'person');")
        parties = cur.fetchall()
        for r in parties:
            nid, name, ntype = r["node_id"], r["name"], r["node_type"]
            clean_name = name.strip().lower()
            if clean_name in KNOWN_LOCATIONS:
                logger.info(f"[Reclassify Location] {ntype} -> location: '{name}' ({nid})")
                stats["reclassified_locations"] += 1
                if not dry_run:
                    cur.execute("UPDATE knowledge_nodes SET node_type = 'location' WHERE node_id = ?;", (nid,))

        # 3. Purge OCR noise / multiline entities with 0 edges
        cur.execute("""
            SELECT n.node_id, n.name, n.node_type
            FROM knowledge_nodes n
            LEFT JOIN knowledge_edges e ON (e.source_id = n.node_id OR e.target_id = n.node_id)
            WHERE (n.name LIKE '%\n%' OR n.name LIKE '%\r%' OR LENGTH(n.name) > 60 OR LENGTH(n.name) < 2)
              AND e.edge_id IS NULL;
        """)
        ocr_noise = cur.fetchall()
        for r in ocr_noise:
            nid, name, ntype = r["node_id"], r["name"], r["node_type"]
            repr_name = repr(name[:40])
            logger.info(f"[Purge OCR Noise] Deleting {ntype}: {repr_name} ({nid})")
            stats["purged_ocr_noise"] += 1
            if not dry_run:
                cur.execute("DELETE FROM document_entity_links WHERE node_id = ?;", (nid,))
                cur.execute("DELETE FROM knowledge_nodes WHERE node_id = ?;", (nid,))

        # 4. Purge blacklisted false-positives
        cur.execute("SELECT node_id, name, node_type FROM knowledge_nodes WHERE node_type IN ('organization', 'person');")
        remaining = cur.fetchall()
        for r in remaining:
            nid, name, ntype = r["node_id"], r["name"], r["node_type"]
            low = name.strip().lower()
            patterns = ORG_BLACKLIST_PATTERNS if ntype == "organization" else PERSON_BLACKLIST_PATTERNS
            if any(re.search(pat, low, re.IGNORECASE) for pat in patterns):
                logger.info(f"[Purge Blacklisted] Deleting {ntype}: '{name}' ({nid})")
                stats["purged_blacklisted"] += 1
                if not dry_run:
                    cur.execute("DELETE FROM knowledge_edges WHERE source_id = ? OR target_id = ?;", (nid, nid))
                    cur.execute("DELETE FROM document_entity_links WHERE node_id = ?;", (nid,))
                    cur.execute("DELETE FROM knowledge_nodes WHERE node_id = ?;", (nid,))

        if not dry_run:
            repo.conn.commit()

    return stats


def verify_entities_batch(candidates: List[Dict[str, Any]], ollama_url: str, model_name: str) -> List[Dict[str, Any]]:
    """Submits a batch of candidate entities to Ollama /api/chat for semantic verification."""
    prompt = f"""You are a strict data validation and knowledge-graph certification engine.
Review the following list of candidate entities extracted from a corporate document repository.

Rules:
1. "person": Must be a real human being's full name. Reject roles, titles, section headers, or boilerplate phrases.
2. "organization": Must be a bona fide commercial, governmental, or legal corporate body. Reject technical concepts (e.g., "Memory Bank", "Test Corp" in code snippets), UI labels, or generic terms.
3. "contract_type": Must be a specific legal instrument (e.g., "Employment Agreement", "Non-Disclosure Agreement", "Commercial Lease"). Reject document categories like "Technical Architecture", "Meeting Notes", "Whitepaper", or "Source Code".
4. If an entity is invalid or a false positive, set "valid": false.
5. If the entity is valid but misclassified, provide the corrected "certified_type" (options: person, organization, legal_contract, technical_document, location, statute, rejected).

Candidate Entities:
{json.dumps(candidates, indent=2)}

Output strictly valid JSON matching this schema:
[
  {{
    "name": "string",
    "valid": true,
    "certified_type": "person|organization|legal_contract|technical_document|location|statute|rejected",
    "reason": "short explanation"
  }}
]
Do NOT include explanations or Markdown fences outside the JSON.
"""

    resp = httpx.post(
        f"{ollama_url.rstrip('/')}/api/chat",
        json={
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0, "num_ctx": 4096}
        },
        timeout=120.0
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}")

    clean_json = resp.json().get("message", {}).get("content", "").strip()
    clean_json = re.sub(r'^```json\s*', '', clean_json, flags=re.IGNORECASE)
    clean_json = re.sub(r'\s*```$', '', clean_json)
    return json.loads(clean_json)


def run_llm_pruning(repo: DocumentRepository, ollama_url: str, model_name: str, limit: int = 200, batch_size: int = 25, dry_run: bool = True) -> Dict[str, int]:
    """Audit low-degree/suspicious entities in batches using LLM verification."""
    stats = {"audited": 0, "purged_by_llm": 0, "recategorized_by_llm": 0}

    with repo._lock:
        cur = repo.conn.cursor()
        # Find single-occurrence, degree-0 entities
        cur.execute("""
            SELECT n.node_id, n.node_type, n.name, COUNT(l.sha256_hash) AS doc_occurrences,
                   (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree
            FROM knowledge_nodes n
            LEFT JOIN document_entity_links l ON n.node_id = l.node_id
            WHERE n.node_type IN ('person', 'organization')
            GROUP BY n.node_id, n.node_type, n.name
            HAVING doc_occurrences = 1 AND degree = 0
            ORDER BY n.name ASC
            LIMIT ?;
        """, (limit,))
        candidates_raw = cur.fetchall()

    if not candidates_raw:
        logger.info("No isolated single-document entities found for LLM review.")
        return stats

    logger.info(f"Found {len(candidates_raw)} isolated candidates for LLM semantic verification...")

    for i in range(0, len(candidates_raw), batch_size):
        chunk = candidates_raw[i:i + batch_size]
        candidates_payload = [
            {"node_id": r["node_id"], "name": r["name"], "current_type": r["node_type"]}
            for r in chunk
        ]

        try:
            results = verify_entities_batch(candidates_payload, ollama_url=ollama_url, model_name=model_name)
            res_by_name = {res["name"].lower(): res for res in results if isinstance(res, dict) and "name" in res}

            with repo._lock:
                cur = repo.conn.cursor()
                for c in candidates_payload:
                    stats["audited"] += 1
                    nid = c["node_id"]
                    v_res = res_by_name.get(c["name"].lower())

                    if v_res:
                        is_valid = v_res.get("valid", True)
                        cert_type = v_res.get("certified_type", c["current_type"]).lower()
                        reason = v_res.get("reason", "")

                        if not is_valid or cert_type == "rejected":
                            logger.info(f"[LLM Reject] Deleting {c['current_type']}: '{c['name']}' ({reason})")
                            stats["purged_by_llm"] += 1
                            if not dry_run:
                                cur.execute("DELETE FROM document_entity_links WHERE node_id = ?;", (nid,))
                                cur.execute("DELETE FROM knowledge_nodes WHERE node_id = ?;", (nid,))
                        elif cert_type != c["current_type"]:
                            mapped_type = cert_type if cert_type in ["organization", "person", "location", "statute"] else "document_category"
                            logger.info(f"[LLM Recategorize] {c['current_type']} -> {mapped_type}: '{c['name']}' ({reason})")
                            stats["recategorized_by_llm"] += 1
                            if not dry_run:
                                cur.execute("UPDATE knowledge_nodes SET node_type = ? WHERE node_id = ?;", (mapped_type, nid))

                if not dry_run:
                    repo.conn.commit()

        except Exception as e:
            logger.warning(f"Batch LLM verification failed for slice [{i}:{i+batch_size}]: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="RepoScroller KG Hallucination Pruning & Recategorization")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Simulate without modifying database")
    parser.add_argument("--deterministic-only", action="store_true", default=False, help="Run only deterministic rule passes")
    parser.add_argument("--verify-llm", action="store_true", default=False, help="Run batch LLM semantic verification via Ollama")
    parser.add_argument("--limit", type=int, default=150, help="Max candidates for LLM verification")
    parser.add_argument("--batch-size", type=int, default=25, help="Batch size per LLM prompt")
    parser.add_argument("--ollama-url", type=str, default="", help="Override Ollama base URL")
    parser.add_argument("--model", type=str, default="", help="Override Ollama chat model")

    args = parser.parse_args()

    repo = DocumentRepository()
    logger.info(f"=== RepoScroller Knowledge Graph Pruning Tool (dry_run={args.dry_run}) ===")

    # Step 1: Deterministic pass
    det_stats = run_deterministic_pruning(repo, dry_run=args.dry_run)
    logger.info(f"Deterministic pass complete: {det_stats}")

    # Step 2: LLM Verification pass (if requested)
    if args.verify_llm and not args.deterministic_only:
        ollama_url = args.ollama_url or getattr(settings, "OLLAMA_EMBED_BASE_URL", "http://NITRO-AN51755:11434")
        model = args.model or getattr(settings, "chat_model", "qwen2.5:latest")
        logger.info(f"Starting LLM semantic verification against {ollama_url} (model: {model})...")
        llm_stats = run_llm_pruning(
            repo,
            ollama_url=ollama_url,
            model_name=model,
            limit=args.limit,
            batch_size=args.batch_size,
            dry_run=args.dry_run
        )
        logger.info(f"LLM verification complete: {llm_stats}")

    logger.info("Knowledge Graph Pruning run finished successfully.")


if __name__ == "__main__":
    main()
