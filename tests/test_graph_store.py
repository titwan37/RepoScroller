"""Unit tests for PropertyGraphStore and neighborhood expansion."""

import pytest
from reposcroller.ledger.db import init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ledger.graph_store import PropertyGraphStore
from reposcroller.ai.graph_schemas import EntityNode, EntityEdge, DocumentEntityLink


def test_property_graph_store_operations(tmp_path):
    db_file = tmp_path / "test_graph.db"
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)
    store = PropertyGraphStore(repository=repo)

    sha = "test_doc_graph_sha1"
    repo.upsert_document(
        sha256_hash=sha,
        simhash="111222333",
        canonical_filename="Contract_UBS_2024.pdf",
        doc_type="commercial_contract",
        lifecycle_status="final",
        completeness_score=1.0,
        maturity_score=0.9,
        page_count=5,
        text_snippet="Contract between UBS AG and Zurich Insurance.",
        doc_date="2024-05-01"
    )

    # 1. Upsert Nodes
    node1 = EntityNode(node_id="org_ubs_ag", node_type="organization", name="UBS AG")
    node2 = EntityNode(node_id="org_zurich_ins", node_type="organization", name="Zurich Insurance")
    store.upsert_node(node1)
    store.upsert_node(node2)

    # 2. Upsert Edge
    edge = EntityEdge(source_id="org_ubs_ag", target_id="org_zurich_ins", relation_type="PARTY_TO")
    store.upsert_edge(edge)

    # 3. Link Document
    link1 = DocumentEntityLink(sha256_hash=sha, node_id="org_ubs_ag", role="counterparty")
    link2 = DocumentEntityLink(sha256_hash=sha, node_id="org_zurich_ins", role="counterparty")
    store.link_document_entity(link1)
    store.link_document_entity(link2)

    # 4. Verify Document Entities
    entities = store.get_document_entities(sha)
    assert len(entities) == 2
    assert {e["node_id"] for e in entities} == {"org_ubs_ag", "org_zurich_ins"}

    # 5. Verify Neighborhood Expansion
    neighborhood = store.expand_entity_neighborhood("org_ubs_ag", max_hops=1)
    assert neighborhood["node_id"] == "org_ubs_ag"
    assert len(neighborhood["outgoing_relations"]) == 1
    assert neighborhood["outgoing_relations"][0]["name"] == "Zurich Insurance"
    assert len(neighborhood["associated_documents"]) == 1
    assert neighborhood["associated_documents"][0]["canonical_filename"] == "Contract_UBS_2024.pdf"

    # 6. Verify Stats
    stats = store.get_graph_stats()
    assert stats["total_nodes"] == 2
    assert stats["total_edges"] == 1
    assert stats["total_document_links"] == 2
