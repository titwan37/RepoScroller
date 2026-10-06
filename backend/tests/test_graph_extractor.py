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
    Salary & Compensation: The base salary shall be paid monthly in CHF. A discretionary bonus applies.
    Governing Law: This contract is governed by Swiss law, in particular Art. 320 OR.
    Place of jurisdiction: Zurich, Switzerland.
    """
    doc_graph = extractor.extract_knowledge_graph(
        text=text,
        sha256_hash="sha_contract_swisscom",
        filename="Employment_Contract_Swisscom.pdf",
        doc_type="employment_contract"
    )

    assert len(doc_graph.nodes) >= 5
    node_names = [n.name.lower() for n in doc_graph.nodes]
    node_types = [n.node_type for n in doc_graph.nodes]

    assert any("swisscom" in name for name in node_names)
    assert any("alice" in name for name in node_names)
    assert any("zurich" in name or "zürich" in name for name in node_names)
    assert "currency" in node_types
    assert "financial_pillar" in node_types

    # Verify Currency & Financial Pillar nodes
    currency_nodes = [n for n in doc_graph.nodes if n.node_type == "currency"]
    pillar_nodes = [n for n in doc_graph.nodes if n.node_type == "financial_pillar"]
    assert any(c.name == "CHF" for c in currency_nodes)
    assert any("salary" in p.name.lower() for p in pillar_nodes)

    # Verify Relationship Edges
    edge_relations = [e.relation_type for e in doc_graph.edges]
    assert "DENOMINATED_IN" in edge_relations
    assert "INVOLVES_PAYMENT" in edge_relations
    assert "STIPULATES_CURRENCY" in edge_relations
    assert "PAYS" in edge_relations
    assert "GOVERNED_BY" in edge_relations

    assert len(doc_graph.links) >= 5
    assert len(doc_graph.edges) >= 4


def test_signatory_role_marker_must_be_a_whole_word():
    extractor = KnowledgeGraphExtractor(provider="mock")
    doc_graph = extractor._extract_heuristic_fallback(
        text=(
            "Le MPK mini est maintenant en mesure de communiquer avec votre logiciel.\n"
            "Tenant: Alice Smith."
        ),
        sha256_hash="test_french_tenant_word_boundary",
        filename="user_guide.pdf",
        doc_type="technical_manual",
    )

    person_names = {node.name.lower() for node in doc_graph.nodes if node.node_type == "person"}
    assert "en mesure de communiquer avec votre logiciel" not in person_names
    assert "alice smith" in person_names
