"""Unit and integration test for dynamic 3D graph filtering and document visualization."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.api.app import app
from backend.ledger.graph_store import PropertyGraphStore
from backend.ledger.repository import DocumentRepository
from backend.ledger.db import init_db
from backend.ai.graph_schemas import EntityNode, EntityEdge, DocumentEntityLink


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test_graph_filter.db"
    init_db(db_path)
    repo = DocumentRepository(db_path=db_path)
    store = PropertyGraphStore(repository=repo)

    # Insert document first for foreign key constraint
    repo.upsert_document(
        sha256_hash="sha_test_123",
        simhash="123456",
        canonical_filename="test_doc.pdf",
        doc_type="legal_contract",
        lifecycle_status="active",
        completeness_score=1.0,
        maturity_score=0.9,
        page_count=5,
        text_snippet="ZKB Zurich agreement"
    )

    # Insert test nodes
    store.upsert_node(EntityNode(node_id="org_zkb", node_type="organization", name="Zürcher Kantonalbank", properties={"location": "zurich", "aliases": ["ZKB"]}))
    store.upsert_node(EntityNode(node_id="org_ubs", node_type="organization", name="UBS Group AG", properties={"location": "zurich"}))
    store.upsert_node(EntityNode(node_id="loc_zurich", node_type="location", name="Zurich", properties={"country": "CH"}))
    store.upsert_node(EntityNode(node_id="doc_node_1", node_type="statute", name="ZKB Annual Report", properties={"org": "ZKB"}))
    store.upsert_node(EntityNode(node_id="statute_sr/142.20", node_type="statute", name="SR 142.20", properties={}))

    # Insert test edges
    store.upsert_edge(EntityEdge(source_id="org_zkb", target_id="loc_zurich", relation_type="located_in", weight=1.0))
    store.upsert_edge(EntityEdge(source_id="org_zkb", target_id="doc_node_1", relation_type="mentions", weight=0.9))

    # Link document
    store.link_document_entity(DocumentEntityLink(sha256_hash="sha_test_123", node_id="org_zkb", role="subject", confidence=0.95))
    store.link_document_entity(DocumentEntityLink(sha256_hash="sha_test_123", node_id="loc_zurich", role="location", confidence=0.95))

    # Patch global graph store in sidecar route
    from backend.api.routes import sidecar
    original_store = sidecar._graph_store
    sidecar._graph_store = store

    test_client = TestClient(app)
    yield test_client

    sidecar._graph_store = original_store


def test_graph_3d_location_and_org_filtering(client):
    response = client.get("/api/v1/sidecar/graph-3d?location=zurich&org=ZKB")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert "active_filters" in data
    assert data["active_filters"].get("org") == "ZKB"
    assert data["active_filters"].get("location") == "zurich"

    # Node ids matching ZKB and Zurich
    node_ids = {n["id"] for n in data["nodes"]}
    assert "org_zkb" in node_ids
    assert "loc_zurich" in node_ids


def test_graph_3d_doc_sha_filtering(client):
    response = client.get("/api/v1/sidecar/graph-3d?doc_sha=sha_test_123")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert data.get("focus_node_id") is not None
    node_ids = {n["id"] for n in data["nodes"]}
    assert "org_zkb" in node_ids or "loc_zurich" in node_ids or "doc_sha_test_123" in node_ids


def test_node_neighborhood_entity(client):
    # Test path endpoint
    resp = client.get("/api/v1/sidecar/graph/node/org_zkb")
    assert resp.status_code == 200
    data = resp.json()
    assert data["node_id"] == "org_zkb"
    assert len(data["outgoing_relations"]) >= 2
    assert len(data["associated_documents"]) >= 1

    # Test query param endpoint
    resp_q = client.get("/api/v1/sidecar/graph/node?id=org_zkb")
    assert resp_q.status_code == 200
    data_q = resp_q.json()
    assert data_q["node_id"] == "org_zkb"


def test_node_neighborhood_document(client):
    # Test document node neighborhood
    resp = client.get("/api/v1/sidecar/graph/node/doc_sha_test_123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["node_type"] == "document"
    assert len(data["outgoing_relations"]) >= 2
    assert len(data["associated_documents"]) >= 1


def test_node_neighborhood_with_slash(client):
    resp = client.get("/api/v1/sidecar/graph/node/statute_sr/142.20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["node_id"] == "statute_sr/142.20"
