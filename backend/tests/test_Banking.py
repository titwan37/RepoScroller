"""Tests for Organization Entity Extraction & Resolution for Banking Documents.

Validates canonical entity mapping, alias resolution, edge generation,
and historical document backfilling for Zuger Kantonalbank and PostFinance.
"""

import json
import sqlite3
import pytest
from pathlib import Path

from backend.config import settings
from backend.ai.graph_extractor import KnowledgeGraphExtractor, KNOWN_BANKING_ORGANIZATIONS
from backend.ledger.graph_store import PropertyGraphStore
from backend.ledger.repository import DocumentRepository


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_zuger_kantonalbank_canonical_node_exists(db_conn):
    """Verify that organization_zuger_kantonalbank exists with canonical metadata."""
    cur = db_conn.cursor()
    cur.execute("""
        SELECT node_id, node_type, name, properties_json 
        FROM knowledge_nodes 
        WHERE node_id = 'organization_zuger_kantonalbank';
    """)
    row = cur.fetchone()
    assert row is not None, "Canonical node 'organization_zuger_kantonalbank' must exist"
    assert row["name"] == "Zuger Kantonalbank"
    assert row["node_type"] == "organization"

    props = json.loads(row["properties_json"])
    assert "ZKB" in props["aliases"]
    assert "Zuger Kantonal Bank" in props["aliases"]
    assert "ZugerKB" in props["aliases"]
    assert props["clearing_code"] == "0787"
    assert props["location"] == "zug"


def test_zuger_kantonalbank_located_in_edge(db_conn):
    """Verify directed edge organization_zuger_kantonalbank -> location_zug."""
    cur = db_conn.cursor()
    cur.execute("""
        SELECT source_id, target_id, relation_type 
        FROM knowledge_edges 
        WHERE source_id = 'organization_zuger_kantonalbank' 
          AND target_id = 'location_zug' 
          AND relation_type = 'LOCATED_IN';
    """)
    row = cur.fetchone()
    assert row is not None, "Edge organization_zuger_kantonalbank -[LOCATED_IN]-> location_zug must exist"


def test_postfinance_canonical_node_exists(db_conn):
    """Verify that organization_postfinance_sa exists with canonical metadata."""
    cur = db_conn.cursor()
    cur.execute("""
        SELECT node_id, node_type, name, properties_json 
        FROM knowledge_nodes 
        WHERE node_id = 'organization_postfinance_sa';
    """)
    row = cur.fetchone()
    assert row is not None, "Canonical node 'organization_postfinance_sa' must exist"
    assert row["name"] == "PostFinance SA"
    assert row["node_type"] == "organization"


def test_extractor_zuger_kantonalbank_header():
    """Verify extractor maps letterhead, postal addresses, and IBAN to canonical node."""
    ext = KnowledgeGraphExtractor()
    sample_text = """
    Zuger Kantonalbank Bahnhofstrasse 1 Postfach 6301 Zug
    Telefon +41 41 709 11 11 www.zugerkb.ch CHE-105.744.410 MWST
    ZugerKB Konto-Set Basis Portfolio Standardportfolio Privatkonto 77-159.624-03 / CHF
    Liegenschaft IBAN CH10 0078 7007 7159 6240 3
    Ihre Kundenberaterin Ana Sliskovic Direktwahl +41 41 709 66
    Eschenstrasse 7 6312 Steinhausen
    Hypothek Zins Zahlung 03.08.23 Zinsbelastung 57.180.462.190.2
    Unstimmigkeiten sind der Bank unverzüglich zu melden.
    """
    kg = ext.extract_knowledge_graph(sample_text, sha256_hash="sha_zkb_test_01", filename="2023_Kontoauszug.pdf")

    node_ids = {n.node_id for n in kg.nodes}
    assert "organization_zuger_kantonalbank" in node_ids
    assert "location_zug" in node_ids
    assert "location_steinhausen" in node_ids
    assert "financial_pillar_mortgage" in node_ids
    assert "financial_pillar_interest" in node_ids

    # Unstimmigkeiten should NEVER be an organization
    assert not any("unstimmigkeiten" in nid for nid in node_ids)

    # Verify link
    link_node_ids = {lnk.node_id for lnk in kg.links}
    assert "organization_zuger_kantonalbank" in link_node_ids


def test_extractor_zkb_abbreviation_with_zug_context():
    """Verify standalone 'ZKB' in a Zug banking context resolves to Zuger Kantonalbank."""
    ext = KnowledgeGraphExtractor()
    sample_text = """
    2025-01-07 ZKB - Hypothek Mahnung
    Hypothek 1 message <sandro.feusi@zugerkb.ch>
    Sehr geehrter Herr Falempin
    Leider konnten wir per Ende Dezember 2024 die Zinsen wieder nicht belasten.
    Wir bitten um Überweisung auf unser Konto in 6300 Zug.
    """
    kg = ext.extract_knowledge_graph(sample_text, sha256_hash="sha_zkb_test_02", filename="2025-01-07_ZKB_Mahnung.pdf")

    node_ids = {n.node_id for n in kg.nodes}
    assert "organization_zuger_kantonalbank" in node_ids


def test_sidecar_3d_universe_zkb_filter():
    """Verify that querying graph-3d with org=ZKB resolves and returns Zuger Kantonalbank."""
    repo = DocumentRepository()
    store = PropertyGraphStore(repo)

    result = store.get_3d_knowledge_universe(limit=200, filters={"org": "ZKB"})
    node_ids = {n["id"] for n in result["nodes"]}
    assert "organization_zuger_kantonalbank" in node_ids
    assert result["focus_node_id"] == "organization_zuger_kantonalbank"


def test_historical_documents_linked_to_zuger_kb(db_conn):
    """Verify that historical documents in the ledger have been tied to organization_zuger_kantonalbank."""
    cur = db_conn.cursor()
    cur.execute("""
        SELECT COUNT(DISTINCT sha256_hash) as doc_count 
        FROM document_entity_links 
        WHERE node_id = 'organization_zuger_kantonalbank';
    """)
    count = cur.fetchone()["doc_count"]
    assert count >= 800, f"Expected at least 800 historical documents linked to Zuger Kantonalbank, found {count}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])