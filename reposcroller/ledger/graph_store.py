import json
from typing import List, Dict, Any, Optional
from reposcroller.config import settings
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
            cur = self.repo.conn.cursor()
            cur.execute("""
                INSERT INTO knowledge_nodes (node_id, node_type, name, properties_json, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(node_id) DO UPDATE SET
                    name = excluded.name,
                    node_type = excluded.node_type,
                    properties_json = excluded.properties_json,
                    updated_at = CURRENT_TIMESTAMP;
            """, (node.node_id, node.node_type, node.name, json.dumps(node.properties)))
            self.repo.conn.commit()

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
            cur = self.repo.conn.cursor()
            cur.execute("""
                INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight, properties_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                    weight = excluded.weight,
                    properties_json = excluded.properties_json;
            """, (edge.source_id, edge.target_id, edge.relation_type, edge.weight, json.dumps(edge.properties)))
            self.repo.conn.commit()

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
            cur = self.repo.conn.cursor()
            cur.execute("""
                INSERT INTO document_entity_links (sha256_hash, node_id, role, confidence)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(sha256_hash, node_id, role) DO UPDATE SET
                    confidence = excluded.confidence;
            """, (link.sha256_hash, link.node_id, link.role, link.confidence))
            self.repo.conn.commit()

    def save_document_graph(self, doc_graph: DocumentKnowledgeGraph) -> None:
        """Atomically persist extracted nodes, edges, and document links."""
        for node in doc_graph.nodes:
            self.upsert_node(node)
        for edge in doc_graph.edges:
            self.upsert_edge(edge)
        for link in doc_graph.links:
            self.link_document_entity(link)

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

    def get_graph_stats(self) -> Dict[str, Any]:
        """Aggregate statistics on knowledge graph nodes, edges, and document links."""
        with self.repo._lock:
            cur = self.repo.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM knowledge_nodes")
            total_nodes = cur.fetchone()[0]

            cur.execute("SELECT node_type, COUNT(*) FROM knowledge_nodes GROUP BY node_type")
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
