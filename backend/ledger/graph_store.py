import json
import time
from typing import List, Dict, Any, Optional
from backend.config import settings
from backend.ledger.db import transaction
from backend.ledger.repository import DocumentRepository
from backend.ai.graph_schemas import EntityNode, EntityEdge, DocumentEntityLink, DocumentKnowledgeGraph, THEME_RELATION

class PropertyGraphStore:
    """Manages storage and traversal of knowledge nodes, relationships, and document associations."""

    def __init__(self,
                 repository: Optional[DocumentRepository] = None,
                 neo4j_uri: Optional[str] = None):
        self.repo = repository or DocumentRepository()
        self.graph_type = settings.GRAPH_STORE_TYPE
        self.neo4j_uri = neo4j_uri or settings.NEO4J_URI
        self._neo4j_driver = None
        self._graph_stats_cache = None
        self._graph_stats_cache_time = 0.0

        if self.graph_type == "neo4j":
            try:
                from neo4j import GraphDatabase  # type: ignore  # Optional: pip install neo4j
                self._neo4j_driver = GraphDatabase.driver(
                    self.neo4j_uri,
                    auth=(settings.NEO4J_USER or "neo4j", settings.NEO4J_PASSWORD or "password")
                )
            except Exception:
                self._neo4j_driver = None


    def upsert_node(self, node: EntityNode) -> None:
        """Insert or update an entity node in SQLite (and Neo4j if available)."""
        with self.repo._lock:
            with transaction(self.repo.conn) as cur:
                cur.execute("""
                    INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(node_id) DO UPDATE SET
                        name = excluded.name,
                        node_type = excluded.node_type,
                        properties_json = excluded.properties_json,
                        updated_at = CURRENT_TIMESTAMP;
                """, (node.node_id, node.node_type, node.name, json.dumps(node.properties, ensure_ascii=False)))

        # Optional Neo4j Sync
        if self._neo4j_driver:
            try:
                with self._neo4j_driver.session() as session:
                    session.run(
                        "MERGE (n:Entity {id: $id}) SET n.name = $name, n.type = $type",
                        id=node.node_id, name=node.name, type=node.node_type
                    )
            except Exception:
                pass

    def upsert_edge(self, edge: EntityEdge) -> None:
        """Insert or update a relationship edge between two entity nodes."""
        with self.repo._lock:
            with transaction(self.repo.conn) as cur:
                cur.execute("""
                    INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                        weight = excluded.weight,
                        properties_json = excluded.properties_json;
                """, (edge.source_id, edge.target_id, edge.relation_type, edge.weight, json.dumps(edge.properties, ensure_ascii=False)))

        # Optional Neo4j Sync
        if self._neo4j_driver:
            try:
                with self._neo4j_driver.session() as session:
                    cypher = f"""
                    MATCH (s:Entity {{id: $source_id}}), (t:Entity {{id: $target_id}})
                    MERGE (s)-[r:{edge.relation_type}]->(t)
                    SET r.weight = $weight
                    """
                    session.run(cypher, source_id=edge.source_id, target_id=edge.target_id, weight=edge.weight)
            except Exception:
                pass

    def link_document_entity(self, link: DocumentEntityLink) -> None:
        """Associate a document with an entity node."""
        with self.repo._lock:
            with transaction(self.repo.conn) as cur:
                cur.execute("""
                    INSERT INTO document_entity_links (sha256_hash, node_id, role, confidence)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(sha256_hash, node_id, role) DO UPDATE SET
                        confidence = excluded.confidence;
                """, (link.sha256_hash, link.node_id, link.role, link.confidence))

    def save_document_graph(self, doc_graph: DocumentKnowledgeGraph) -> None:
        """Atomically persist extracted nodes, edges, and document links for a single document."""
        self.save_graphs_batch([doc_graph])

    def save_graphs_batch(self, doc_graphs: List[DocumentKnowledgeGraph]) -> None:
        """Atomically persist extracted nodes, edges, and document links for a batch of documents in a single transaction."""
        if not doc_graphs:
            return

        with self.repo._lock:
            with transaction(self.repo.conn) as cur:
                for doc_graph in doc_graphs:
                    for node in doc_graph.nodes:
                        cur.execute("""
                            INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json, updated_at)
                            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(node_id) DO UPDATE SET
                                name = excluded.name,
                                node_type = excluded.node_type,
                                properties_json = excluded.properties_json,
                                updated_at = CURRENT_TIMESTAMP;
                        """, (node.node_id, node.node_type, node.name, json.dumps(node.properties, ensure_ascii=False)))

                    for edge in doc_graph.edges:
                        cur.execute("""
                            INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                                weight = excluded.weight,
                                properties_json = excluded.properties_json;
                        """, (edge.source_id, edge.target_id, edge.relation_type, edge.weight, json.dumps(edge.properties, ensure_ascii=False)))

                    # A document belongs to exactly one taxonomy theme: drop stale CATEGORIZED_AS links
                    # (e.g. after taxonomy evolution reclassified it) before writing the current one.
                    theme_ids = [l.node_id for l in doc_graph.links if l.role == THEME_RELATION]
                    if theme_ids:
                        placeholders = ",".join("?" for _ in theme_ids)
                        cur.execute(f"""
                            DELETE FROM document_entity_links
                            WHERE sha256_hash = ? AND role = ? AND node_id NOT IN ({placeholders});
                        """, (doc_graph.sha256_hash, THEME_RELATION, *theme_ids))

                    for link in doc_graph.links:
                        cur.execute("""
                            INSERT INTO document_entity_links (sha256_hash, node_id, role, confidence)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(sha256_hash, node_id, role) DO UPDATE SET
                                confidence = excluded.confidence;
                        """, (link.sha256_hash, link.node_id, link.role, link.confidence))

    def backfill_theme_links(self, extractor: Optional[Any] = None, batch_size: int = 500) -> Dict[str, Any]:
        """Attach taxonomy theme hubs to already-ingested documents without re-chunking/re-embedding.

        Only theme nodes and document->theme links are written; category->theme edges are
        created on the next normal sidecar pass for each document.
        """
        from backend.ai.graph_extractor import (  # lazy: keep graph_store import-light
            KnowledgeGraphExtractor, ThemeResolver, make_db_taxonomy_loader,
        )
        extractor = extractor or KnowledgeGraphExtractor(
            theme_resolver=ThemeResolver(loader=make_db_taxonomy_loader(self.repo.conn, self.repo._lock))
        )

        with self.repo._lock:
            cur = self.repo.conn.cursor()
            cur.execute("SELECT sha256_hash, doc_type FROM document_ledger;")
            rows = [(r[0], r[1]) for r in cur.fetchall()]

        graphs: List[DocumentKnowledgeGraph] = []
        themes: Dict[str, int] = {}
        for sha, doc_type in rows:
            g = extractor.attach_theme(DocumentKnowledgeGraph(sha256_hash=sha), doc_type or "")
            if g.links:
                graphs.append(g)
                themes[g.links[0].node_id] = themes.get(g.links[0].node_id, 0) + 1

        for i in range(0, len(graphs), batch_size):
            self.save_graphs_batch(graphs[i:i + batch_size])

        return {
            "documents_examined": len(rows),
            "documents_themed": len(graphs),
            "documents_skipped": len(rows) - len(graphs),
            "theme_distribution": dict(sorted(themes.items(), key=lambda kv: -kv[1])),
        }

    def backfill_financial_pillars(self, batch_size: int = 500) -> Dict[str, Any]:
        """Detect and backfill financial pillar archetypes across the document ledger.
        
        Scans document_fts full-text index for contractual payment mechanisms:
        rent, salary, mortgage, fee, fine, interest, insurance_premium.
        """
        PILLAR_DEFINITIONS = {
            "financial_pillar_rent": ("Rent", "Universal rental and lease payment commitments", "Miete OR Mietzins OR Loyer OR Rent OR Bail"),
            "financial_pillar_salary": ("Salary", "Employment remuneration, payroll, and compensation", "Lohn OR Gehalt OR Salär OR Salaire OR Salary OR Remuneration OR Bonus"),
            "financial_pillar_mortgage": ("Mortgage", "Real estate hypothecary loans and collateralized credit", "Hypothek OR Hypothekardarlehen OR Mortgage"),
            "financial_pillar_fee": ("Fee", "Administrative, brokerage, management, and legal fee structures", "Gebühr OR Honorar OR Frais OR Courtage OR Commission OR Fee"),
            "financial_pillar_fine": ("Fine", "Judicial, penal, regulatory, and contractual fines or penalties", "Busse OR Konventionalstrafe OR Pénalité OR Fine OR Penalty"),
            "financial_pillar_interest": ("Interest", "Credit interest, default interest, and capital yield rates", "Zins OR Verzugszins OR Intérêt OR Interest"),
            "financial_pillar_insurance_premium": ("Insurance Premium", "Social security, health, and commercial insurance coverage", "Prämie OR Prime OR AHV OR ALV OR Pensionskasse"),
        }

        with self.repo._lock:
            cur = self.repo.conn.cursor()

            # 1. Ensure financial_pillar archetype knowledge_nodes exist
            for node_id, (name, desc, _) in PILLAR_DEFINITIONS.items():
                cur.execute("""
                    INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json, updated_at)
                    VALUES (?, 'financial_pillar', ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(node_id) DO UPDATE SET
                        name = excluded.name,
                        properties_json = excluded.properties_json,
                        updated_at = CURRENT_TIMESTAMP;
                """, (node_id, name, json.dumps({"description": desc, "canonical_name": name})))

            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_fts';")
            has_fts = bool(cur.fetchone())

            total_linked = 0
            pillar_counts: Dict[str, int] = {}

            for node_id, (name, _, fts_query) in PILLAR_DEFINITIONS.items():
                matched_shas = []
                if has_fts:
                    try:
                        cur.execute("SELECT DISTINCT sha256_hash FROM document_fts WHERE document_fts MATCH ?;", (fts_query,))
                        matched_shas = [r[0] for r in cur.fetchall()]
                    except Exception:
                        matched_shas = []

                if matched_shas:
                    for i in range(0, len(matched_shas), batch_size):
                        batch = [(sha, node_id) for sha in matched_shas[i:i + batch_size]]
                        cur.executemany("""
                            INSERT INTO document_entity_links (sha256_hash, node_id, role, confidence)
                            VALUES (?, ?, 'financial_term', 1.0)
                            ON CONFLICT(sha256_hash, node_id, role) DO UPDATE SET confidence = 1.0;
                        """, batch)
                    pillar_counts[node_id] = len(matched_shas)
                    total_linked += len(matched_shas)

            self.repo.conn.commit()

        return {
            "pillars_populated": len(PILLAR_DEFINITIONS),
            "total_links_created": total_linked,
            "pillar_distribution": pillar_counts,
        }

    def backfill_geo_entity_links(self) -> Dict[str, Any]:
        """Synchronize geographic and edge document links into document_entity_links.
        
        Ensures canonical geographic nodes (e.g. location_ch_zg_6312, location_steinhausen,
        location_ch_zg) accurately reflect their document links in document_entity_links.
        """
        with self.repo._lock:
            cur = self.repo.conn.cursor()
            
            # 1. Mirror doc_% edges from knowledge_edges into document_entity_links
            cur.execute("""
                INSERT OR IGNORE INTO document_entity_links (sha256_hash, node_id, role, confidence)
                SELECT SUBSTR(e.source_id, 5), e.target_id, e.relation_type, COALESCE(e.weight, 1.0)
                FROM knowledge_edges e
                WHERE e.source_id LIKE 'doc_%'
                  AND EXISTS (SELECT 1 FROM knowledge_nodes n WHERE n.node_id = e.target_id)
                  AND EXISTS (SELECT 1 FROM document_ledger dl WHERE dl.sha256_hash = SUBSTR(e.source_id, 5));
            """)
            mirrored_from_edges = cur.rowcount if cur.rowcount >= 0 else 0

            # 2. Mirror document_geo_links into document_entity_links for matching location nodes
            cur.execute("""
                INSERT OR IGNORE INTO document_entity_links (sha256_hash, node_id, role, confidence)
                SELECT dgl.sha256_hash, n.node_id, 'LOCATED_IN', COALESCE(dgl.confidence, 1.0)
                FROM document_geo_links dgl
                JOIN knowledge_nodes n ON (
                    n.node_id = 'location_' || LOWER(REPLACE(REPLACE(dgl.geo_id, '-', '_'), ' ', '_'))
                    OR (n.properties_json LIKE '%"geo_id":"' || dgl.geo_id || '"%')
                )
                WHERE EXISTS (SELECT 1 FROM document_ledger dl WHERE dl.sha256_hash = dgl.sha256_hash);
            """)
            mirrored_from_geolinks = cur.rowcount if cur.rowcount >= 0 else 0

            self.repo.conn.commit()
            return {
                "mirrored_from_edges": mirrored_from_edges,
                "mirrored_from_geolinks": mirrored_from_geolinks,
                "total_mirrored": mirrored_from_edges + mirrored_from_geolinks
            }

    def get_document_entities(self, sha256_hash: str) -> List[Dict[str, Any]]:
        """Retrieve all entities associated with a specific document."""
        with self.repo._lock:
            cur = self.repo.conn.cursor()
            cur.execute("""
                SELECT n.node_id, n.node_type, n.name, n.properties_json, l.role, l.confidence
                FROM document_entity_links l
                JOIN knowledge_nodes n ON l.node_id = n.node_id
                WHERE l.sha256_hash = ?
                ORDER BY n.node_type ASC, n.name ASC;
            """, (sha256_hash,))
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if d.get("properties_json"):
                    try:
                        d["properties"] = json.loads(d["properties_json"])
                    except Exception:
                        d["properties"] = {}
                results.append(d)
            return results

    def expand_entity_neighborhood(self, node_id: str, max_hops: int = 1) -> Dict[str, Any]:
        """Expand 1-hop or 2-hop connected graph neighborhood for a given entity or document node."""
        if not node_id:
            return {
                "node_id": "",
                "outgoing_relations": [],
                "incoming_relations": [],
                "associated_documents": [],
            }

        with self.repo._lock:
            cur = self.repo.conn.cursor()

            # 1. Handle Document Nodes (e.g. doc_<sha> or direct 64-char sha256 hash)
            if node_id.startswith("doc_") or (len(node_id) == 64 and all(c in "0123456789abcdefABCDEF" for c in node_id)):
                clean_sha = node_id[4:] if node_id.startswith("doc_") else node_id
                
                # Fetch document info
                cur.execute("""
                    SELECT sha256_hash, canonical_filename, doc_type, doc_date, lifecycle_status, maturity_score
                    FROM document_ledger
                    WHERE sha256_hash LIKE ? OR sha256_hash = ?
                    LIMIT 1;
                """, (f"{clean_sha}%", clean_sha))
                doc_row = cur.fetchone()
                
                full_sha = doc_row["sha256_hash"] if doc_row else clean_sha
                
                # Fetch linked entities for this document
                cur.execute("""
                    SELECT n.node_id, n.node_type, n.name, n.properties_json,
                           COALESCE(l.role, 'MENTIONS') AS relation_type,
                           COALESCE(l.confidence, 1.0) AS weight
                    FROM document_entity_links l
                    JOIN knowledge_nodes n ON l.node_id = n.node_id
                    WHERE l.sha256_hash LIKE ? OR l.sha256_hash = ?
                    ORDER BY weight DESC
                    LIMIT 100;
                """, (f"{clean_sha}%", full_sha))
                linked_entities = [dict(r) for r in cur.fetchall()]

                associated_docs = []
                if doc_row:
                    associated_docs.append(dict(doc_row))

                return {
                    "node_id": node_id,
                    "node_type": "document",
                    "name": doc_row["canonical_filename"] if doc_row else node_id,
                    "outgoing_relations": linked_entities,
                    "incoming_relations": [],
                    "associated_documents": associated_docs,
                }

            # 2. Handle Knowledge Graph Entity Nodes
            # Resolve actual canonical node_id if passed with slightly different casing or alias
            cur.execute("""
                SELECT node_id, node_type, name FROM knowledge_nodes
                WHERE node_id = ? OR LOWER(node_id) = LOWER(?) OR LOWER(name) = LOWER(?)
                LIMIT 1;
            """, (node_id, node_id, node_id))
            node_match = cur.fetchone()
            canonical_id = node_match["node_id"] if node_match else node_id

            # Outgoing edges
            cur.execute("""
                SELECT e.relation_type, e.weight, e.properties_json, n.node_id, n.node_type, n.name
                FROM knowledge_edges e
                JOIN knowledge_nodes n ON e.target_id = n.node_id
                WHERE e.source_id = ?;
            """, (canonical_id,))
            outgoing = [dict(r) for r in cur.fetchall()]

            # Incoming edges
            cur.execute("""
                SELECT e.relation_type, e.weight, e.properties_json, n.node_id, n.node_type, n.name
                FROM knowledge_edges e
                JOIN knowledge_nodes n ON e.source_id = n.node_id
                WHERE e.target_id = ?;
            """, (canonical_id,))
            incoming = [dict(r) for r in cur.fetchall()]

            # Associated documents
            cur.execute("""
                SELECT DISTINCT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.doc_date, dl.lifecycle_status, l.role
                FROM document_entity_links l
                JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
                WHERE l.node_id = ?
                ORDER BY dl.doc_date DESC
                LIMIT 50;
            """, (canonical_id,))
            docs = [dict(r) for r in cur.fetchall()]

            # Co-occurrence Fallback: if explicit edges are empty (e.g. locations/statutes), bridge via shared documents
            if not outgoing and not incoming and docs:
                doc_hashes = [d["sha256_hash"] for d in docs[:15]]
                placeholders = ",".join("?" for _ in doc_hashes)
                cur.execute(f"""
                    SELECT DISTINCT n.node_id, n.node_type, n.name, 
                           CASE WHEN n.node_type = 'location' THEN 'LOCATED_IN'
                                WHEN n.node_type = 'statute' THEN 'SUBJECT_TO'
                                WHEN n.node_type = 'currency' THEN 'DENOMINATED_IN'
                                WHEN n.node_type = 'financial_pillar' THEN 'INVOLVES_PAYMENT'
                                ELSE 'CO_OCCURS_IN_DOC' END AS relation_type,
                           1.0 AS weight
                    FROM document_entity_links l
                    JOIN knowledge_nodes n ON l.node_id = n.node_id
                    WHERE l.sha256_hash IN ({placeholders}) AND n.node_id != ?
                    LIMIT 30;
                """, doc_hashes + [canonical_id])
                outgoing = [dict(r) for r in cur.fetchall()]

            # If 2 hops requested, expand 1 level further for outgoing nodes
            if max_hops >= 2 and outgoing:
                neighbor_ids = [r["node_id"] for r in outgoing[:10]]
                placeholders = ",".join("?" for _ in neighbor_ids)
                cur.execute(f"""
                    SELECT e.relation_type, e.weight, n.node_id, n.node_type, n.name, e.source_id AS parent_node_id
                    FROM knowledge_edges e
                    JOIN knowledge_nodes n ON e.target_id = n.node_id
                    WHERE e.source_id IN ({placeholders}) AND n.node_id != ?
                    LIMIT 40;
                """, neighbor_ids + [canonical_id])
                hop2_rows = cur.fetchall()
                for h in hop2_rows:
                    h_dict = dict(h)
                    h_dict["hop"] = 2
                    outgoing.append(h_dict)

            return {
                "node_id": canonical_id,
                "node_type": node_match["node_type"] if node_match else "entity",
                "name": node_match["name"] if node_match else canonical_id,
                "outgoing_relations": outgoing,
                "incoming_relations": incoming,
                "associated_documents": docs,
            }

    def get_all_entities_grouped(self, limit_per_type: int = 500) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch all entities grouped by node_type, annotated with their linked document count."""
        with self.repo._lock:
            cur = self.repo.conn.cursor()
            cur.execute("""
                SELECT n.node_id, n.node_type, n.name, n.properties_json,
                       COUNT(l.sha256_hash) AS doc_count
                FROM knowledge_nodes n
                LEFT JOIN document_entity_links l ON n.node_id = l.node_id
                GROUP BY n.node_id, n.node_type, n.name
                ORDER BY doc_count DESC, n.name ASC
            """)
            rows = cur.fetchall()
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for r in rows:
                ntype = r["node_type"] or "other"
                if ntype not in grouped:
                    grouped[ntype] = []
                if len(grouped[ntype]) < limit_per_type:
                    grouped[ntype].append({
                        "node_id": r["node_id"],
                        "name": r["name"],
                        "doc_count": r["doc_count"]
                    })
            return grouped

    def get_graph_stats(self, max_age: float = 4.0) -> Dict[str, Any]:
        """Aggregate statistics on knowledge graph nodes, edges, and document links with lightweight TTL caching."""
        now = time.time()
        if self._graph_stats_cache is not None and (now - self._graph_stats_cache_time) < max_age:
            return self._graph_stats_cache

        with self.repo._lock:
            cur = self.repo.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM knowledge_nodes")
            total_nodes = cur.fetchone()[0]

            cur.execute("SELECT node_type, COUNT(*) FROM knowledge_nodes GROUP BY node_type ORDER BY COUNT(*) DESC")
            node_types = dict(cur.fetchall())

            cur.execute("SELECT COUNT(*) FROM knowledge_edges")
            total_edges = cur.fetchone()[0]

            cur.execute("SELECT relation_type, COUNT(*) FROM knowledge_edges GROUP BY relation_type")
            edge_types = dict(cur.fetchall())

            cur.execute("SELECT COUNT(*) FROM document_entity_links")
            total_links = cur.fetchone()[0]

            stats = {
                "total_nodes": total_nodes,
                "node_types": node_types,
                "total_edges": total_edges,
                "edge_types": edge_types,
                "total_document_links": total_links,
            }
            self._graph_stats_cache = stats
            self._graph_stats_cache_time = now
            return stats

    def get_3d_knowledge_universe(self,
                                   limit: int = 1000,
                                   filters: Optional[Dict[str, Any]] = None,
                                   layout: str = "spatial") -> Dict[str, Any]:
        """Generate 3D Euclidean coordinates along axes of importance with stratified archetype sampling,
        dynamic query filtering, or thematic mindmap solar-planetary topology."""
        import hashlib
        import math
        import json

        cluster_definitions = [
            {
                "id": 0,
                "name": "Corporate Alliances & Organizations",
                "archetype": "Organizations",
                "color": "#38bdf8",
                "icon": "🏢",
                "types": ["organization"],
                "representation_desc": "Top corporate hubs & counterparties",
            },
            {
                "id": 1,
                "name": "Contracts & Operational Projects",
                "archetype": "Contract Types",
                "color": "#10b981",
                "icon": "📄",
                "types": ["contract_type", "document_category", "document", "project_code"],
                "representation_desc": "Full coverage of all document types & categories",
            },
            {
                "id": 2,
                "name": "Key Signatories & Management",
                "archetype": "Persons",
                "color": "#c084fc",
                "icon": "👤",
                "types": ["person"],
                "representation_desc": "Top signatories & management",
            },
            {
                "id": 3,
                "name": "Jurisdictions & Geographic Hubs",
                "archetype": "Locations",
                "color": "#f59e0b",
                "icon": "📍",
                "types": ["location"],
                "representation_desc": "Full coverage (Ottenbach, Steinhausen, Zug, CH, etc.)",
            },
            {
                "id": 4,
                "name": "Statutory & Regulatory Codes",
                "archetype": "Statutes",
                "color": "#f43f5e",
                "icon": "⚖️",
                "types": ["statute", "milestone_date"],
                "representation_desc": "Swiss legal codes & governing articles",
            },
            {
                "id": 5,
                "name": "Financial Pillars & Currencies",
                "archetype": "Financial",
                "color": "#eab308",
                "icon": "💰",
                "types": ["currency", "financial_pillar", "monetary_value"],
                "representation_desc": "Universal monetary hubs & contractual flows",
            },
            {
                "id": 6,
                "name": "Life-Style Domains & Thematic Hubs",
                "archetype": "Themes",
                "color": "#ec4899",
                "icon": "🪐",
                "types": ["theme"],
                "representation_desc": "Taxonomy life domains & central gravitational hubs",
            },
        ]

        THEME_PALETTE = {
            "theme_legal_contract": {"color": "#f59e0b", "icon": "⚖️"},
            "theme_financial_banking": {"color": "#10b981", "icon": "🏦"},
            "theme_financial_invoice": {"color": "#34d399", "icon": "🧾"},
            "theme_career_research": {"color": "#06b6d4", "icon": "💼"},
            "theme_court_order": {"color": "#f43f5e", "icon": "🏛️"},
            "theme_tax_assessment": {"color": "#8b5cf6", "icon": "📊"},
            "theme_corporate_governance": {"color": "#6366f1", "icon": "🏢"},
            "theme_technical_architecture": {"color": "#14b8a6", "icon": "📐"},
            "theme_formal_correspondence": {"color": "#38bdf8", "icon": "✉️"},
            "theme_identity_credentials": {"color": "#fb923c", "icon": "🪪"},
            "theme_unclassified": {"color": "#94a3b8", "icon": "📁"},
        }

        active_filters = {k: v for k, v in (filters or {}).items() if v is not None and str(v).strip() != ""}
        layout_mode = str(active_filters.pop("layout", layout or "spatial")).lower().strip()
        if layout_mode not in ["thematic", "spatial"]:
            layout_mode = "spatial"

        focus_node_id = None
        extra_document_node = None
        extra_edges = []

        with self.repo._lock:
            cur = self.repo.conn.cursor()

            # Query entity population count per node_type to calculate representativity
            cur.execute("SELECT node_type, COUNT(*) as cnt FROM knowledge_nodes GROUP BY node_type;")
            type_counts = {r["node_type"]: r["cnt"] for r in cur.fetchall()}

            quota_per_type = max(100, limit // len(cluster_definitions))

            if active_filters:
                loc_filter = active_filters.get("location")
                org_filter = active_filters.get("org") or active_filters.get("organization")
                person_filter = active_filters.get("person") or active_filters.get("author")
                ntype_filter = active_filters.get("node_type") or active_filters.get("type")
                cluster_filter = active_filters.get("cluster")
                doc_sha_filter = active_filters.get("doc_sha") or active_filters.get("sha256") or active_filters.get("document")
                theme_filter = active_filters.get("theme")
                q_filter = active_filters.get("q") or active_filters.get("query") or active_filters.get("search")

                matching_node_ids = set()

                # 1. Document SHA Filter & Lineage Navigation
                if doc_sha_filter:
                    clean_sha = str(doc_sha_filter).strip()
                    cur.execute("SELECT node_id FROM document_entity_links WHERE sha256_hash = ?;", (clean_sha,))
                    doc_linked_nodes = {r["node_id"] for r in cur.fetchall()}
                    matching_node_ids.update(doc_linked_nodes)

                    # Retrieve document metadata from ledger
                    cur.execute("SELECT sha256_hash, canonical_filename, doc_type, doc_date, maturity_score, lifecycle_status FROM document_ledger WHERE sha256_hash = ?;", (clean_sha,))
                    doc_meta = cur.fetchone()
                    if doc_meta:
                        doc_node_id = f"doc_{clean_sha[:16]}"
                        focus_node_id = doc_node_id
                        extra_document_node = {
                            "node_id": doc_node_id,
                            "node_type": "document",
                            "name": doc_meta["canonical_filename"],
                            "properties_json": json.dumps({
                                "sha256": clean_sha,
                                "doc_type": doc_meta["doc_type"],
                                "status": doc_meta["lifecycle_status"]
                            }),
                            "doc_count": 1,
                            "degree": len(doc_linked_nodes),
                            "latest_doc_date": doc_meta["doc_date"] or "2024-01-01",
                            "raw_sha": clean_sha,
                        }
                    elif doc_linked_nodes:
                        focus_node_id = next(iter(doc_linked_nodes))

                # 2. Location & Org Filters with Inter-SubGraph Discovery
                loc_node_ids = set()
                org_node_ids = set()
                person_node_ids = set()

                if loc_filter:
                    level_filter = active_filters.get("level")
                    from backend.ledger.geo_taxonomy import get_sub_regions
                    try:
                        sub_regions = get_sub_regions(self.repo.conn, loc_filter)
                    except Exception:
                        sub_regions = []

                    if sub_regions:
                        target_sub_regions = sub_regions
                        if level_filter == "municipality":
                            target_sub_regions = [sr for sr in sub_regions if sr["entity_type"] == "municipality"]
                        elif level_filter == "canton":
                            target_sub_regions = sub_regions

                        geo_ids = [sr["geo_id"] for sr in target_sub_regions]
                        p_geos = ",".join("?" for _ in geo_ids)

                        for sr in target_sub_regions:
                            loc_node_ids.add(f"location_{sr['geo_id'].lower().replace('-', '_')}")
                            loc_node_ids.add(f"location_{sr['name'].lower().replace(' ', '_')}")

                        cur.execute(f"""
                            SELECT DISTINCT del.node_id
                            FROM document_geo_links dgl
                            JOIN document_entity_links del ON dgl.sha256_hash = del.sha256_hash
                            WHERE dgl.geo_id IN ({p_geos})
                            LIMIT ?;
                        """, geo_ids + [min(400, limit)])
                        for r in cur.fetchall():
                            matching_node_ids.add(r["node_id"])

                        canton_root = next((sr for sr in target_sub_regions if sr["entity_type"] == "canton"), None)
                        if canton_root:
                            focus_node_id = f"location_{canton_root['geo_id'].lower().replace('-', '_')}"
                        else:
                            focus_node_id = f"location_{target_sub_regions[0]['geo_id'].lower().replace('-', '_')}"

                    cur.execute("SELECT node_id FROM knowledge_nodes WHERE node_type = 'location' AND (LOWER(name) LIKE ? OR LOWER(node_id) LIKE ?);", (f"%{loc_filter.lower()}%", f"%{loc_filter.lower()}%"))
                    for r in cur.fetchall():
                        loc_node_ids.add(r["node_id"])

                    matching_node_ids.update(loc_node_ids)
                    if loc_node_ids and not focus_node_id:
                        focus_node_id = next(iter(loc_node_ids))

                if org_filter:
                    clean_org = org_filter.lower().strip()
                    extra_clauses = ["LOWER(name) LIKE ?", "LOWER(node_id) LIKE ?", "LOWER(properties_json) LIKE ?"]
                    params = [f"%{clean_org}%", f"%{clean_org}%", f"%{clean_org}%"]
                    if clean_org in ["zkb", "zkb zug", "zgkb", "zugerkb"]:
                        extra_clauses.append("node_id = 'organization_zuger_kantonalbank'")
                    clause_sql = " OR ".join(extra_clauses)
                    cur.execute(f"SELECT node_id FROM knowledge_nodes WHERE node_type = 'organization' AND ({clause_sql});", params)
                    org_node_ids = {r["node_id"] for r in cur.fetchall()}
                    matching_node_ids.update(org_node_ids)
                    if org_node_ids and not focus_node_id:
                        if "organization_zuger_kantonalbank" in org_node_ids:
                            focus_node_id = "organization_zuger_kantonalbank"
                        else:
                            focus_node_id = next(iter(org_node_ids))

                if person_filter:
                    cur.execute("SELECT node_id FROM knowledge_nodes WHERE node_type = 'person' AND (LOWER(name) LIKE ? OR LOWER(node_id) LIKE ?);", (f"%{person_filter.lower()}%", f"%{person_filter.lower()}%"))
                    person_node_ids = {r["node_id"] for r in cur.fetchall()}
                    matching_node_ids.update(person_node_ids)
                    if person_node_ids and not focus_node_id:
                        focus_node_id = next(iter(person_node_ids))

                # Theme filter
                if theme_filter:
                    clean_th = theme_filter.lower().strip()
                    cur.execute("SELECT node_id FROM knowledge_nodes WHERE node_type = 'theme' AND (LOWER(node_id) LIKE ? OR LOWER(name) LIKE ?);", (f"%{clean_th}%", f"%{clean_th}%"))
                    th_matched = {r["node_id"] for r in cur.fetchall()}
                    matching_node_ids.update(th_matched)
                    if th_matched and not focus_node_id:
                        focus_node_id = next(iter(th_matched))

                # If multiple focal entities provided (e.g. loc + org), find bridging documents
                if loc_node_ids and org_node_ids:
                    p_loc = ",".join("?" for _ in loc_node_ids)
                    p_org = ",".join("?" for _ in org_node_ids)
                    cur.execute(f"""
                        SELECT DISTINCT l1.sha256_hash
                        FROM document_entity_links l1
                        JOIN document_entity_links l2 ON l1.sha256_hash = l2.sha256_hash
                        WHERE l1.node_id IN ({p_loc}) AND l2.node_id IN ({p_org})
                        LIMIT 50;
                    """, list(loc_node_ids) + list(org_node_ids))
                    shared_shas = [r["sha256_hash"] for r in cur.fetchall()]
                    if shared_shas:
                        p_shas = ",".join("?" for _ in shared_shas)
                        cur.execute(f"SELECT DISTINCT node_id FROM document_entity_links WHERE sha256_hash IN ({p_shas});", shared_shas)
                        shared_entities = {r["node_id"] for r in cur.fetchall()}
                        matching_node_ids.update(shared_entities)
                else:
                    focal_ids = loc_node_ids or org_node_ids or person_node_ids
                    if focal_ids:
                        p_focal = ",".join("?" for _ in focal_ids)
                        focal_list = list(focal_ids)
                        cur.execute(f"""
                            SELECT DISTINCT CASE WHEN source_id IN ({p_focal}) THEN target_id ELSE source_id END AS neighbor_id
                            FROM knowledge_edges
                            WHERE source_id IN ({p_focal}) OR target_id IN ({p_focal})
                            LIMIT ?;
                        """, focal_list + focal_list + focal_list + [min(250, limit)])
                        matching_node_ids.update({r["neighbor_id"] for r in cur.fetchall()})

                        cur.execute(f"""
                            SELECT l2.node_id, COUNT(DISTINCT l1.sha256_hash) AS shared_docs
                            FROM document_entity_links l1
                            JOIN document_entity_links l2 ON l1.sha256_hash = l2.sha256_hash
                            WHERE l1.node_id IN ({p_focal}) AND l2.node_id NOT IN ({p_focal})
                            GROUP BY l2.node_id
                            ORDER BY shared_docs DESC
                            LIMIT ?;
                        """, focal_list + focal_list + [min(300, limit)])
                        matching_node_ids.update({r["node_id"] for r in cur.fetchall()})

                # 3. Node Type Filter
                if ntype_filter:
                    cur.execute("SELECT node_id FROM knowledge_nodes WHERE LOWER(node_type) = ? LIMIT ?;", (ntype_filter.lower(), limit))
                    matching_node_ids.update({r["node_id"] for r in cur.fetchall()})

                # 4. Cluster Filter
                if cluster_filter is not None:
                    try:
                        cid = int(cluster_filter)
                        if 0 <= cid < len(cluster_definitions):
                            cluster_types = cluster_definitions[cid]["types"]
                            p_types = ",".join("?" for _ in cluster_types)
                            cur.execute(f"SELECT node_id FROM knowledge_nodes WHERE node_type IN ({p_types}) LIMIT ?;", cluster_types + [limit])
                            matching_node_ids.update({r["node_id"] for r in cur.fetchall()})
                    except (ValueError, TypeError):
                        pass

                # 5. General Search Query
                if q_filter:
                    cur.execute("SELECT node_id FROM knowledge_nodes WHERE LOWER(name) LIKE ? OR LOWER(node_id) LIKE ? LIMIT ?;", (f"%{q_filter.lower()}%", f"%{q_filter.lower()}%", limit))
                    q_matched = {r["node_id"] for r in cur.fetchall()}
                    matching_node_ids.update(q_matched)
                    if q_matched and not focus_node_id:
                        focus_node_id = next(iter(q_matched))

                raw_nodes = []
                if matching_node_ids:
                    p_matched = ",".join("?" for _ in matching_node_ids)
                    cur.execute(f"""
                        SELECT n.node_id, n.node_type, n.name, n.properties_json,
                               COUNT(DISTINCT l.sha256_hash) AS doc_count,
                               (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree,
                               MAX(dl.doc_date) AS latest_doc_date,
                               NULL AS raw_sha
                        FROM knowledge_nodes n
                        LEFT JOIN document_entity_links l ON n.node_id = l.node_id
                        LEFT JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
                        WHERE n.node_id IN ({p_matched})
                        GROUP BY n.node_id, n.node_type, n.name
                        ORDER BY (degree * 2 + doc_count * 3) DESC
                        LIMIT ?;
                    """, list(matching_node_ids) + [limit])
                    raw_nodes = [dict(r) for r in cur.fetchall()]

                if extra_document_node:
                    raw_nodes.insert(0, extra_document_node)

            elif layout_mode == "thematic":
                # Thematic Mindmap Mode:
                # 1. Pull all theme hubs (Suns)
                # 2. Pull categorized documents linked via CATEGORIZED_AS (Planets)
                # 3. Pull key entities linked to these categorized documents to show cross-pollination
                doc_limit = max(100, int(limit * 0.65))
                ent_limit = max(50, int(limit * 0.30))
                cur.execute("""
                    WITH ThematicHubs AS (
                        SELECT n.node_id, n.node_type, n.name, n.properties_json,
                               COUNT(DISTINCT l.sha256_hash) AS doc_count,
                               (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree,
                               MAX(dl.doc_date) AS latest_doc_date,
                               NULL AS raw_sha,
                               1 AS priority
                        FROM knowledge_nodes n
                        LEFT JOIN document_entity_links l ON n.node_id = l.node_id
                        LEFT JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
                        WHERE n.node_type = 'theme'
                        GROUP BY n.node_id, n.node_type, n.name
                    ),
                    ThematicDocs AS (
                        SELECT 'doc_' || SUBSTR(dl.sha256_hash, 1, 16) AS node_id,
                               'document' AS node_type,
                               dl.canonical_filename AS name,
                               json_object(
                                   'sha256', dl.sha256_hash,
                                   'doc_type', dl.doc_type,
                                   'status', dl.lifecycle_status,
                                   'theme_id', l.node_id
                               ) AS properties_json,
                               1 AS doc_count,
                               (SELECT COUNT(*) FROM document_entity_links del WHERE del.sha256_hash = dl.sha256_hash) AS degree,
                               dl.doc_date AS latest_doc_date,
                               dl.sha256_hash AS raw_sha,
                               2 AS priority
                        FROM document_ledger dl
                        JOIN document_entity_links l ON dl.sha256_hash = l.sha256_hash AND l.role = 'CATEGORIZED_AS'
                        WHERE l.node_id LIKE 'theme_%'
                        ORDER BY dl.doc_date DESC, degree DESC
                        LIMIT ?
                    ),
                    ConnectedEntities AS (
                        SELECT n.node_id, n.node_type, n.name, n.properties_json,
                               COUNT(DISTINCT l.sha256_hash) AS doc_count,
                               (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree,
                               MAX(dl.doc_date) AS latest_doc_date,
                               NULL AS raw_sha,
                               3 AS priority
                        FROM knowledge_nodes n
                        JOIN document_entity_links l ON n.node_id = l.node_id
                        JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
                        WHERE n.node_type != 'theme'
                          AND l.sha256_hash IN (SELECT raw_sha FROM ThematicDocs)
                        GROUP BY n.node_id, n.node_type, n.name
                        ORDER BY (degree * 2 + doc_count * 3) DESC
                        LIMIT ?
                    )
                    SELECT node_id, node_type, name, properties_json, doc_count, degree, latest_doc_date, raw_sha
                    FROM (
                        SELECT * FROM ThematicHubs
                        UNION ALL
                        SELECT * FROM ThematicDocs
                        UNION ALL
                        SELECT * FROM ConnectedEntities
                    )
                    ORDER BY priority ASC, (degree * 2 + doc_count * 3) DESC
                    LIMIT ?;
                """, (doc_limit, ent_limit, limit))
                raw_nodes = [dict(r) for r in cur.fetchall()]

            else:
                # Standard Stratified Cluster Sampling
                cur.execute("""
                    WITH EntityBase AS (
                        SELECT n.node_id, n.node_type, n.name, n.properties_json,
                               COUNT(DISTINCT l.sha256_hash) AS doc_count,
                               (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree,
                               MAX(dl.doc_date) AS latest_doc_date,
                               NULL AS raw_sha
                        FROM knowledge_nodes n
                        LEFT JOIN document_entity_links l ON n.node_id = l.node_id
                        LEFT JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
                        GROUP BY n.node_id, n.node_type, n.name
                    ),
                    RankedEntities AS (
                        SELECT *,
                               ROW_NUMBER() OVER (
                                    PARTITION BY node_type
                                    ORDER BY (degree * 2 + doc_count * 5) DESC
                               ) as type_rank
                        FROM EntityBase
                    )
                    SELECT node_id, node_type, name, properties_json, doc_count, degree, latest_doc_date, raw_sha
                    FROM RankedEntities
                    WHERE type_rank <= ?
                    ORDER BY (degree * 2 + doc_count * 3 + (CAST(SUBSTR(COALESCE(latest_doc_date, '2005-01-01'), 1, 4) AS INT) - 2005) * 10) DESC
                    LIMIT ?;
                """, (quota_per_type, limit))
                raw_nodes = [dict(r) for r in cur.fetchall()]

            if not raw_nodes:
                for c in cluster_definitions:
                    c["total_in_db"] = sum(type_counts.get(t, 0) for t in c.get("types", []))
                    c["rendered_count"] = 0
                    c["quota"] = quota_per_type
                    c["is_capped"] = False
                    c["representation_pct"] = 0.0
                return {
                    "nodes": [],
                    "edges": [],
                    "clusters": cluster_definitions,
                    "axes": {
                        "x": "Thematic Gravitational Plane (Cosmic X)" if layout_mode == "thematic" else "Domain Specificity & Category Dispersion (PCA-1)",
                        "y": "Cross-Pollination & Inter-Domain Tension (Cosmic Y)" if layout_mode == "thematic" else "Temporal Recency & Lifecycle Maturity (PCA-2)",
                        "z": "Solar Elevation & Centrality Mass (Cosmic Z)" if layout_mode == "thematic" else "Graph Centrality & Hub Authority (PCA-3)"
                    },
                    "stats": {
                        "total_nodes": 0,
                        "rendered_nodes": 0,
                        "total_edges": 0,
                        "rendered_edges": 0,
                        "quota_per_type": quota_per_type,
                        "layout": layout_mode
                    },
                    "active_filters": active_filters,
                    "focus_node_id": focus_node_id,
                    "layout": layout_mode
                }

            max_degree = max((r.get("degree", 0) for r in raw_nodes), default=1) or 1
            node_id_set = set()
            nodes_data = []

            # 3D Cluster anchors for Spatial Layout
            cluster_centers = {
                0: (-55.0, 15.0, 30.0),    # Organizations
                1: (50.0, -10.0, 45.0),    # Contracts & Projects
                2: (-20.0, 40.0, -25.0),   # Persons
                3: (-65.0, -35.0, -40.0),  # Locations
                4: (60.0, 35.0, -15.0),    # Statutes & Milestones
                5: (10.0, -45.0, 10.0),    # Financial Pillars & Currencies (Gold cluster)
                6: (0.0, 0.0, 40.0),       # Thematic Hubs in Spatial View
            }

            # Pre-calculate Sun anchors for Thematic Mindmap Layout
            theme_nodes_list = [r["node_id"] for r in raw_nodes if r.get("node_type") == "theme"]
            num_themes = max(1, len(theme_nodes_list))
            theme_anchors = {}
            for i, t_nid in enumerate(theme_nodes_list):
                angle = (2.0 * math.pi * i) / num_themes
                r_sun = 135.0
                x_sun = math.cos(angle) * r_sun
                y_sun = math.sin(angle) * r_sun
                z_sun = math.sin(i * 1.5) * 35.0
                theme_anchors[t_nid] = (round(x_sun, 2), round(y_sun, 2), round(z_sun, 2))

            for idx, r in enumerate(raw_nodes):
                nid = r["node_id"]
                ntype = r["node_type"] or "organization"
                name = r["name"] or nid
                doc_count = r.get("doc_count") or 0
                degree = r.get("degree") or 0
                latest_date = r.get("latest_doc_date") or "2024-01-01"

                node_id_set.add(nid)

                # Cluster mapping based on entity type archetype
                if ntype == "organization":
                    cid = 0
                elif ntype in ["contract_type", "document_category", "document", "project_code"]:
                    cid = 1
                elif ntype == "person":
                    cid = 2
                elif ntype == "location":
                    cid = 3
                elif ntype in ["statute", "milestone_date"]:
                    cid = 4
                elif ntype in ["currency", "financial_pillar", "monetary_value"]:
                    cid = 5
                elif ntype == "theme":
                    cid = 6
                else:
                    cid = idx % len(cluster_definitions)

                cluster_meta = cluster_definitions[cid]
                node_color = cluster_meta["color"]
                node_icon = cluster_meta["icon"]

                # Extract document-level theme association if present
                theme_id_for_node = None
                parsed_props = {}
                if r.get("properties_json"):
                    try:
                        parsed_props = json.loads(r["properties_json"])
                        theme_id_for_node = parsed_props.get("theme_id")
                    except Exception:
                        pass

                if ntype == "theme":
                    theme_id_for_node = nid
                    if nid in THEME_PALETTE:
                        node_color = THEME_PALETTE[nid]["color"]
                        node_icon = THEME_PALETTE[nid]["icon"]

                # Layout coordinate calculation
                if layout_mode == "thematic":
                    if ntype == "theme":
                        x, y, z = theme_anchors.get(nid, (0.0, 0.0, 0.0))
                        size_scale = max(6.5, min(10.5, 6.5 + (math.sqrt(degree + 1) * 0.4)))
                    elif ntype == "document":
                        th_anchor = theme_anchors.get(theme_id_for_node) if theme_id_for_node else None
                        if not th_anchor and theme_anchors:
                            th_anchor = next(iter(theme_anchors.values()))
                        if th_anchor:
                            th_x, th_y, th_z = th_anchor
                            h_val = int(hashlib.md5(nid.encode("utf-8")).hexdigest()[:8], 16)
                            doc_angle = (h_val % 360) * (math.pi / 180.0)
                            r_orbit = 22.0 + (h_val % 35)
                            x = th_x + math.cos(doc_angle) * r_orbit
                            y = th_y + math.sin(doc_angle) * r_orbit
                            z = th_z + ((h_val % 30) - 15.0)
                        else:
                            x, y, z = (0.0, 0.0, 0.0)
                        size_scale = 3.2
                    else:
                        # Connected entity in interstitial cross-pollination space
                        h_val = int(hashlib.md5(nid.encode("utf-8")).hexdigest()[:8], 16)
                        angle = (h_val % 360) * (math.pi / 180.0)
                        r_ent = 45.0 + (h_val % 45)
                        x = math.cos(angle) * r_ent
                        y = math.sin(angle) * r_ent
                        z = ((h_val % 60) - 30.0)
                        size_scale = max(0.9, min(4.5, 0.9 + (math.sqrt(degree + 1) * 0.25)))
                else:
                    # Spatial PCA layout
                    h_val = int(hashlib.md5(nid.encode("utf-8")).hexdigest()[:8], 16)
                    angle = (h_val % 360) * (math.pi / 180.0)
                    radius = 12.0 + (h_val % 45)

                    cx, cy, cz = cluster_centers.get(cid, (0.0, 0.0, 0.0))
                    x = cx + math.cos(angle) * radius

                    year = 2024
                    try:
                        if latest_date and len(latest_date) >= 4:
                            year = int(latest_date[:4])
                    except Exception:
                        year = 2024
                    year_clamped = max(2010, min(2027, year))
                    y = cy + ((year_clamped - 2018) * 9.0) + (math.sin(angle * 2.0) * 10.0)

                    deg_ratio = math.log(degree + 1) / math.log(max_degree + 2)
                    z = cz + (deg_ratio * 120.0 - 50.0) + (math.sin(angle) * 8.0)

                    if ntype == "theme":
                        size_scale = max(6.0, min(9.5, 6.0 + (math.sqrt(degree + 1) * 0.35)))
                    elif ntype == "document":
                        size_scale = 3.2
                    else:
                        size_scale = max(0.8, min(4.5, 0.8 + (math.sqrt(degree + 1) * 0.25)))

                nodes_data.append({
                    "id": nid,
                    "name": name,
                    "type": ntype,
                    "cluster": cid,
                    "cluster_name": cluster_meta["name"],
                    "cluster_color": node_color,
                    "cluster_icon": node_icon,
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "z": round(z, 2),
                    "degree": degree,
                    "doc_count": doc_count,
                    "latest_date": latest_date,
                    "size": round(size_scale, 2),
                    "theme_id": theme_id_for_node,
                    "is_hub": ntype == "theme",
                })

            # 2. Fetch edges linking the selected top nodes
            edges_data = list(extra_edges)
            if node_id_set:
                placeholders = ",".join("?" for _ in node_id_set)
                cur.execute(f"""
                    SELECT source_id, target_id, relation_type, weight
                    FROM knowledge_edges
                    WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})
                    ORDER BY weight DESC
                    LIMIT 3000;
                """, list(node_id_set) + list(node_id_set))
                raw_edges = cur.fetchall()

                for e in raw_edges:
                    edges_data.append({
                        "source": e["source_id"],
                        "target": e["target_id"],
                        "relation": e["relation_type"] or "RELATED_TO",
                        "weight": round(e["weight"] or 1.0, 2)
                    })

                # Bridge document nodes to their linked entities and themes
                doc_shas_to_nid = {}
                for r in raw_nodes:
                    if r.get("node_type") == "document" or r["node_id"].startswith("doc_"):
                        r_sha = r.get("raw_sha")
                        if not r_sha and r.get("properties_json"):
                            try:
                                p_json = json.loads(r["properties_json"])
                                r_sha = p_json.get("sha256")
                            except Exception:
                                pass
                        if not r_sha and r["node_id"].startswith("doc_"):
                            r_sha = r["node_id"][4:]
                        if r_sha:
                            doc_shas_to_nid[r_sha] = r["node_id"]

                if doc_shas_to_nid:
                    p_dshas = ",".join("?" for _ in doc_shas_to_nid)
                    p_nids = ",".join("?" for _ in node_id_set)
                    cur.execute(f"""
                        SELECT sha256_hash, node_id, role, confidence
                        FROM document_entity_links
                        WHERE sha256_hash IN ({p_dshas})
                          AND node_id IN ({p_nids});
                    """, list(doc_shas_to_nid.keys()) + list(node_id_set))
                    for l_row in cur.fetchall():
                        d_sha = l_row["sha256_hash"]
                        doc_nid = doc_shas_to_nid.get(d_sha)
                        target_nid = l_row["node_id"]
                        role = l_row["role"]
                        rel = "CATEGORIZED_AS" if role == THEME_RELATION else (role.upper() if role else "CONTAINS_ENTITY")
                        w = 3.0 if role == THEME_RELATION else 1.8
                        edges_data.append({
                            "source": doc_nid,
                            "target": target_nid,
                            "relation": rel,
                            "weight": w
                        })

                # Bridge isolated locations, statutes, and contracts via shared document co-occurrence
                connected_nodes = {e["source"] for e in edges_data} | {e["target"] for e in edges_data}
                isolated_nodes = [nid for nid in node_id_set if nid not in connected_nodes and not nid.startswith("doc_")]
                if isolated_nodes:
                    iso_placeholders = ",".join("?" for _ in isolated_nodes)
                    all_placeholders = ",".join("?" for _ in node_id_set)
                    cur.execute(f"""
                        SELECT DISTINCT l1.node_id AS source_id, l2.node_id AS target_id,
                               CASE WHEN n1.node_type = 'location' OR n2.node_type = 'location' THEN 'LOCATED_IN'
                                    WHEN n1.node_type = 'statute' OR n2.node_type = 'statute' THEN 'SUBJECT_TO'
                                    WHEN n1.node_type = 'currency' OR n2.node_type = 'currency' THEN 'DENOMINATED_IN'
                                    WHEN n1.node_type = 'financial_pillar' OR n2.node_type = 'financial_pillar' THEN 'INVOLVES_PAYMENT'
                                    ELSE 'CO_OCCURS' END AS relation_type,
                               1.0 AS weight
                        FROM document_entity_links l1
                        JOIN document_entity_links l2 ON l1.sha256_hash = l2.sha256_hash
                        JOIN knowledge_nodes n1 ON l1.node_id = n1.node_id
                        JOIN knowledge_nodes n2 ON l2.node_id = n2.node_id
                        WHERE l1.node_id IN ({iso_placeholders})
                          AND l2.node_id IN ({all_placeholders})
                          AND l1.node_id != l2.node_id
                        LIMIT 1000;
                    """, isolated_nodes + list(node_id_set))
                    for e in cur.fetchall():
                        edges_data.append({
                            "source": e["source_id"],
                            "target": e["target_id"],
                            "relation": e["relation_type"],
                            "weight": 1.0
                        })

            # Deduplicate edges by (source, target, relation)
            deduped_edges = []
            seen_edges = set()
            for edge in edges_data:
                ekey = (edge["source"], edge["target"], edge["relation"])
                if ekey not in seen_edges:
                    seen_edges.add(ekey)
                    deduped_edges.append(edge)
            edges_data = deduped_edges

            # Compute cluster rendered counts and representativity percentages
            cluster_rendered_counts = {c["id"]: 0 for c in cluster_definitions}
            for n in nodes_data:
                cid = n.get("cluster", 0)
                if cid in cluster_rendered_counts:
                    cluster_rendered_counts[cid] += 1

            for c in cluster_definitions:
                total_db = sum(type_counts.get(t, 0) for t in c.get("types", []))
                rendered_cnt = cluster_rendered_counts[c["id"]]
                c["total_in_db"] = total_db
                c["rendered_count"] = rendered_cnt
                c["quota"] = quota_per_type
                c["is_capped"] = (total_db > quota_per_type) and (rendered_cnt >= quota_per_type)
                c["representation_pct"] = round((rendered_cnt / total_db * 100.0), 1) if total_db > 0 else 100.0

            # Overall stats
            cur.execute("SELECT COUNT(*) FROM knowledge_nodes")
            tot_nodes = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM knowledge_edges")
            tot_edges = cur.fetchone()[0]

            return {
                "nodes": nodes_data,
                "edges": edges_data,
                "clusters": cluster_definitions,
                "axes": {
                    "x": "Thematic Gravitational Plane (Cosmic X)" if layout_mode == "thematic" else "Domain Specificity & Category Dispersion (PCA-1)",
                    "y": "Cross-Pollination & Inter-Domain Tension (Cosmic Y)" if layout_mode == "thematic" else "Temporal Recency & Lifecycle Maturity (PCA-2)",
                    "z": "Solar Elevation & Centrality Mass (Cosmic Z)" if layout_mode == "thematic" else "Graph Centrality & Hub Authority (PCA-3)"
                },
                "stats": {
                    "total_nodes": tot_nodes,
                    "rendered_nodes": len(nodes_data),
                    "total_edges": tot_edges,
                    "rendered_edges": len(edges_data),
                    "quota_per_type": quota_per_type,
                    "overall_representativity_pct": round((len(nodes_data) / tot_nodes * 100.0), 1) if tot_nodes > 0 else 100.0,
                    "db_type_counts": type_counts,
                    "dimensionality": "3D Thematic Gravitational Space" if layout_mode == "thematic" else "High-Dim 1024-D -> 3D PCA Space",
                    "clustering_algorithm": "Thematic Gravitational Mindmap (k=7)" if layout_mode == "thematic" else "Stratified Topological Archetypes (k=7)",
                    "layout": layout_mode
                },
                "active_filters": active_filters,
                "focus_node_id": focus_node_id,
                "layout": layout_mode
            }


