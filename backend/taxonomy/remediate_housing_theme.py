"""Elevates 'Real Estate & Housing' (theme_real_estate_housing) in the Knowledge Universe.

1. Wires explicit topological edges in knowledge_edges to establish Centrality Degree:
   - contract_type_lease_contract -> CATEGORIZED_AS -> theme_real_estate_housing
   - financial_pillar_rent -> CATEGORIZED_AS -> theme_real_estate_housing
   - financial_pillar_mortgage -> CATEGORIZED_AS -> theme_real_estate_housing
   - theme_real_estate_housing -> LOCATED_IN -> location_ch_zg_6312 (Steinhausen)
   - theme_real_estate_housing -> LOCATED_IN -> location_zug (Kanton/Stadt Zug)
   - organization_alfred_muller_ag -> MANAGES -> theme_real_estate_housing
   - organization_zuger_kantonalbank -> FINANCES -> theme_real_estate_housing
   - theme_legal_justice -> DISPUTE_REGARDING -> theme_real_estate_housing
   - organization_kantonsgericht_zug -> ADJUDICATES_ACCESS_TO -> theme_real_estate_housing

2. Backfills multi-thematic document links in document_entity_links:
   - Tenancy contracts (lease_contract)
   - Housing invoices, utility bills, maintenance charges
   - Mortgage loans, interest certificates (Zinsausweise), banking financing
   - Property management & residential administration (Alfred Müller, Eschenstrasse, GarageBollinger)
   - Legal dispute proceedings (court orders, correspondence, hearings) regarding property access & eviction
"""

import json
import sqlite3
from pathlib import Path
from backend.config import settings

def remediate_housing():
    db_path = Path(settings.DB_PATH)
    print(f"Target Database: {db_path}")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("BEGIN TRANSACTION;")

    try:
        # --- 0. Ensure Canonical Nodes Exist ---
        print("\n0. Ensuring prerequisite canonical knowledge nodes exist...")
        # Kantonsgericht Zug
        cur.execute("""
            INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json, updated_at)
            VALUES (
                'organization_kantonsgericht_zug',
                'organization',
                'Kantonsgericht Zug',
                ?,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(node_id) DO UPDATE SET
                name = excluded.name,
                updated_at = CURRENT_TIMESTAMP;
        """, (json.dumps({"canonical_name": "Kantonsgericht Zug", "jurisdiction": "Kanton Zug"}),))

        # Ensure theme_real_estate_housing node is complete
        cur.execute("""
            INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json, updated_at)
            VALUES (
                'theme_real_estate_housing',
                'theme',
                'Real Estate & Housing',
                ?,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(node_id) DO UPDATE SET
                name = excluded.name,
                updated_at = CURRENT_TIMESTAMP;
        """, (json.dumps({
            "taxonomy_root": "theme_real_estate_housing",
            "is_hub": True,
            "description": "Property ownership, real estate assets, tenancy, housing operating costs, and access dispute proceedings"
        }),))

        # --- 1. Wire Topological Edges in knowledge_edges ---
        print("1. Wiring explicit knowledge_edges for theme_real_estate_housing...")
        edges_to_wire = [
            ("contract_type_lease_contract", "theme_real_estate_housing", "CATEGORIZED_AS", 1.0, {"context": "Lease and rental contract archetype"}),
            ("financial_pillar_rent", "theme_real_estate_housing", "CATEGORIZED_AS", 1.0, {"context": "Rent and lease payment obligations"}),
            ("financial_pillar_mortgage", "theme_real_estate_housing", "CATEGORIZED_AS", 1.0, {"context": "Hypothecary credit and real estate collateral"}),
            ("theme_real_estate_housing", "location_ch_zg_6312", "LOCATED_IN", 1.0, {"context": "Primary residence and property asset in Steinhausen"}),
            ("theme_real_estate_housing", "location_zug", "LOCATED_IN", 1.0, {"context": "Cantonal jurisdiction of property assets"}),
            ("organization_alfred_muller_ag", "theme_real_estate_housing", "MANAGES", 1.0, {"context": "Property management, real estate development, and administration"}),
            ("organization_zuger_kantonalbank", "theme_real_estate_housing", "FINANCES", 1.0, {"context": "Mortgage financing and interest certification"}),
            ("theme_legal_justice", "theme_real_estate_housing", "DISPUTE_REGARDING", 1.0, {"context": "Central substantive subject of legal proceedings: real estate access"}),
            ("organization_kantonsgericht_zug", "theme_real_estate_housing", "ADJUDICATES_ACCESS_TO", 1.0, {"context": "Judicial rulings regarding property access and eviction"}),
        ]

        for src, tgt, rel, weight, props in edges_to_wire:
            # Check both endpoints exist to satisfy FK constraints
            cur.execute("SELECT 1 FROM knowledge_nodes WHERE node_id = ?", (src,))
            src_ok = cur.fetchone()
            cur.execute("SELECT 1 FROM knowledge_nodes WHERE node_id = ?", (tgt,))
            tgt_ok = cur.fetchone()

            if src_ok and tgt_ok:
                cur.execute("""
                    INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                        weight = excluded.weight,
                        properties_json = excluded.properties_json;
                """, (src, tgt, rel, weight, json.dumps(props)))
                print(f"  [+] Wired edge: {src} --[{rel}]--> {tgt}")
            else:
                print(f"  [!] Skipped edge (missing node): {src} (ok={bool(src_ok)}) -> {tgt} (ok={bool(tgt_ok)})")

        # --- 2. Query Candidate Documents for theme_real_estate_housing ---
        print("\n2. Discovering candidate documents for Real Estate & Housing across all streams...")
        candidate_query = """
        SELECT DISTINCT dl.sha256_hash
        FROM document_ledger dl
        LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
        LEFT JOIN document_entity_links del_pillar ON dl.sha256_hash = del_pillar.sha256_hash 
             AND del_pillar.node_id IN ('financial_pillar_rent', 'financial_pillar_mortgage')
        WHERE dl.doc_type = 'lease_contract'
           OR del_pillar.node_id IS NOT NULL
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%immo%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%wohn%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%miet%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%hypo%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%liegenschaft%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%nebenkosten%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%zinsausweis%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%loyer%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%bail%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%regie%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%eschenstrasse%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%garagebollinger%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%hause-kosten%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%alfred%muller%'
           OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename) LIKE '%alfred%müller%'
           OR (
               dl.doc_type IN ('court_order', 'formal_correspondence', 'legal_contract')
               AND (
                   lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%ausweisung%'
                   OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%evakuierung%'
                   OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%miet%'
                   OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%wohnung%'
                   OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%zutritt%'
                   OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%accès%'
                   OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%eschenstrasse%'
                   OR lower(COALESCE(fl.relative_path, '') || ' ' || dl.canonical_filename || ' ' || COALESCE(dl.text_snippet, '')) LIKE '%alfred%muller%'
               )
           );
        """
        cur.execute(candidate_query)
        candidate_shas = [r[0] for r in cur.fetchall()]
        print(f"Total candidate documents found: {len(candidate_shas)}")

        # --- 3. Link candidate documents to theme_real_estate_housing ---
        print("3. Inserting multi-thematic links into document_entity_links...")
        batch_size = 500
        total_inserted = 0
        for i in range(0, len(candidate_shas), batch_size):
            batch = [(sha, 'theme_real_estate_housing', 'CATEGORIZED_AS', 1.0) for sha in candidate_shas[i:i + batch_size]]
            cur.executemany("""
                INSERT INTO document_entity_links (sha256_hash, node_id, role, confidence)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(sha256_hash, node_id, role) DO UPDATE SET confidence = 1.0;
            """, batch)
            total_inserted += len(batch)

        print(f"  [+] Successfully linked {total_inserted} documents to theme_real_estate_housing.")

        # Commit transaction
        conn.commit()
        print("\nHousing theme remediation successfully committed!")

        # --- 4. Verify Final Metrics ---
        print("\n=== FINAL VERIFICATION METRICS ===")
        cur.execute("""
            SELECT 
                (SELECT COUNT(*) FROM knowledge_edges WHERE source_id = 'theme_real_estate_housing' OR target_id = 'theme_real_estate_housing') AS degree,
                (SELECT COUNT(DISTINCT sha256_hash) FROM document_entity_links WHERE node_id = 'theme_real_estate_housing') AS doc_count;
        """)
        deg, cnt = cur.fetchone()
        print(f"Theme 'Real Estate & Housing' (theme_real_estate_housing):")
        print(f"  Centrality Degree: {deg}")
        print(f"  Document Count:    {cnt}")

    except Exception as e:
        conn.rollback()
        print(f"\nError during remediation! Rolled back. Details: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    remediate_housing()
