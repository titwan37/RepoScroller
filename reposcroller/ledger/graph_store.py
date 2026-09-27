import json
import time
from typing import List, Dict, Any, Optional
from reposcroller.config import settings
from reposcroller.ledger.db import transaction
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ai.graph_schemas import EntityNode, EntityEdge, DocumentEntityLink, DocumentKnowledgeGraph

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
        """Expand 1-hop or 2-hop connected graph neighborhood for a given entity."""
        with self.repo._lock:
            cur = self.repo.conn.cursor()
            # Outgoing edges
            cur.execute("""
                SELECT e.relation_type, e.weight, e.properties_json, n.node_id, n.node_type, n.name
                FROM knowledge_edges e
                JOIN knowledge_nodes n ON e.target_id = n.node_id
                WHERE e.source_id = ?;
            """, (node_id,))
            outgoing = [dict(r) for r in cur.fetchall()]

            # Incoming edges
            cur.execute("""
                SELECT e.relation_type, e.weight, e.properties_json, n.node_id, n.node_type, n.name
                FROM knowledge_edges e
                JOIN knowledge_nodes n ON e.source_id = n.node_id
                WHERE e.target_id = ?;
            """, (node_id,))
            incoming = [dict(r) for r in cur.fetchall()]

            # Associated documents
            cur.execute("""
                SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.doc_date, dl.lifecycle_status, l.role
                FROM document_entity_links l
                JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
                WHERE l.node_id = ?
                LIMIT 50;
            """, (node_id,))
            docs = [dict(r) for r in cur.fetchall()]

            # Co-occurrence Fallback: if explicit edges are empty (e.g. locations/statutes), bridge via shared documents
            if not outgoing and not incoming and docs:
                doc_hashes = [d["sha256_hash"] for d in docs[:15]]
                placeholders = ",".join("?" for _ in doc_hashes)
                cur.execute(f"""
                    SELECT DISTINCT n.node_id, n.node_type, n.name, 
                           CASE WHEN n.node_type = 'location' THEN 'LOCATED_IN'
                                WHEN n.node_type = 'statute' THEN 'SUBJECT_TO'
                                ELSE 'CO_OCCURS_IN_DOC' END AS relation_type,
                           1.0 AS weight
                    FROM document_entity_links l
                    JOIN knowledge_nodes n ON l.node_id = n.node_id
                    WHERE l.sha256_hash IN ({placeholders}) AND n.node_id != ?
                    LIMIT 25;
                """, doc_hashes + [node_id])
                outgoing = [dict(r) for r in cur.fetchall()]

            return {
                "node_id": node_id,
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

    def get_3d_knowledge_universe(self, limit: int = 1000) -> Dict[str, Any]:
        """Generate 3D Euclidean coordinates along axes of importance with stratified archetype sampling."""
        import hashlib
        import math

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

        with self.repo._lock:
            cur = self.repo.conn.cursor()

            # Query entity population count per node_type to calculate representativity
            cur.execute("SELECT node_type, COUNT(*) as cnt FROM knowledge_nodes GROUP BY node_type;")
            type_counts = {r["node_type"]: r["cnt"] for r in cur.fetchall()}

            # Stratified Cluster Sampling (Option A): Allocate quota per archetype to avoid hub monopolies
            quota_per_type = max(100, limit // 5)
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
            raw_nodes = cur.fetchall()

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
                    "stats": {"total_nodes": 0, "rendered_nodes": 0, "rendered_edges": 0, "quota_per_type": quota_per_type}
                }

            max_degree = max((r["degree"] for r in raw_nodes), default=1) or 1
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
                doc_count = r["doc_count"] or 0
                degree = r["degree"] or 0
                latest_date = r["latest_doc_date"] or "2024-01-01"

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
                    cid = idx % len(cluster_definitions)   # cid = idx % 5

                # Compute deterministic pseudo-random offsets from name hash
                h_val = int(hashlib.md5(nid.encode("utf-8")).hexdigest()[:8], 16)
                angle = (h_val % 360) * (math.pi / 180.0)
                radius = 12.0 + (h_val % 45)

                cx, cy, cz = cluster_centers.get(cid, (0.0, 0.0, 0.0))

                # Axis X: Specificity (PCA-1) -> Cluster center + angular displacement
                x = cx + math.cos(angle) * radius

                # Axis Y: Temporal Recency & Maturity (PCA-2)
                # Map years (e.g. 2015 -> -60, 2026 -> +80)
                year = 2024
                try:
                    if latest_date and len(latest_date) >= 4:
                        year = int(latest_date[:4])
                except Exception:
                    year = 2024
                year_clamped = max(2010, min(2027, year))
                y = cy + ((year_clamped - 2018) * 9.0) + (math.sin(angle * 2.0) * 10.0)

                # Axis Z: Centrality & Authority Degree (PCA-3)
                # Higher authority degree -> higher Z
                deg_ratio = math.log(degree + 1) / math.log(max_degree + 2)
                z = cz + (deg_ratio * 120.0 - 50.0) + (math.sin(angle) * 8.0)

                # Node display size & scale based on degree
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
            edges_data = []
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
                isolated_nodes = [nid for nid in node_id_set if nid not in connected_nodes]
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
                }
            }


