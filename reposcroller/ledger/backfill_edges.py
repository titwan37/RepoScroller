"""In-DB Co-occurrence Graph Edge and Entity Backfill.

Scans all documents for comprehensive Swiss and international locations (including
Ottenbach, Steinhausen, Zug, Switzerland, Baar, Cham, Rotkreuz, and major cantons/cities),
populates missing document links, and bridges co-occurrence edges to counterparties.
"""

import re
import time
import json
import logging
from typing import Dict, Any, List
from reposcroller.ledger.db import get_db_connection

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("reposcroller.backfill_edges")

# Comprehensive location definitions with canonical node_ids, display names, and matching patterns
COMPREHENSIVE_LOCATIONS = {
    "location_ottenbach": {
        "name": "Ottenbach",
        "pattern": r'\b(?:Ottenbach|8913\s*Ottenbach)\b'
    },
    "location_steinhausen": {
        "name": "Steinhausen",
        "pattern": r'\b(?:Steinhausen|6312\s*Steinhausen)\b'
    },
    "location_zug": {
        "name": "Zug",
        "pattern": r'\b(?:Zug|Kanton\s+Zug|Canton\s+de\s+Zoug|Zoug|6300\s*Zug)\b'
    },
    "location_switzerland": {
        "name": "Switzerland",
        "pattern": r'\b(?:Switzerland|Schweiz|Suisse|Svizzera|Helvetia|CH-\d{4})\b'
    },
    "location_baar": {
        "name": "Baar",
        "pattern": r'\b(?:Baar|6340\s*Baar)\b'
    },
    "location_cham": {
        "name": "Cham",
        "pattern": r'\b(?:Cham|6330\s*Cham)\b'
    },
    "location_rotkreuz": {
        "name": "Rotkreuz",
        "pattern": r'\b(?:Rotkreuz|Risch[- ]Rotkreuz|6343\s*Rotkreuz)\b'
    },
    "location_affoltern": {
        "name": "Affoltern am Albis",
        "pattern": r'\b(?:Affoltern\s+am\s+Albis|Affoltern|8910\s*Affoltern)\b'
    },
    "location_zurich": {
        "name": "Zurich",
        "pattern": r'\b(?:Zurich|Zürich|Kanton\s+Zürich|8001\s*Zürich|8000\s*Zürich)\b'
    },
    "location_geneva": {
        "name": "Geneva",
        "pattern": r'\b(?:Geneva|Genève|Genf|Canton\s+de\s+Genève)\b'
    },
    "location_lausanne": {
        "name": "Lausanne",
        "pattern": r'\b(?:Lausanne|1000\s*Lausanne)\b'
    },
    "location_basel": {
        "name": "Basel",
        "pattern": r'\b(?:Basel|Bâle|Basel-Stadt|Basel-Landschaft)\b'
    },
    "location_bern": {
        "name": "Bern",
        "pattern": r'\b(?:Bern|Berne|Canton\s+de\s+Berne)\b'
    },
    "location_luzern": {
        "name": "Luzern",
        "pattern": r'\b(?:Luzern|Lucerne)\b'
    },
    "location_st_gallen": {
        "name": "St. Gallen",
        "pattern": r'\b(?:St\.?\s*Gallen|Sankt\s+Gallen)\b'
    },
    "location_lugano": {
        "name": "Lugano",
        "pattern": r'\b(?:Lugano)\b'
    },
    "location_winterthur": {
        "name": "Winterthur",
        "pattern": r'\b(?:Winterthur)\b'
    },
    "location_neuchatel": {
        "name": "Neuchâtel",
        "pattern": r'\b(?:Neuchâtel|Neuchatel)\b'
    },
    "location_fribourg": {
        "name": "Fribourg",
        "pattern": r'\b(?:Fribourg|Freiburg)\b'
    },
    "location_sion": {
        "name": "Sion",
        "pattern": r'\b(?:Sion|Sitten)\b'
    },
    "location_chur": {
        "name": "Chur",
        "pattern": r'\b(?:Chur|Coire)\b'
    },
    "location_biel": {
        "name": "Biel/Bienne",
        "pattern": r'\b(?:Biel|Bienne)\b'
    },
    "location_aarau": {
        "name": "Aarau",
        "pattern": r'\b(?:Aarau|Aargau)\b'
    },
    "location_solothurn": {
        "name": "Solothurn",
        "pattern": r'\b(?:Solothurn|Soleure)\b'
    },
    "location_schaffhausen": {
        "name": "Schaffhausen",
        "pattern": r'\b(?:Schaffhausen|Schaffhouse)\b'
    },
    "location_bellinzona": {
        "name": "Bellinzona",
        "pattern": r'\b(?:Bellinzona)\b'
    },
    "location_vaud": {
        "name": "Vaud",
        "pattern": r'\b(?:Canton\s+de\s+Vaud|Vaud)\b'
    },
    "location_valais": {
        "name": "Valais",
        "pattern": r'\b(?:Valais|Wallis)\b'
    },
    "location_ticino": {
        "name": "Ticino",
        "pattern": r'\b(?:Ticino|Tessin)\b'
    },
    "location_paris": {
        "name": "Paris",
        "pattern": r'\b(?:Paris)\b'
    },
    "location_london": {
        "name": "London",
        "pattern": r'\b(?:London)\b'
    },
    "location_new_york": {
        "name": "New York",
        "pattern": r'\b(?:New\s+York|NYC)\b'
    },
    "location_berlin": {
        "name": "Berlin",
        "pattern": r'\b(?:Berlin)\b'
    },
    "location_frankfurt": {
        "name": "Frankfurt",
        "pattern": r'\b(?:Frankfurt)\b'
    },
    "location_munich": {
        "name": "Munich",
        "pattern": r'\b(?:Munich|München)\b'
    },
    "location_brussels": {
        "name": "Brussels",
        "pattern": r'\b(?:Brussels|Bruxelles)\b'
    },
    "location_amsterdam": {
        "name": "Amsterdam",
        "pattern": r'\b(?:Amsterdam)\b'
    },
    "location_milan": {
        "name": "Milan",
        "pattern": r'\b(?:Milan|Milano)\b'
    },
    "location_rome": {
        "name": "Rome",
        "pattern": r'\b(?:Rome|Roma)\b'
    },
    "location_madrid": {
        "name": "Madrid",
        "pattern": r'\b(?:Madrid)\b'
    },
    "location_vienna": {
        "name": "Vienna",
        "pattern": r'\b(?:Vienna|Wien)\b'
    },
    "location_tenerife": {
        "name": "Tenerife",
        "pattern": r'\b(?:Tenerife)\b'
    },
    "location_luxembourg": {
        "name": "Luxembourg",
        "pattern": r'\b(?:Luxembourg|Luxemburg)\b'
    },
    "location_liechtenstein": {
        "name": "Liechtenstein",
        "pattern": r'\b(?:Liechtenstein|Vaduz)\b'
    },
}


def run_cooccurrence_backfill() -> Dict[str, Any]:
    """Execute end-to-end entity scan and co-occurrence edge backfill."""
    conn = get_db_connection()
    cur = conn.cursor()

    t0 = time.time()
    logger.info("=== Starting Comprehensive Location & Edge Backfill ===")

    # 1. Clean up corrupted / malformed location entries
    logger.info("Cleaning up corrupted location entries...")
    cur.execute("""
        DELETE FROM knowledge_nodes
        WHERE node_type = 'location' 
          AND (LENGTH(name) > 60 OR name LIKE '%.pdf%' OR name LIKE 'Vous avez%');
    """)
    cleaned_rows = cur.rowcount
    conn.commit()
    if cleaned_rows > 0:
        logger.info(f"   -> Purged {cleaned_rows} invalid location node records.")

    # 2. Ensure all canonical location nodes exist in knowledge_nodes
    logger.info("Registering canonical location nodes...")
    for loc_id, loc_info in COMPREHENSIVE_LOCATIONS.items():
        cur.execute("""
            INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json, updated_at)
            VALUES (?, 'location', ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(node_id) DO UPDATE SET
                name = excluded.name,
                updated_at = CURRENT_TIMESTAMP;
        """, (loc_id, loc_info["name"], json.dumps({"region": "Europe", "country": "Switzerland"})))
    conn.commit()

    # 3. Scan document_ledger (canonical_filename, text_snippet) and chunks for location mentions
    logger.info("Scanning 26,000+ documents for location occurrences...")
    cur.execute("SELECT sha256_hash, canonical_filename, text_snippet FROM document_ledger")
    docs = cur.fetchall()

    compiled_patterns = {
        loc_id: re.compile(loc_info["pattern"], re.IGNORECASE)
        for loc_id, loc_info in COMPREHENSIVE_LOCATIONS.items()
    }

    new_links: List[tuple] = []
    location_match_counts = {loc_id: 0 for loc_id in COMPREHENSIVE_LOCATIONS}

    for d in docs:
        sha = d["sha256_hash"]
        fn = d["canonical_filename"] or ""
        snippet = d["text_snippet"] or ""
        text_corpus = f"{fn} {snippet}"

        for loc_id, regex in compiled_patterns.items():
            if regex.search(text_corpus):
                new_links.append((sha, loc_id, "mention", 1.0))
                location_match_counts[loc_id] += 1

    logger.info(f"Location scan matched {len(new_links):,} document-location pairs.")
    for loc_id, count in location_match_counts.items():
        if count > 0:
            loc_name = COMPREHENSIVE_LOCATIONS[loc_id]["name"]
            logger.info(f"   - {loc_name:20s}: {count:,} documents")

    # Insert document_entity_links in batches
    if new_links:
        cur.executemany("""
            INSERT OR IGNORE INTO document_entity_links (sha256_hash, node_id, role, confidence)
            VALUES (?, ?, ?, ?);
        """, new_links)
        inserted_links = cur.rowcount
        conn.commit()
        logger.info(f"   -> Inserted {inserted_links:,} new document-location link records.")

    # 4. Bridge Organizations and People to Locations (LOCATED_IN / RESIDES_IN)
    logger.info("Bridging Organizations and People to all identified Locations...")
    t_step = time.time()
    cur.execute("""
        INSERT OR IGNORE INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
        SELECT
            l_party.node_id AS source_id,
            l_loc.node_id AS target_id,
            CASE WHEN n_party.node_type = 'organization' THEN 'LOCATED_IN' ELSE 'RESIDES_IN' END AS relation_type,
            1.0 AS weight,
            json_object('context', 'Inferred from co-occurrence in ' || l_party.sha256_hash) AS properties_json
        FROM document_entity_links l_party
        JOIN knowledge_nodes n_party ON l_party.node_id = n_party.node_id
        JOIN document_entity_links l_loc ON l_party.sha256_hash = l_loc.sha256_hash
        JOIN knowledge_nodes n_loc ON l_loc.node_id = n_loc.node_id
        WHERE n_party.node_type IN ('person', 'organization')
          AND n_loc.node_type = 'location'
          AND l_party.node_id != l_loc.node_id;
    """)
    rows_loc = cur.rowcount
    conn.commit()
    logger.info(f"   -> Inserted {rows_loc:,} party-location edges ({time.time() - t_step:.2f}s)")

    # 5. Bridge Contract Types to Locations (JURISDICTION)
    logger.info("Bridging Contract Types to all identified Locations...")
    t_step = time.time()
    cur.execute("""
        INSERT OR IGNORE INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
        SELECT
            l_ct.node_id AS source_id,
            l_loc.node_id AS target_id,
            'JURISDICTION' AS relation_type,
            1.0 AS weight,
            json_object('context', 'Inferred from co-occurrence in ' || l_ct.sha256_hash) AS properties_json
        FROM document_entity_links l_ct
        JOIN knowledge_nodes n_ct ON l_ct.node_id = n_ct.node_id
        JOIN document_entity_links l_loc ON l_ct.sha256_hash = l_loc.sha256_hash
        JOIN knowledge_nodes n_loc ON l_loc.node_id = n_loc.node_id
        WHERE n_ct.node_type = 'contract_type'
          AND n_loc.node_type = 'location'
          AND l_ct.node_id != l_loc.node_id;
    """)
    rows_jur = cur.rowcount
    conn.commit()
    logger.info(f"   -> Inserted {rows_jur:,} jurisdiction edges ({time.time() - t_step:.2f}s)")

    # 6. Retrieve Final Location Verification Table
    cur.execute("""
        SELECT n.node_id, n.name,
               COUNT(DISTINCT l.sha256_hash) AS doc_count,
               (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree
        FROM knowledge_nodes n
        LEFT JOIN document_entity_links l ON n.node_id = l.node_id
        WHERE n.node_type = 'location'
        GROUP BY n.node_id, n.name
        HAVING doc_count > 0 OR degree > 0
        ORDER BY degree DESC, doc_count DESC;
    """)
    location_summary = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) FROM knowledge_edges")
    total_edges = cur.fetchone()[0]

    cur.execute("SELECT relation_type, COUNT(*) FROM knowledge_edges GROUP BY relation_type ORDER BY COUNT(*) DESC")
    type_breakdown = dict(cur.fetchall())

    conn.close()
    elapsed = time.time() - t0

    logger.info(f"=== Comprehensive Backfill Finished in {elapsed:.2f}s ===")
    logger.info(f"Total graph edges in system: {total_edges:,}")
    logger.info("Top Locations by Degree & Associated Documents:")
    for loc in location_summary[:20]:
        logger.info(f"   📍 {loc['name']:22s}: {loc['degree']:,} edges | {loc['doc_count']:,} docs")

    return {
        "status": "success",
        "total_edges": total_edges,
        "edge_types": type_breakdown,
        "locations": location_summary,
        "elapsed_seconds": round(elapsed, 2)
    }


if __name__ == "__main__":
    run_cooccurrence_backfill()
