"""Hierarchical Geographic Taxonomy and Cantonal-Municipal Disambiguation Engine.

Maintains an administrative hierarchy (Canton -> Municipalities / Postal Codes)
and provides recursive SQLite CTEs for transitive cantonal document rollups
and organization entity linking (Zuger Kantonalbank, PostFinance SA).
"""

import re
import logging
import sqlite3
from typing import List, Dict, Any, Tuple, Set

logger = logging.getLogger("reposcroller.geo_taxonomy")

CANONICAL_GEO_SEED = [
    # --- CANTON ZUG (CH-ZG: 11 Canonical Municipalities) ---
    {"geo_id": "CH-ZG", "name": "Kanton Zug", "entity_type": "canton", "postal_code": None, "parent_id": None, "bfs_nr": None},
    {"geo_id": "CH-ZG-6300", "name": "Stadt Zug", "entity_type": "municipality", "postal_code": "6300", "parent_id": "CH-ZG", "bfs_nr": 1711},
    {"geo_id": "CH-ZG-6312", "name": "Steinhausen", "entity_type": "municipality", "postal_code": "6312", "parent_id": "CH-ZG", "bfs_nr": 1708},
    {"geo_id": "CH-ZG-6340", "name": "Baar", "entity_type": "municipality", "postal_code": "6340", "parent_id": "CH-ZG", "bfs_nr": 1701},
    {"geo_id": "CH-ZG-6330", "name": "Cham", "entity_type": "municipality", "postal_code": "6330", "parent_id": "CH-ZG", "bfs_nr": 1702},
    {"geo_id": "CH-ZG-6343", "name": "Risch-Rotkreuz", "entity_type": "municipality", "postal_code": "6343", "parent_id": "CH-ZG", "bfs_nr": 1707},
    {"geo_id": "CH-ZG-6314", "name": "Unterägeri", "entity_type": "municipality", "postal_code": "6314", "parent_id": "CH-ZG", "bfs_nr": 1709},
    {"geo_id": "CH-ZG-6315", "name": "Oberägeri", "entity_type": "municipality", "postal_code": "6315", "parent_id": "CH-ZG", "bfs_nr": 1706},
    {"geo_id": "CH-ZG-6331", "name": "Hünenberg", "entity_type": "municipality", "postal_code": "6331", "parent_id": "CH-ZG", "bfs_nr": 1703},
    {"geo_id": "CH-ZG-6313", "name": "Menzingen", "entity_type": "municipality", "postal_code": "6313", "parent_id": "CH-ZG", "bfs_nr": 1704},
    {"geo_id": "CH-ZG-6318", "name": "Walchwil", "entity_type": "municipality", "postal_code": "6318", "parent_id": "CH-ZG", "bfs_nr": 1710},
    {"geo_id": "CH-ZG-6345", "name": "Neuheim", "entity_type": "municipality", "postal_code": "6345", "parent_id": "CH-ZG", "bfs_nr": 1705},

    # --- CANTON ZÜRICH (CH-ZH) ---
    {"geo_id": "CH-ZH", "name": "Kanton Zürich", "entity_type": "canton", "postal_code": None, "parent_id": None, "bfs_nr": None},
    {"geo_id": "CH-ZH-8000", "name": "Stadt Zürich", "entity_type": "municipality", "postal_code": "8000", "parent_id": "CH-ZH", "bfs_nr": 261},
    {"geo_id": "CH-ZH-8913", "name": "Ottenbach", "entity_type": "municipality", "postal_code": "8913", "parent_id": "CH-ZH", "bfs_nr": 11},
    {"geo_id": "CH-ZH-8910", "name": "Affoltern am Albis", "entity_type": "municipality", "postal_code": "8910", "parent_id": "CH-ZH", "bfs_nr": 2},
    {"geo_id": "CH-ZH-8400", "name": "Winterthur", "entity_type": "municipality", "postal_code": "8400", "parent_id": "CH-ZH", "bfs_nr": 230},

    # --- CANTON LUZERN (CH-LU) ---
    {"geo_id": "CH-LU", "name": "Kanton Luzern", "entity_type": "canton", "postal_code": None, "parent_id": None, "bfs_nr": None},
    {"geo_id": "CH-LU-6000", "name": "Stadt Luzern", "entity_type": "municipality", "postal_code": "6000", "parent_id": "CH-LU", "bfs_nr": 1061},

    # --- CANTON BERN (CH-BE) ---
    {"geo_id": "CH-BE", "name": "Kanton Bern", "entity_type": "canton", "postal_code": None, "parent_id": None, "bfs_nr": None},
    {"geo_id": "CH-BE-3000", "name": "Stadt Bern", "entity_type": "municipality", "postal_code": "3000", "parent_id": "CH-BE", "bfs_nr": 351},
]

CANONICAL_ORGS_SEED = [
    {
        "org_id": "org_zkb",
        "canonical_name": "Zuger Kantonalbank",
        "hq_geo_id": "CH-ZG-6300",
        "jurisdiction_geo_id": "CH-ZG",
        "aliases": [
            "ZUGER KANTONALBANK",
            "ZUGER KANTONAL BANK",
            "ZUGERKB",
            "ZGKB",
            "ZKB ZUG",
            "BAHNHOFSTRASSE 1, 6301 ZUG",
            "BAHNHOFSTRASSE 1, 6300 ZUG",
            "POSTFACH, 6301 ZUG",
            "CHE-105.830.407"
        ]
    },
    {
        "org_id": "org_postfinance",
        "canonical_name": "PostFinance SA",
        "hq_geo_id": "CH-BE-3000",
        "jurisdiction_geo_id": "CH-BE",
        "aliases": [
            "POSTFINANCE SA",
            "POSTFINANCE AG",
            "POSTFINANCE",
            "POSTFINANCE SCHWEIZ",
            "MINGERSTRASSE 20, 3030 BERN",
            "POSTFACH, 3005 BERN",
            "CHE-114.583.749"
        ]
    },
    {
        "org_id": "org_wwz",
        "canonical_name": "WWZ Energie AG",
        "hq_geo_id": "CH-ZG-6312",
        "jurisdiction_geo_id": "CH-ZG",
        "aliases": [
            "WWZ ENERGIE AG",
            "WWZENERGIE AG",
            "WASSERWERKE ZUG AG",
            "WWZ TELEKOM AG",
            "CHOLERSTRASSE 24, 6312 STEINHAUSEN"
        ]
    },
    {
        "org_id": "org_kantonsgericht_zg",
        "canonical_name": "Kantonsgericht Zug",
        "hq_geo_id": "CH-ZG-6300",
        "jurisdiction_geo_id": "CH-ZG",
        "aliases": [
            "KANTONSGERICHT ZUG",
            "OBERGERICHT ZUG",
            "GERICHTE DES KANTONS ZUG",
            "KIRCHMATTSTRASSE 12, 6300 ZUG"
        ]
    }
]


def init_geo_taxonomy(conn: sqlite3.Connection) -> None:
    """Ensure schema tables exist and seed the geographic & organization hierarchy."""
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS geo_taxonomy (
            geo_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            postal_code TEXT,
            parent_id TEXT,
            bfs_nr INTEGER,
            FOREIGN KEY(parent_id) REFERENCES geo_taxonomy(geo_id)
        );

        CREATE TABLE IF NOT EXISTS organization_entities (
            org_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            hq_geo_id TEXT,
            jurisdiction_geo_id TEXT,
            FOREIGN KEY(hq_geo_id) REFERENCES geo_taxonomy(geo_id),
            FOREIGN KEY(jurisdiction_geo_id) REFERENCES geo_taxonomy(geo_id)
        );

        CREATE TABLE IF NOT EXISTS organization_aliases (
            alias_pattern TEXT NOT NULL,
            org_id TEXT NOT NULL,
            PRIMARY KEY(alias_pattern, org_id),
            FOREIGN KEY(org_id) REFERENCES organization_entities(org_id)
        );

        CREATE TABLE IF NOT EXISTS document_geo_links (
            sha256_hash TEXT NOT NULL,
            geo_id TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            PRIMARY KEY(sha256_hash, geo_id)
        );

        CREATE TABLE IF NOT EXISTS document_org_links (
            sha256_hash TEXT NOT NULL,
            org_id TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            PRIMARY KEY(sha256_hash, org_id),
            FOREIGN KEY(org_id) REFERENCES organization_entities(org_id)
        );

        CREATE TABLE IF NOT EXISTS knowledge_nodes (
            node_id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL,
            name TEXT NOT NULL,
            properties_json TEXT
        );

        CREATE TABLE IF NOT EXISTS knowledge_edges (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            properties_json TEXT,
            PRIMARY KEY(source_id, target_id, relation_type)
        );

        CREATE INDEX IF NOT EXISTS idx_doc_geo_lookup ON document_geo_links(geo_id, sha256_hash);
        CREATE INDEX IF NOT EXISTS idx_doc_org_lookup ON document_org_links(org_id, sha256_hash);
    """)

    # 1. Seed geo_taxonomy
    for item in CANONICAL_GEO_SEED:
        cur.execute("""
            INSERT INTO geo_taxonomy (geo_id, name, entity_type, postal_code, parent_id, bfs_nr)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(geo_id) DO UPDATE SET
                name = excluded.name,
                entity_type = excluded.entity_type,
                postal_code = excluded.postal_code,
                parent_id = excluded.parent_id,
                bfs_nr = excluded.bfs_nr;
        """, (item["geo_id"], item["name"], item["entity_type"], item["postal_code"], item["parent_id"], item["bfs_nr"]))

    # 2. Seed organization entities and aliases
    for org in CANONICAL_ORGS_SEED:
        cur.execute("""
            INSERT INTO organization_entities (org_id, canonical_name, hq_geo_id, jurisdiction_geo_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(org_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                hq_geo_id = excluded.hq_geo_id,
                jurisdiction_geo_id = excluded.jurisdiction_geo_id;
        """, (org["org_id"], org["canonical_name"], org["hq_geo_id"], org["jurisdiction_geo_id"]))

        for alias in org.get("aliases", []):
            cur.execute("""
                INSERT OR IGNORE INTO organization_aliases (alias_pattern, org_id)
                VALUES (?, ?);
            """, (alias.upper().strip(), org["org_id"]))

    conn.commit()


def get_sub_regions(conn: sqlite3.Connection, target_geo_or_name: str) -> List[Dict[str, Any]]:
    """Execute a recursive SQLite CTE to retrieve a region and all transitive descendants."""
    cur = conn.cursor()
    query_param = target_geo_or_name.strip().lower()

    cur.execute("""
        WITH RECURSIVE sub_regions AS (
            SELECT geo_id, name, entity_type, postal_code, parent_id, bfs_nr, 0 AS depth
            FROM geo_taxonomy
            WHERE LOWER(geo_id) = ?
               OR (LOWER(geo_id) = 'ch-zg' AND ? IN ('zug', 'kanton zug', 'kanton-zug', 'zg'))
               OR (LOWER(geo_id) = 'ch-zh' AND ? IN ('zürich', 'zurich', 'kanton zürich', 'kanton zurich', 'zh'))
               OR (LOWER(name) = ? AND entity_type = 'canton')

            UNION ALL

            SELECT g.geo_id, g.name, g.entity_type, g.postal_code, g.parent_id, g.bfs_nr, sr.depth + 1
            FROM geo_taxonomy g
            JOIN sub_regions sr ON g.parent_id = sr.geo_id
        )
        SELECT DISTINCT geo_id, name, entity_type, postal_code, parent_id, bfs_nr, depth
        FROM sub_regions
        ORDER BY depth ASC, name ASC;
    """, (query_param, query_param, query_param, query_param))

    rows = cur.fetchall()
    if rows:
        return [
            {
                "geo_id": r[0], "name": r[1], "entity_type": r[2],
                "postal_code": r[3], "parent_id": r[4], "bfs_nr": r[5], "depth": r[6]
            }
            for r in rows
        ]

    cur.execute("""
        SELECT geo_id, name, entity_type, postal_code, parent_id, bfs_nr, 0 AS depth
        FROM geo_taxonomy
        WHERE LOWER(name) LIKE ? OR LOWER(geo_id) LIKE ?;
    """, (f"%{query_param}%", f"%{query_param}%"))
    return [
        {
            "geo_id": r[0], "name": r[1], "entity_type": r[2],
            "postal_code": r[3], "parent_id": r[4], "bfs_nr": r[5], "depth": r[6]
        }
        for r in cur.fetchall()
    ]


def classify_text_geo(text: str, filename: str = "") -> Set[Tuple[str, float]]:
    """Extract and disambiguate geographic entities across all Canton Zug municipalities."""
    combined = f"{filename} {text or ''}".lower()
    results: Set[Tuple[str, float]] = set()

    # --- CANTON ZUG: All 11 Municipalities ---
    # 1. Stadt Zug (6300, 6301, 6302, 6303)
    if re.search(r'\b(630[0-3]|stadt\s+zug)\b', combined):
        results.add(("CH-ZG-6300", 1.0))
        results.add(("CH-ZG", 0.95))

    # 2. Steinhausen (6312)
    if re.search(r'\b(6312|steinhausen)\b', combined):
        results.add(("CH-ZG-6312", 1.0))
        results.add(("CH-ZG", 0.95))

    # 3. Baar (6340, 6341, Allenwinden)
    if re.search(r'\b(634[01]|baar|allenwinden)\b', combined):
        results.add(("CH-ZG-6340", 1.0))
        results.add(("CH-ZG", 0.95))

    # 4. Cham (6330, 6332, Hagendorn)
    if re.search(r'\b(633[02]|cham|hagendorn)\b', combined):
        results.add(("CH-ZG-6330", 1.0))
        results.add(("CH-ZG", 0.95))

    # 5. Risch-Rotkreuz (6343, Rotkreuz, Buonas, Holzhäusern)
    if re.search(r'\b(6343|rotkreuz|risch|buonas|holzhäusern)\b', combined):
        results.add(("CH-ZG-6343", 1.0))
        results.add(("CH-ZG", 0.95))

    # 6. Unterägeri (6314)
    if re.search(r'\b(6314|unterägeri|unteraegeri)\b', combined):
        results.add(("CH-ZG-6314", 1.0))
        results.add(("CH-ZG", 0.95))

    # 7. Oberägeri (6315, Alosen, Morgarten)
    if re.search(r'\b(6315|oberägeri|oberaegeri|alosen|morgarten)\b', combined):
        results.add(("CH-ZG-6315", 1.0))
        results.add(("CH-ZG", 0.95))

    # 8. Hünenberg (6331, 6333)
    if re.search(r'\b(633[13]|hünenberg|huenenberg)\b', combined):
        results.add(("CH-ZG-6331", 1.0))
        results.add(("CH-ZG", 0.95))

    # 9. Menzingen (6313, Finstersee)
    if re.search(r'\b(6313|menzingen|finstersee)\b', combined):
        results.add(("CH-ZG-6313", 1.0))
        results.add(("CH-ZG", 0.95))

    # 10. Walchwil (6318)
    if re.search(r'\b(6318|walchwil)\b', combined):
        results.add(("CH-ZG-6318", 1.0))
        results.add(("CH-ZG", 0.95))

    # 11. Neuheim (6345)
    if re.search(r'\b(6345|neuheim)\b', combined):
        results.add(("CH-ZG-6345", 1.0))
        results.add(("CH-ZG", 0.95))

    # --- CANTON ZÜRICH & Surrounds ---
    if re.search(r'\b(8913|ottenbach)\b', combined):
        results.add(("CH-ZH-8913", 1.0))
        results.add(("CH-ZH", 0.95))

    if re.search(r'\b(8910|affoltern\s+am\s+albis)\b', combined):
        results.add(("CH-ZH-8910", 1.0))
        results.add(("CH-ZH", 0.95))

    if re.search(r'\b(80\d{2}|zürich|zurich|stadt\s+zürich)\b', combined):
        results.add(("CH-ZH-8000", 1.0))
        results.add(("CH-ZH", 0.95))

    if re.search(r'\b(8400|winterthur)\b', combined):
        results.add(("CH-ZH-8400", 1.0))
        results.add(("CH-ZH", 0.95))

    # --- Disambiguation for "Zug" and "Zuger" ---
    if re.search(r'\bzuger\b', combined):
        results.add(("CH-ZG", 0.90))

    if re.search(r'\bzug\b', combined):
        # Exclude common German idioms (train / in the course of)
        is_idiom = bool(re.search(r'\b(im\s+zuge|mit\s+dem\s+zug|per\s+zug|abfahrt\s+zug)\b', combined))
        if not is_idiom:
            if re.search(r'(kanton\s+zug|kt\.\s*zug|kantonsgericht|kantonspolizei|obergericht|kanzlei|steuerverwaltung\s+zug)', combined):
                results.add(("CH-ZG", 1.0))
            elif re.search(r'(\d{4}\s+zug|postfach[^\n,]+zug|ch-630[0-9])', combined):
                results.add(("CH-ZG-6300", 1.0))
                results.add(("CH-ZG", 0.95))
            else:
                results.add(("CH-ZG", 0.85))

    return results


def classify_text_orgs(text: str, filename: str = "") -> Set[Tuple[str, float]]:
    """Extract canonical organizations (e.g. Zuger Kantonalbank, PostFinance SA)."""
    combined = f"{filename} {text or ''}".upper()
    found: Set[Tuple[str, float]] = set()

    org_patterns = {
        "org_zkb": [
            r"\bZUGER\s+KANTONALBANK\b",
            r"\bZUGER\s+KANTONAL\s+BANK\b",
            r"\bZUGERKB\b",
            r"\bZGKB\b",
            r"\bZKB\s+ZUG\b",
            r"BAHNHOFSTRASSE\s+1[,\s]+630[01]\s+ZUG"
        ],
        "org_postfinance": [
            r"\bPOSTFINANCE\s+SA\b",
            r"\bPOSTFINANCE\s+AG\b",
            r"\bPOSTFINANCE\b",
            r"MINGERSTRASSE\s+20[,\s]+3030\s+BERN"
        ],
        "org_wwz": [
            r"\bWWZ\s+ENERGIE\s+AG\b",
            r"\bWWZENERGIE\s+AG\b",
            r"\bWASSERWERKE\s+ZUG\b",
            r"\bWWZ\s+TELEKOM\b",
            r"CHOLERSTRASSE\s+24[,\s]+6312\s+STEINHAUSEN"
        ],
        "org_kantonsgericht_zg": [
            r"\bKANTONSGERICHT\s+ZUG\b",
            r"\bOBERGERICHT\s+ZUG\b",
            r"KIRCHMATTSTRASSE\s+12[,\s]+6300\s+ZUG"
        ]
    }

    for org_id, patterns in org_patterns.items():
        for pat in patterns:
            if re.search(pat, combined, re.IGNORECASE):
                found.add((org_id, 1.0))
                break

    return found


def backfill_document_geo_links(conn: sqlite3.Connection) -> Dict[str, int]:
    """Scan documents and chunks to link documents to locations, organizations, and 3D universe edges."""
    init_geo_taxonomy(conn)
    cur = conn.cursor()

    logger.info("Starting entity extraction and knowledge graph backfill...")

    # Batch query fetching documents and initial chunk text in a single pass
    cur.execute("""
        SELECT l.sha256_hash, l.canonical_filename, l.text_snippet,
               IFNULL(GROUP_CONCAT(c.chunk_text, ' '), '') AS chunks_sample
        FROM document_ledger l
        LEFT JOIN (
            SELECT sha256_hash, chunk_text
            FROM document_chunks
            WHERE chunk_index < 5
        ) c ON l.sha256_hash = c.sha256_hash
        GROUP BY l.sha256_hash;
    """)
    docs = cur.fetchall()

    doc_geo_batch: List[Tuple[str, str, float]] = []
    doc_org_batch: List[Tuple[str, str, float]] = []

    for row in docs:
        sha = row[0]
        fname = row[1] or ""
        snippet = row[2] or ""
        chunks = row[3] or ""
        full_text = f"{snippet} {chunks}"

        # Classify Geography
        for geo_id, conf in classify_text_geo(full_text, fname):
            doc_geo_batch.append((sha, geo_id, conf))

        # Classify Organizations
        for org_id, conf in classify_text_orgs(full_text, fname):
            doc_org_batch.append((sha, org_id, conf))

    # Upsert document_geo_links
    if doc_geo_batch:
        cur.executemany("""
            INSERT INTO document_geo_links (sha256_hash, geo_id, confidence)
            VALUES (?, ?, ?)
            ON CONFLICT(sha256_hash, geo_id) DO UPDATE SET
                confidence = max(document_geo_links.confidence, excluded.confidence);
        """, doc_geo_batch)

    # Upsert document_org_links
    if doc_org_batch:
        cur.executemany("""
            INSERT INTO document_org_links (sha256_hash, org_id, confidence)
            VALUES (?, ?, ?)
            ON CONFLICT(sha256_hash, org_id) DO UPDATE SET
                confidence = max(document_org_links.confidence, excluded.confidence);
        """, doc_org_batch)

    conn.commit()

    # --- Synchronize 3D Knowledge Universe (Nodes & Edges) ---

    # 1. Geographic Nodes
    cur.execute("""
        INSERT OR REPLACE INTO knowledge_nodes (node_id, node_type, name, properties_json)
        SELECT 'location_' || LOWER(REPLACE(geo_id, '-', '_')), 'location', name,
               json_object('geo_id', geo_id, 'entity_type', entity_type, 'postal_code', postal_code, 'bfs_nr', bfs_nr)
        FROM geo_taxonomy;
    """)

    # 2. Administrative Subdivision Edges (Municipalities -> Canton)
    cur.execute("""
        INSERT OR REPLACE INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
        SELECT 
            'location_' || LOWER(REPLACE(g_child.geo_id, '-', '_')) AS source_id,
            'location_' || LOWER(REPLACE(g_parent.geo_id, '-', '_')) AS target_id,
            'PART_OF_CANTON' AS relation_type,
            2.0 AS weight,
            json_object('hierarchy', 'Administrative Subdivision') AS properties_json
        FROM geo_taxonomy g_child
        JOIN geo_taxonomy g_parent ON g_child.parent_id = g_parent.geo_id;
    """)

    # 3. Organization Nodes
    for org in CANONICAL_ORGS_SEED:
        cur.execute("""
            INSERT OR REPLACE INTO knowledge_nodes (node_id, node_type, name, properties_json)
            VALUES (?, 'organization', ?, json_object('org_id', ?, 'hq', ?, 'jurisdiction', ?));
        """, (f"organization_{org['org_id']}", org["canonical_name"], org["org_id"], org["hq_geo_id"], org["jurisdiction_geo_id"]))

        # Link Org -> HQ Location
        cur.execute("""
            INSERT OR REPLACE INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
            VALUES (?, ?, 'HEADQUARTERED_IN', 2.0, json_object('context', 'Headquarters'));
        """, (f"organization_{org['org_id']}", f"location_{org['hq_geo_id'].lower().replace('-', '_')}"))

        # Link Org -> Canton Jurisdiction
        cur.execute("""
            INSERT OR REPLACE INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
            VALUES (?, ?, 'LOCATED_IN', 1.8, json_object('context', 'Jurisdiction'));
        """, (f"organization_{org['org_id']}", f"location_{org['jurisdiction_geo_id'].lower().replace('-', '_')}"))

    # 4. Document -> Location Edges
    cur.execute("""
        INSERT OR REPLACE INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
        SELECT 
            'doc_' || sha256_hash AS source_id,
            'location_' || LOWER(REPLACE(geo_id, '-', '_')) AS target_id,
            'LOCATED_IN' AS relation_type,
            confidence AS weight,
            json_object('geo_id', geo_id) AS properties_json
        FROM document_geo_links;
    """)

    # 5. Document -> Organization Edges (Binds 845 ZKB docs to org_zkb in 3D graph)
    cur.execute("""
        INSERT OR REPLACE INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
        SELECT 
            'doc_' || sha256_hash AS source_id,
            'organization_' || org_id AS target_id,
            'MENTIONS_ORG' AS relation_type,
            confidence AS weight,
            json_object('org_id', org_id) AS properties_json
        FROM document_org_links;
    """)

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM document_geo_links;")
    total_geo = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM document_org_links;")
    total_org = cur.fetchone()[0]

    logger.info(f"Backfill complete: {total_geo:,} geo links, {total_org:,} org links created.")
    return {
        "total_documents": len(docs),
        "geo_links_created": len(doc_geo_batch),
        "org_links_created": len(doc_org_batch),
        "total_geo_links": total_geo,
        "total_org_links": total_org,
    }