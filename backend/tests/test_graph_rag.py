"""Unit tests for GraphRAG multi-signal hybrid retrieval and RRF fusion."""

import pytest
from backend.ledger.db import init_db
from backend.ledger.repository import DocumentRepository
from backend.ledger.vector_store import VectorStore
from backend.ledger.graph_store import PropertyGraphStore
from backend.ai.embeddings import EmbeddingAdapter
from backend.ai.graph_schemas import EntityNode, EntityEdge, DocumentEntityLink
from backend.ai.graph_extractor import KnowledgeGraphExtractor
from backend.agents.graph_rag import GraphRAGQueryEngine


def test_graph_rag_hybrid_query(tmp_path):
    db_file = tmp_path / "test_graph_rag.db"
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)
    embedder = EmbeddingAdapter(provider="mock", dimension=64)
    vstore = VectorStore(repository=repo, embedding_adapter=embedder)
    gstore = PropertyGraphStore(repository=repo)
    engine = GraphRAGQueryEngine(repository=repo, vector_store=vstore, graph_store=gstore, embedding_adapter=embedder)

    sha = "test_graph_rag_sha_456"
    repo.upsert_document(
        sha256_hash=sha,
        simhash="456789123",
        canonical_filename="2024_0615_Tenancy_Contract_Zurich.pdf",
        doc_type="lease_contract",
        lifecycle_status="final",
        completeness_score=1.0,
        maturity_score=0.95,
        page_count=4,
        text_snippet="Apartment rental agreement in Zurich.",
        doc_date="2024-06-15",
        full_text="Apartment rental agreement in Zurich between Landlord and Tenant Alice for monthly rent of CHF 3,000."
    )

    # Index vector chunk
    vstore.index_document_chunks(sha, [{
        "chunk_id": f"{sha}_0",
        "sha256_hash": sha,
        "chunk_index": 0,
        "chunk_text": "Apartment rental agreement in Zurich between Landlord and Tenant Alice.",
        "token_count": 10
    }])

    # Index graph entity & link
    node = EntityNode(node_id="person_alice", node_type="person", name="Alice")
    gstore.upsert_node(node)
    gstore.link_document_entity(DocumentEntityLink(sha256_hash=sha, node_id="person_alice", role="signatory"))

    # Execute Hybrid GraphRAG query
    result = engine.query(query_text="rental agreement Alice Zurich", top_k=3)

    assert len(result["top_candidates"]) >= 1
    assert result["top_candidates"][0]["sha256_hash"] == sha
    assert len(result["graph_entities"]) >= 1
    assert result["graph_entities"][0]["node"]["name"] == "Alice"
    assert result["retrieval_signals"]["fused_candidates_count"] >= 1


def test_3d_knowledge_universe_representativity(tmp_path):
    db_file = tmp_path / "test_graph_universe.db"
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)
    gstore = PropertyGraphStore(repository=repo)

    # Insert 10 organizations and 2 locations
    for i in range(10):
        gstore.upsert_node(EntityNode(node_id=f"org_{i}", node_type="organization", name=f"Org {i}"))
    for i in range(2):
        gstore.upsert_node(EntityNode(node_id=f"loc_{i}", node_type="location", name=f"Loc {i}"))

    # Test with quota of 5 per archetype (limit=20 -> max(100, 20//4) = 100, or custom limit=400 -> 100)
    # With limit=16 -> max(100, 16//4) = 100
    res = gstore.get_3d_knowledge_universe(limit=1000)

    assert len(res["nodes"]) == 12
    assert "clusters" in res
    assert len(res["clusters"]) == 5

    # Find Organizations cluster (id 0) and Locations cluster (id 3)
    org_cluster = next(c for c in res["clusters"] if c["id"] == 0)
    loc_cluster = next(c for c in res["clusters"] if c["id"] == 3)

    assert org_cluster["total_in_db"] == 10
    assert org_cluster["rendered_count"] == 10
    assert org_cluster["representation_pct"] == 100.0
    assert org_cluster["quota"] == 250
    assert org_cluster["is_capped"] is False

    assert loc_cluster["total_in_db"] == 2
    assert loc_cluster["rendered_count"] == 2
    assert loc_cluster["representation_pct"] == 100.0

    assert "overall_representativity_pct" in res["stats"]
    assert res["stats"]["overall_representativity_pct"] == 100.0


def test_extractor_multi_type_edges():
    extractor = KnowledgeGraphExtractor(provider="mock")
    text = (
        "Agreement between Swisscom AG and Alice Dupont in Zurich and Steinhausen. "
        "Governed by Art. 253 OR. Total amount CHF 5,000 for Project ALPHA-9."
    )
    kg = extractor._extract_heuristic_fallback(
        text=text,
        sha256_hash="test_sha_edges_123",
        filename="contract_zurich.pdf",
        doc_type="lease_contract"
    )

    relation_types = {e.relation_type for e in kg.edges}
    assert "PARTY_TO" in relation_types
    assert "LOCATED_IN" in relation_types
    assert "JURISDICTION" in relation_types
    assert "SUBJECT_TO" in relation_types
    assert "GOVERNED_BY" in relation_types
    assert "VALUED_AT" in relation_types
    assert "ASSIGNED_TO" in relation_types

    # Test person-specific RESIDES_IN
    person_text = "Signed by Hans Peter in Ottenbach."
    person_kg = extractor._extract_heuristic_fallback(
        text=person_text,
        sha256_hash="test_sha_person_456",
        filename="person_sign.pdf",
        doc_type="employment_contract"
    )
    person_relations = {e.relation_type for e in person_kg.edges}
    assert "RESIDES_IN" in person_relations


def test_expand_entity_neighborhood_lod(tmp_path):
    db_file = tmp_path / "test_lod_neighborhood.db"
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)
    gstore = PropertyGraphStore(repository=repo)

    # Insert parent node and 3 neighbors with edges
    gstore.upsert_node(EntityNode(node_id="loc_zug", node_type="location", name="Zug"))
    gstore.upsert_node(EntityNode(node_id="org_crypto_ag", node_type="organization", name="Crypto AG"))
    gstore.upsert_node(EntityNode(node_id="stat_or253", node_type="statute", name="Art. 253 OR"))

    gstore.upsert_edge(EntityEdge(source_id="org_crypto_ag", target_id="loc_zug", relation_type="LOCATED_IN", weight=1.0))
    gstore.upsert_edge(EntityEdge(source_id="org_crypto_ag", target_id="stat_or253", relation_type="SUBJECT_TO", weight=1.0))

    # Expand neighborhood of Crypto AG
    nh = gstore.expand_entity_neighborhood(node_id="org_crypto_ag", max_hops=1)
    assert nh["node_id"] == "org_crypto_ag"
    outgoing_targets = {r["node_id"] for r in nh["outgoing_relations"]}
    assert "loc_zug" in outgoing_targets
    assert "stat_or253" in outgoing_targets


