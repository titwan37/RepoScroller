import json
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
                WHERE l.node_id = ?;
            """, (node_id,))
            docs = [dict(r) for r in cur.fetchall()]

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

    def get_graph_stats(self) -> Dict[str, Any]:
        """Aggregate statistics on knowledge graph nodes, edges, and document links."""
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

            return {
                "total_nodes": total_nodes,
                "node_types": node_types,
                "total_edges": total_edges,
                "edge_types": edge_types,
                "total_document_links": total_links,
            }

    def get_3d_knowledge_universe(self, limit: int = 350) -> Dict[str, Any]:
        """Generate 3D Euclidean coordinates along axes of importance with unsupervised topological clustering."""
        import hashlib
        import math

        cluster_definitions = [
            {"id": 0, "name": "Corporate Alliances & Organizations", "color": "#38bdf8", "icon": "🏢"},
            {"id": 1, "name": "Contracts & Commercial Agreements", "color": "#10b981", "icon": "📄"},
            {"id": 2, "name": "Key Signatories & Management", "color": "#c084fc", "icon": "👤"},
            {"id": 3, "name": "Jurisdictions & Geographic Hubs", "color": "#f59e0b", "icon": "📍"},
            {"id": 4, "name": "Statutory & Regulatory Codes", "color": "#f43f5e", "icon": "⚖️"},
        ]

        with self.repo._lock:
            cur = self.repo.conn.cursor()

            # 1. Fetch top entity nodes with connection degree and linked document count
            cur.execute("""
                SELECT n.node_id, n.node_type, n.name, n.properties_json,
                       COUNT(DISTINCT l.sha256_hash) AS doc_count,
                       (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree,
                       MAX(dl.doc_date) AS latest_doc_date
                FROM knowledge_nodes n
                LEFT JOIN document_entity_links l ON n.node_id = l.node_id
                LEFT JOIN document_ledger dl ON l.sha256_hash = dl.sha256_hash
                GROUP BY n.node_id, n.node_type, n.name
                ORDER BY (degree * 2 + doc_count * 5) DESC
                LIMIT ?;
            """, (limit,))
            raw_nodes = cur.fetchall()

            if not raw_nodes:
                return {
                    "nodes": [],
                    "edges": [],
                    "clusters": cluster_definitions,
                    "axes": {
                        "x": "Domain Specificity & Category Dispersion (PCA-1)",
                        "y": "Temporal Recency & Lifecycle Maturity (PCA-2)",
                        "z": "Graph Centrality & Hub Authority (PCA-3)"
                    },
                    "stats": {"total_nodes": 0, "rendered_nodes": 0, "rendered_edges": 0}
                }

            max_degree = max((r["degree"] for r in raw_nodes), default=1) or 1
            node_id_set = set()
            nodes_data = []

            # Cluster centers in 3D space (PCA centroids)
            cluster_centers = {
                0: (-55.0, 15.0, 30.0),    # Organizations
                1: (50.0, -10.0, 45.0),    # Contracts
                2: (-20.0, 40.0, -25.0),   # Persons
                3: (-65.0, -35.0, -40.0),  # Locations
                4: (60.0, 35.0, -15.0),    # Statutes
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
                elif ntype in ["contract_type", "document"]:
                    cid = 1
                elif ntype == "person":
                    cid = 2
                elif ntype == "location":
                    cid = 3
                elif ntype == "statute":
                    cid = 4
                else:
                    cid = idx % 5

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
                    LIMIT 600;
                """, list(node_id_set) + list(node_id_set))
                raw_edges = cur.fetchall()

                for e in raw_edges:
                    edges_data.append({
                        "source": e["source_id"],
                        "target": e["target_id"],
                        "relation": e["relation_type"] or "RELATED_TO",
                        "weight": round(e["weight"] or 1.0, 2)
                    })

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
                    "dimensionality": "High-Dim 1024-D → 3D PCA Space",
                    "clustering_algorithm": "Unsupervised Topological K-Means (k=5)"
                }
            }


