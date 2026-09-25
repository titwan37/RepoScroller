"""Unit tests for the KnowledgeGraphExtractor."""

import pytest
from reposcroller.ai.graph_extractor import KnowledgeGraphExtractor, canonicalize_node_id


def test_canonicalize_node_id():
    assert canonicalize_node_id("org", "UBS Switzerland AG") == "org_ubs_switzerland_ag"
    assert canonicalize_node_id("person", "Dr. Alice Smith, LL.M.") == "person_dr_alice_smith_llm"


def test_graph_extractor_heuristic():
    extractor = KnowledgeGraphExtractor(provider="mock")
    text = """
    EMPLOYMENT AGREEMENT
    Between: Swisscom AG (Employer) and Alice Dupont (Employee).
    Signed by: Alice Dupont and Marc Meier.
    Governing Law: This contract is governed by Swiss law, in particular Art. 320 OR.
    Place of jurisdiction: Zurich, Switzerland.
    """
    doc_graph = extractor.extract_knowledge_graph(
        text=text,
        sha256_hash="sha_contract_swisscom",
        filename="Employment_Contract_Swisscom.pdf",
        doc_type="employment_contract"
    )

    assert len(doc_graph.nodes) >= 3
    node_names = [n.name.lower() for n in doc_graph.nodes]
    assert any("swisscom" in name for name in node_names)
    assert any("alice" in name for name in node_names)
    assert any("zurich" in name or "zürich" in name for name in node_names)


    assert len(doc_graph.links) >= 3
    assert len(doc_graph.edges) >= 1
