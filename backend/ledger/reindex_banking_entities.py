"""Backfill and Re-index Engine for Banking Entities & Taxonomy Resolution.

Specifically resolves and normalizes 'Zuger Kantonalbank' (ZKB, ZugerKB, ZGKB)
and 'PostFinance SA' across the knowledge graph, document entity links, and ledger.
"""

import re
import json
import logging
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple

logger = logging.getLogger("reindex_banking")

CANONICAL_ZUGER_KB_ID = "organization_zuger_kantonalbank"
CANONICAL_POSTFINANCE_ID = "organization_postfinance_sa"
CANONICAL_ZKB_ZURICH_ID = "organization_zuercher_kantonalbank"

ZUG_BANKING_PATTERNS = [
    r"(?i)\b(?:Zuger\s+Kantonalbank(?:\s+AG)?|Zuger\s+Kantonal\s*Bank|ZugerKB|ZGKB)\b",
    r"(?i)\bzugerkb\.ch\b",
    r"(?i)\bCHE-105\.744\.410\b",
    r"(?i)\bCH10\s*0078\s*7\b",
    r"(?i)\b0787\b.*(?i:kantonalbank)",
]

POSTFINANCE_PATTERNS = [
    r"(?i)\b(?:PostFinance(?:\s+SA|\s+AG)?|Post\s*Finance)\b",
    r"(?i)\bpostfinance\.ch\b",
    r"(?i)\bPOFICHBEXXX\b",
]

MALFORMED_ZUG_NODES = {
    "organization_schuldzinsen_2016_zuger_kantonal_bank",
    "organization_hypothek_auskonto_zuger_kantonal_bank",
    "organization_zusatzblatt_2015_sv_zuger_kantonal_bank",
    "person_zuger_kantonalbank_direkt_pk",
    "organization_zuger_kantonal_bank",
}

MALFORMED_GARBAGE_NODES = {
    "organization_unstimmigkeiten_sind_der_bank",
    "organization_zugestellt_name_der_bank",
}


def get_db_path() -> Path:
    from backend.config import settings
    return getattr(settings, "DB_PATH", Path(__file__).resolve().parent.parent / "data" / "reposcroller_ledger.db")


def reindex_banking_entities(db_path: Path = None, verbose: bool = True) -> Dict[str, Any]:
    """Execute complete migration, entity merge, and historical backfill for banking organizations."""
    if db_path is None:
        db_path = get_db_path()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    stats = {
        "canonical_nodes_upserted": 0,
        "legacy_nodes_merged": 0,
        "garbage_nodes_purged": 0,
        "documents_linked_to_zuger_kb": 0,
        "documents_linked_to_postfinance": 0,
        "links_inserted": 0,
        "taxonomy_categories_updated": 0,
    }

    try:
        # 1. Upsert Canonical Nodes
        zuger_kb_props = json.dumps({
            "aliases": ["Zuger Kantonalbank", "Zuger Kantonal Bank", "ZugerKB", "ZGKB", "ZKB Zug", "ZKB", "Zuger Kantonalbank AG"],
            "location": "zug",
            "institution_type": "cantonal_bank",
            "clearing_code": "0787",
            "headquarters": "Bahnhofstrasse 1, Postfach, 6301 Zug",
            "website": "https://www.zugerkb.ch",
            "uid": "CHE-105.744.410 MWST"
        })
        cur.execute("""
            INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json)
            VALUES (?, 'organization', 'Zuger Kantonalbank', ?)
            ON CONFLICT(node_id) DO UPDATE SET
                name = 'Zuger Kantonalbank',
                properties_json = excluded.properties_json;
        """, (CANONICAL_ZUGER_KB_ID, zuger_kb_props))
        stats["canonical_nodes_upserted"] += 1

        postfinance_props = json.dumps({
            "aliases": ["PostFinance", "PostFinance SA", "PostFinance AG", "Swiss Post PostFinance"],
            "location": "bern",
            "institution_type": "financial_institution",
            "headquarters": "Mingerstrasse 20, 3030 Bern",
            "website": "https://www.postfinance.ch",
            "bic": "POFICHBEXXX"
        })
        cur.execute("""
            INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json)
            VALUES (?, 'organization', 'PostFinance SA', ?)
            ON CONFLICT(node_id) DO UPDATE SET
                name = 'PostFinance SA',
                properties_json = excluded.properties_json;
        """, (CANONICAL_POSTFINANCE_ID, postfinance_props))
        stats["canonical_nodes_upserted"] += 1

        # Ensure Location Nodes
        cur.execute("""
            INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json)
            VALUES ('location_zug', 'location', 'Zug', '{"canton": "ZG", "country": "CH"}')
            ON CONFLICT(node_id) DO NOTHING;
        """)
        cur.execute("""
            INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json)
            VALUES ('location_bern', 'location', 'Bern', '{"canton": "BE", "country": "CH"}')
            ON CONFLICT(node_id) DO NOTHING;
        """)

        # Ensure Canonical Edges (LOCATED_IN)
        cur.execute("""
            INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
            VALUES (?, 'location_zug', 'LOCATED_IN', 1.0, '{"context": "Headquarters"}')
            ON CONFLICT(source_id, target_id, relation_type) DO NOTHING;
        """, (CANONICAL_ZUGER_KB_ID,))
        cur.execute("""
            INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
            VALUES (?, 'location_bern', 'LOCATED_IN', 1.0, '{"context": "Headquarters"}')
            ON CONFLICT(source_id, target_id, relation_type) DO NOTHING;
        """, (CANONICAL_POSTFINANCE_ID,))

        # 2. Find and Consolidate Legacy & Malformed Nodes
        # Discover any other noisy nodes matching Zuger Kantonalbank variations
        cur.execute("""
            SELECT node_id FROM knowledge_nodes
            WHERE node_id != ?
            AND (
                LOWER(name) LIKE '%zuger kantonal%'
                OR LOWER(node_id) LIKE '%zuger_kantonal%'
                OR node_id IN ('person_zuger_kantonalbank_direkt_pk')
            );
        """, (CANONICAL_ZUGER_KB_ID,))
        found_legacy_zug = {r["node_id"] for r in cur.fetchall()} | MALFORMED_ZUG_NODES

        for old_id in found_legacy_zug:
            # Re-point links
            cur.execute("""
                UPDATE OR IGNORE document_entity_links
                SET node_id = ?
                WHERE node_id = ?;
            """, (CANONICAL_ZUGER_KB_ID, old_id))
            cur.execute("DELETE FROM document_entity_links WHERE node_id = ?;", (old_id,))

            # Re-point edges
            cur.execute("""
                UPDATE OR IGNORE knowledge_edges
                SET source_id = ?
                WHERE source_id = ?;
            """, (CANONICAL_ZUGER_KB_ID, old_id))
            cur.execute("""
                UPDATE OR IGNORE knowledge_edges
                SET target_id = ?
                WHERE target_id = ?;
            """, (CANONICAL_ZUGER_KB_ID, old_id))
            cur.execute("DELETE FROM knowledge_edges WHERE source_id = ? OR target_id = ?;", (old_id, old_id))

            # Delete old node
            cur.execute("DELETE FROM knowledge_nodes WHERE node_id = ?;", (old_id,))
            stats["legacy_nodes_merged"] += 1

        # Discover and consolidate fragmented PostFinance nodes
        cur.execute("""
            SELECT node_id FROM knowledge_nodes
            WHERE node_id != ?
            AND (
                LOWER(name) LIKE '%postfinance%'
                OR LOWER(node_id) LIKE '%postfinance%'
            );
        """, (CANONICAL_POSTFINANCE_ID,))
        found_legacy_pf = {r["node_id"] for r in cur.fetchall()}
        for old_id in found_legacy_pf:
            cur.execute("""
                UPDATE OR IGNORE document_entity_links
                SET node_id = ?
                WHERE node_id = ?;
            """, (CANONICAL_POSTFINANCE_ID, old_id))
            cur.execute("DELETE FROM document_entity_links WHERE node_id = ?;", (old_id,))

            cur.execute("""
                UPDATE OR IGNORE knowledge_edges
                SET source_id = ?
                WHERE source_id = ?;
            """, (CANONICAL_POSTFINANCE_ID, old_id))
            cur.execute("""
                UPDATE OR IGNORE knowledge_edges
                SET target_id = ?
                WHERE target_id = ?;
            """, (CANONICAL_POSTFINANCE_ID, old_id))
            cur.execute("DELETE FROM knowledge_edges WHERE source_id = ? OR target_id = ?;", (old_id, old_id))

            cur.execute("DELETE FROM knowledge_nodes WHERE node_id = ?;", (old_id,))
            stats["legacy_nodes_merged"] += 1

        # Purge Garbage Nodes
        for g_id in MALFORMED_GARBAGE_NODES:
            cur.execute("DELETE FROM document_entity_links WHERE node_id = ?;", (g_id,))
            cur.execute("DELETE FROM knowledge_edges WHERE source_id = ? OR target_id = ?;", (g_id, g_id))
            cur.execute("DELETE FROM knowledge_nodes WHERE node_id = ?;", (g_id,))
            stats["garbage_nodes_purged"] += 1

        # 3. Backfill Documents Referencing Zuger Kantonalbank Across Document Ledger & Chunks
        # A) Match via canonical_filename or text_snippet
        cur.execute("""
            SELECT sha256_hash, canonical_filename, text_snippet, doc_type
            FROM document_ledger;
        """)
        ledger_docs = cur.fetchall()

        zug_linked_shas: Set[str] = set()
        pf_linked_shas: Set[str] = set()

        for doc in ledger_docs:
            sha = doc["sha256_hash"]
            fname = doc["canonical_filename"] or ""
            snippet = doc["text_snippet"] or ""
            target_str = f"{fname} {snippet}"

            # Check Zuger Kantonalbank patterns
            is_zug_kb = False
            for pat in ZUG_BANKING_PATTERNS:
                if re.search(pat, target_str):
                    is_zug_kb = True
                    break

            # Disambiguate standalone ZKB
            if not is_zug_kb and re.search(r'\bZKB\b', target_str):
                has_zug = bool(re.search(r'(?i)\b(?:Zug|Steinhausen|Baar|Cham|Rotkreuz|6300|6301|6312|Falempin|Hypothek)\b', target_str))
                has_zurich = bool(re.search(r'(?i)\b(?:Zürich|Zurich|8001|8000|zkb\.ch)\b', target_str))
                if has_zug or not has_zurich:
                    is_zug_kb = True

            if is_zug_kb:
                zug_linked_shas.add(sha)

            # Check PostFinance patterns
            for pat in POSTFINANCE_PATTERNS:
                if re.search(pat, target_str):
                    pf_linked_shas.add(sha)
                    break

        # B) Match via document_chunks for deep body hits
        cur.execute("""
            SELECT DISTINCT sha256_hash, chunk_text
            FROM document_chunks
            WHERE LOWER(chunk_text) LIKE '%zuger kantonal%'
               OR LOWER(chunk_text) LIKE '%zugerkb%'
               OR LOWER(chunk_text) LIKE '%zgkb%'
               OR LOWER(chunk_text) LIKE '%che-105.744.410%'
               OR LOWER(chunk_text) LIKE '%0078 7007%'
               OR LOWER(chunk_text) LIKE '%postfinance%';
        """)
        for chunk_row in cur.fetchall():
            sha = chunk_row["sha256_hash"]
            c_text = chunk_row["chunk_text"] or ""

            for pat in ZUG_BANKING_PATTERNS:
                if re.search(pat, c_text):
                    zug_linked_shas.add(sha)
                    break

            for pat in POSTFINANCE_PATTERNS:
                if re.search(pat, c_text):
                    pf_linked_shas.add(sha)
                    break

        # 4. Insert Document Entity Links
        for sha in zug_linked_shas:
            cur.execute("""
                INSERT OR IGNORE INTO document_entity_links (sha256_hash, node_id, role, confidence)
                VALUES (?, ?, 'counterparty', 1.0);
            """, (sha, CANONICAL_ZUGER_KB_ID))
            if cur.rowcount > 0:
                stats["links_inserted"] += 1
            stats["documents_linked_to_zuger_kb"] += 1

            # Also ensure document is linked to location_zug
            cur.execute("""
                INSERT OR IGNORE INTO document_entity_links (sha256_hash, node_id, role, confidence)
                VALUES (?, 'location_zug', 'mention', 0.90);
            """, (sha,))

        for sha in pf_linked_shas:
            cur.execute("""
                INSERT OR IGNORE INTO document_entity_links (sha256_hash, node_id, role, confidence)
                VALUES (?, ?, 'counterparty', 1.0);
            """, (sha, CANONICAL_POSTFINANCE_ID))
            if cur.rowcount > 0:
                stats["links_inserted"] += 1
            stats["documents_linked_to_postfinance"] += 1

            # Ensure document is linked to location_bern
            cur.execute("""
                INSERT OR IGNORE INTO document_entity_links (sha256_hash, node_id, role, confidence)
                VALUES (?, 'location_bern', 'mention', 0.90);
            """, (sha,))

        # 5. Taxonomy Categorization Upgrade: Upgrade banking documents from 'other' or generic to 'financial_banking'
        all_bank_shas = list(zug_linked_shas | pf_linked_shas)
        if all_bank_shas:
            p_shas = ",".join("?" for _ in all_bank_shas)
            cur.execute(f"""
                UPDATE document_ledger
                SET doc_type = 'financial_banking'
                WHERE sha256_hash IN ({p_shas})
                AND (doc_type IS NULL OR doc_type IN ('other', 'unknown', 'document', 'legal_contract', 'formal_correspondence'))
                AND (
                    LOWER(canonical_filename) LIKE '%auszug%'
                    OR LOWER(canonical_filename) LIKE '%konto%'
                    OR LOWER(canonical_filename) LIKE '%zins%'
                    OR LOWER(canonical_filename) LIKE '%relevé%'
                    OR LOWER(canonical_filename) LIKE '%hypothek%'
                    OR LOWER(text_snippet) LIKE '%kontoauszug%'
                    OR LOWER(text_snippet) LIKE '%zinsausweis%'
                    OR LOWER(text_snippet) LIKE '%hypothek%'
                );
            """, all_bank_shas)
            stats["taxonomy_categories_updated"] = cur.rowcount

        conn.commit()

    except Exception as e:
        conn.rollback()
        logger.error(f"Re-indexing failed: {e}", exc_info=True)
        raise
    finally:
        conn.close()

    if verbose:
        print("=" * 60)
        print("BANKING ENTITY RE-INDEXING & RESOLUTION REPORT")
        print("=" * 60)
        print(f"Canonical Nodes Upserted:      {stats['canonical_nodes_upserted']}")
        print(f"Legacy Nodes Merged:           {stats['legacy_nodes_merged']}")
        print(f"Garbage Nodes Purged:          {stats['garbage_nodes_purged']}")
        print(f"Documents Linked to Zuger KB:  {stats['documents_linked_to_zuger_kb']}")
        print(f"Documents Linked to PostFinance: {stats['documents_linked_to_postfinance']}")
        print(f"New Entity Links Inserted:     {stats['links_inserted']}")
        print(f"Taxonomy Categories Upgraded:  {stats['taxonomy_categories_updated']}")
        print("=" * 60)

    return stats


if __name__ == "__main__":
    reindex_banking_entities()
