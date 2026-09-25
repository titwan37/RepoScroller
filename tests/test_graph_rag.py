"""Unit tests for GraphRAG multi-signal hybrid retrieval and RRF fusion."""

import pytest
from reposcroller.ledger.db import init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ledger.vector_store import VectorStore
from reposcroller.ledger.graph_store import PropertyGraphStore
from reposcroller.ai.embeddings import EmbeddingAdapter
from reposcroller.ai.graph_schemas import EntityNode, EntityEdge, DocumentEntityLink
from reposcroller.agents.graph_rag import GraphRAGQueryEngine


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
