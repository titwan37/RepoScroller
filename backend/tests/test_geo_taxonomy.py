"""Tests for Hierarchical Geo-Taxonomy, Recursive SQLite CTE Rollup, and Disambiguation."""

import sqlite3
import pytest
from backend.ledger.db import init_db
from backend.ledger.geo_taxonomy import (
    init_geo_taxonomy,
    get_sub_regions,
    classify_text_geo,
    backfill_document_geo_links,
)
from backend.ledger.graph_store import PropertyGraphStore
from backend.ledger.repository import DocumentRepository


@pytest.fixture
def mem_db(tmp_path):
    db_file = tmp_path / "test_geo.db"
    init_db(db_file)
    conn = sqlite3.connect(db_file)
    init_geo_taxonomy(conn)
    yield conn, db_file
    conn.close()


def test_geo_taxonomy_hierarchy_seeding(mem_db):
    conn, _ = mem_db
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM geo_taxonomy WHERE parent_id = 'CH-ZG';")
    zug_municipalities = cur.fetchone()[0]
    assert zug_municipalities >= 10, f"Expected at least 10 municipalities in Canton Zug, got {zug_municipalities}"

    # Check Steinhausen PLZ and BFS
    cur.execute("SELECT postal_code, bfs_nr, parent_id FROM geo_taxonomy WHERE geo_id = 'CH-ZG-6312';")
    row = cur.fetchone()
    assert row == ("6312", 1708, "CH-ZG")

    # Check Stadt Zug
    cur.execute("SELECT postal_code, bfs_nr, parent_id FROM geo_taxonomy WHERE geo_id = 'CH-ZG-6300';")
    row = cur.fetchone()
    assert row == ("6300", 1711, "CH-ZG")


def test_recursive_cte_canton_rollup(mem_db):
    conn, _ = mem_db
    # Test rollup on 'CH-ZG'
    sub_regions = get_sub_regions(conn, "CH-ZG")
    geo_ids = {sr["geo_id"] for sr in sub_regions}

    assert "CH-ZG" in geo_ids
    assert "CH-ZG-6300" in geo_ids  # Stadt Zug
    assert "CH-ZG-6312" in geo_ids  # Steinhausen
    assert "CH-ZG-6340" in geo_ids  # Baar
    assert "CH-ZG-6330" in geo_ids  # Cham

    # Test alias rollup on 'kanton zug'
    sub_regions_alias = get_sub_regions(conn, "kanton zug")
    assert len(sub_regions_alias) == len(sub_regions)


def test_disambiguation_rules():
    # 1. High precision postal code / leaf matches
    res_steinhausen = classify_text_geo("Eschenstrasse 7, 6312 Steinhausen, Schweiz", "invoice.pdf")
    geo_set_sth = {geo_id for geo_id, _ in res_steinhausen}
    assert "CH-ZG-6312" in geo_set_sth
    assert "CH-ZG" in geo_set_sth

    res_baar = classify_text_geo("Lindenstrasse 10, 6340 Baar", "contract.pdf")
    geo_set_baar = {geo_id for geo_id, _ in res_baar}
    assert "CH-ZG-6340" in geo_set_baar

    # 2. Cantonal context for bare 'Zug'
    res_canton_court = classify_text_geo("Kantonsgericht Zug Verfügung betreffend Eheschutz", "court.pdf")
    geo_set_court = {geo_id for geo_id, _ in res_canton_court}
    assert "CH-ZG" in geo_set_court

    # 3. Postal address context for bare 'Zug'
    res_postal_zug = classify_text_geo("Postfach 1234, 6301 Zug", "statement.pdf")
    geo_set_pzug = {geo_id for geo_id, _ in res_postal_zug}
    assert "CH-ZG-6300" in geo_set_pzug


def test_organization_zkb_binding(mem_db):
    conn, _ = mem_db
    cur = conn.cursor()

    cur.execute("SELECT canonical_name, hq_geo_id, jurisdiction_geo_id FROM organization_entities WHERE org_id = 'org_zkb';")
    row = cur.fetchone()
    assert row == ("Zuger Kantonalbank", "CH-ZG-6300", "CH-ZG")

    cur.execute("SELECT COUNT(*) FROM organization_aliases WHERE org_id = 'org_zkb';")
    alias_count = cur.fetchone()[0]
    assert alias_count >= 5


def test_3d_universe_geo_rollup(mem_db):
    conn, db_file = mem_db
    cur = conn.cursor()

    # Insert mock document ledger and geo links
    cur.execute("""
        INSERT INTO document_ledger (sha256_hash, canonical_filename, doc_type, doc_date)
        VALUES 
            ('sha_zug_doc_1', 'WWZ_Rechnung_Steinhausen.pdf', 'financial_invoice', '2025-01-15'),
            ('sha_zug_doc_2', 'ZKB_Kontoauszug_Zug.pdf', 'financial_invoice', '2025-02-01');
    """)

    cur.execute("""
        INSERT INTO document_geo_links (sha256_hash, geo_id, confidence)
        VALUES 
            ('sha_zug_doc_1', 'CH-ZG-6312', 1.0),
            ('sha_zug_doc_2', 'CH-ZG-6300', 1.0);
    """)

    cur.execute("""
        INSERT INTO document_entity_links (sha256_hash, node_id, role)
        VALUES 
            ('sha_zug_doc_1', 'organization_wwz_energie', 'signatory'),
            ('sha_zug_doc_2', 'organization_zuger_kantonalbank', 'signatory');
    """)

    cur.execute("""
        INSERT INTO knowledge_nodes (node_id, node_type, name)
        VALUES 
            ('organization_wwz_energie', 'organization', 'WWZ Energie AG'),
            ('organization_zuger_kantonalbank', 'organization', 'Zuger Kantonalbank'),
            ('location_ch_zg', 'location', 'Kanton Zug'),
            ('location_ch_zg_6300', 'location', 'Stadt Zug'),
            ('location_ch_zg_6312', 'location', 'Steinhausen');
    """)

    conn.commit()

    repo = DocumentRepository(db_path=db_file)
    gs = PropertyGraphStore(repo)

    # Query cantonal rollup
    universe = gs.get_3d_knowledge_universe(limit=50, filters={"location": "zug", "level": "canton"})
    node_ids = {n["id"] for n in universe["nodes"]}

    assert "organization_wwz_energie" in node_ids
    assert "organization_zuger_kantonalbank" in node_ids
    assert universe["focus_node_id"] == "location_ch_zg"
