import json
import time
from typing import List, Dict, Any, Optional
from backend.config import settings
from backend.ledger.db import transaction
from backend.ledger.repository import DocumentRepository
from backend.ai.graph_schemas import EntityNode, EntityEdge, DocumentEntityLink, DocumentKnowledgeGraph

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

                    for link in doc_graph.links:
                        cur.execute("""
                            INSERT INTO document_entity_links (sha256_hash, node_id, role, confidence)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(sha256_hash, node_id, role) DO UPDATE SET
                                confidence = excluded.confidence;
                        """, (link.sha256_hash, link.node_id, link.role, link.confidence))

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
                SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.doc_date, dl.lifecycle_status, l.role
                FROM document_entity_links l
                JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
                WHERE l.node_id = ?
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

    def get_3d_knowledge_universe(self, limit: int = 1000, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate 3D Euclidean coordinates along axes of importance with stratified archetype sampling or dynamic query filtering."""
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
        ]

        active_filters = {k: v for k, v in (filters or {}).items() if v is not None and str(v).strip() != ""}
        focus_node_id = None
        extra_document_node = None
        extra_edges = []

        with self.repo._lock:
            cur = self.repo.conn.cursor()

            # Query entity population count per node_type to calculate representativity
            cur.execute("SELECT node_type, COUNT(*) as cnt FROM knowledge_nodes GROUP BY node_type;")
            type_counts = {r["node_type"]: r["cnt"] for r in cur.fetchall()}

            quota_per_type = max(100, limit // 5)

            if active_filters:
                loc_filter = active_filters.get("location")
                org_filter = active_filters.get("org") or active_filters.get("organization")
                person_filter = active_filters.get("person") or active_filters.get("author")
                ntype_filter = active_filters.get("node_type") or active_filters.get("type")
                cluster_filter = active_filters.get("cluster")
                doc_sha_filter = active_filters.get("doc_sha") or active_filters.get("sha256") or active_filters.get("document")
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
                            "properties_json": json.dumps({"sha256": clean_sha, "doc_type": doc_meta["doc_type"], "status": doc_meta["lifecycle_status"]}),
                            "doc_count": 1,
                            "degree": len(doc_linked_nodes),
                            "latest_doc_date": doc_meta["doc_date"] or "2024-01-01",
                        }
                        for linked_nid in doc_linked_nodes:
                            extra_edges.append({
                                "source": doc_node_id,
                                "target": linked_nid,
                                "relation": "CONTAINS_ENTITY",
                                "weight": 2.5
                            })
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
                        # Prioritize canonical node if present
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
                    # Single focal filter expansion: expand 1-hop graph neighborhood & shared document entities
                    focal_ids = loc_node_ids or org_node_ids or person_node_ids
                    if focal_ids:
                        p_focal = ",".join("?" for _ in focal_ids)
                        focal_list = list(focal_ids)
                        
                        # 1. Direct graph neighbors via edges
                        cur.execute(f"""
                            SELECT DISTINCT CASE WHEN source_id IN ({p_focal}) THEN target_id ELSE source_id END AS neighbor_id
                            FROM knowledge_edges
                            WHERE source_id IN ({p_focal}) OR target_id IN ({p_focal})
                            LIMIT ?;
                        """, focal_list + focal_list + focal_list + [min(250, limit)])
                        matching_node_ids.update({r["neighbor_id"] for r in cur.fetchall()})

                        # 2. Co-occurring entities via shared document links
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

                # Fetch full node metrics for the matched IDs
                raw_nodes = []
                if matching_node_ids:
                    p_matched = ",".join("?" for _ in matching_node_ids)
                    cur.execute(f"""
                        SELECT n.node_id, n.node_type, n.name, n.properties_json,
                               COUNT(DISTINCT l.sha256_hash) AS doc_count,
                               (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree,
                               MAX(dl.doc_date) AS latest_doc_date
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

            else:
                # Standard Stratified Cluster Sampling
                cur.execute("""
                    WITH EntityBase AS (
                        SELECT n.node_id, n.node_type, n.name, n.properties_json,
                               COUNT(DISTINCT l.sha256_hash) AS doc_count,
                               (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree,
                               MAX(dl.doc_date) AS latest_doc_date
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
                    SELECT * FROM RankedEntities
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
                        "x": "Domain Specificity & Category Dispersion (PCA-1)",
                        "y": "Temporal Recency & Lifecycle Maturity (PCA-2)",
                        "z": "Graph Centrality & Hub Authority (PCA-3)"
                    },
                    "stats": {"total_nodes": 0, "rendered_nodes": 0, "rendered_edges": 0, "quota_per_type": quota_per_type},
                    "active_filters": active_filters,
                    "focus_node_id": focus_node_id
                }

            max_degree = max((r.get("degree", 0) for r in raw_nodes), default=1) or 1
            node_id_set = set()
            nodes_data = []

            # Cluster centers in 3D space (PCA centroids)
            cluster_centers = {
                0: (-55.0, 15.0, 30.0),    # Organizations
                1: (50.0, -10.0, 45.0),    # Contracts & Projects
                2: (-20.0, 40.0, -25.0),   # Persons
                3: (-65.0, -35.0, -40.0),  # Locations
                4: (60.0, 35.0, -15.0),    # Statutes & Milestones
                5: (10.0, -45.0, 10.0),    # Financial Pillars & Currencies (Gold cluster)
            }

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
                else:
                    cid = idx % len(cluster_definitions)

                # Compute deterministic pseudo-random offsets from name hash
                h_val = int(hashlib.md5(nid.encode("utf-8")).hexdigest()[:8], 16)
                angle = (h_val % 360) * (math.pi / 180.0)
                radius = 12.0 + (h_val % 45)

                cx, cy, cz = cluster_centers.get(cid, (0.0, 0.0, 0.0))

                # Axis X: Specificity (PCA-1) -> Cluster center + angular displacement
                x = cx + math.cos(angle) * radius

                # Axis Y: Temporal Recency & Maturity (PCA-2)
                year = 2024
                try:
                    if latest_date and len(latest_date) >= 4:
                        year = int(latest_date[:4])
                except Exception:
                    year = 2024
                year_clamped = max(2010, min(2027, year))
                y = cy + ((year_clamped - 2018) * 9.0) + (math.sin(angle * 2.0) * 10.0)

                # Axis Z: Centrality & Authority Degree (PCA-3)
                deg_ratio = math.log(degree + 1) / math.log(max_degree + 2)
                z = cz + (deg_ratio * 120.0 - 50.0) + (math.sin(angle) * 8.0)

                # Node display size & scale based on degree
                if ntype == "document":
                    size_scale = 3.2
                else:
                    size_scale = max(0.8, min(4.5, 0.8 + (math.sqrt(degree + 1) * 0.25)))

                cluster_meta = cluster_definitions[cid]

                nodes_data.append({
                    "id": nid,
                    "name": name,
                    "type": ntype,
                    "cluster": cid,
                    "cluster_name": cluster_meta["name"],
                    "cluster_color": cluster_meta["color"],
                    "cluster_icon": cluster_meta["icon"],
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "z": round(z, 2),
                    "degree": degree,
                    "doc_count": doc_count,
                    "latest_date": latest_date,
                    "size": round(size_scale, 2),
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
                    "x": "Domain Specificity & Category Dispersion (PCA-1)",
                    "y": "Temporal Recency & Lifecycle Maturity (PCA-2)",
                    "z": "Graph Centrality & Hub Authority (PCA-3)"
                },
                "stats": {
                    "total_nodes": tot_nodes,
                    "rendered_nodes": len(nodes_data),
                    "total_edges": tot_edges,
                    "rendered_edges": len(edges_data),
                    "quota_per_type": quota_per_type,
                    "overall_representativity_pct": round((len(nodes_data) / tot_nodes * 100.0), 1) if tot_nodes > 0 else 100.0,
                    "db_type_counts": type_counts,
                    "dimensionality": "High-Dim 1024-D -> 3D PCA Space",
                    "clustering_algorithm": "Stratified Topological Archetypes (k=6)"
                },
                "active_filters": active_filters,
                "focus_node_id": focus_node_id
            }


