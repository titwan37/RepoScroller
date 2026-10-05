"""Phase 1 Thematic Mindmap: taxonomy theme hubs in the knowledge graph."""

from backend.ledger.db import init_db
from backend.ledger.repository import DocumentRepository
from backend.ledger.graph_store import PropertyGraphStore
from backend.ai.graph_schemas import THEME_NODE_TYPE, THEME_RELATION
from backend.ai.graph_extractor import (
    KnowledgeGraphExtractor, ThemeResolver, make_db_taxonomy_loader,
)

LEASE_TEXT = (
    "Mietvertrag between Swisscom AG and Alice Dupont in Zurich. "
    "Monthly rent of CHF 3,000. Governed by Art. 253 OR."
)


def _repo(tmp_path):
    db_file = tmp_path / "theme_graph.db"
    init_db(db_file)
    return DocumentRepository(db_path=db_file)


def _add_doc(repo, sha, doc_type):
    repo.upsert_document(
        sha256_hash=sha, simhash="1", canonical_filename=f"{sha}.pdf", doc_type=doc_type,
        lifecycle_status="final", completeness_score=1.0, maturity_score=1.0, page_count=1,
        text_snippet=LEASE_TEXT, doc_date="2024-06-15", full_text=LEASE_TEXT,
    )


def _theme_links(repo, sha):
    cur = repo.conn.cursor()
    cur.execute(
        "SELECT node_id FROM document_entity_links WHERE sha256_hash = ? AND role = ?;",
        (sha, THEME_RELATION),
    )
    return [r[0] for r in cur.fetchall()]


def test_resolver_walks_to_taxonomy_root():
    r = ThemeResolver()
    assert r.resolve("lease_contract") == ("legal_contract", "Contracts & Legal Agreements")
    assert r.resolve("Lease Contract")[0] == "legal_contract"          # normalized
    assert r.resolve("financial_banking")[0] == "financial_banking"    # root maps to itself
    assert r.resolve("career_cv")[0] == "career_research"
    assert r.resolve("technical_manual") == ("unclassified", "Unclassified")
    assert r.resolve("") is None and r.resolve(None) is None and r.resolve("other") is None


def test_resolver_survives_cyclic_hierarchy():
    r = ThemeResolver(loader=lambda: {"a": ("b", "A"), "b": ("a", "B")})
    assert r.resolve("a")[0] in {"a", "b"}


def test_extractor_attaches_theme_without_breaking_entities():
    g = KnowledgeGraphExtractor(provider="mock").extract_knowledge_graph(
        text=LEASE_TEXT, sha256_hash="sha_lease", filename="lease.pdf", doc_type="lease_contract",
    )
    themes = [n for n in g.nodes if n.node_type == THEME_NODE_TYPE]
    assert [t.node_id for t in themes] == ["theme_legal_contract"]
    assert themes[0].properties["taxonomy_root"] == "legal_contract"

    assert any(l.node_id == "theme_legal_contract" and l.role == THEME_RELATION for l in g.links)
    assert any(
        e.source_id == "contract_type_lease_contract" and e.target_id == "theme_legal_contract"
        and e.relation_type == THEME_RELATION for e in g.edges
    )
    # Existing entity extraction is intact
    types = {n.node_type for n in g.nodes}
    assert {"organization", "location", "currency", "financial_pillar", "statute"} <= types


def test_attach_theme_is_idempotent():
    ext = KnowledgeGraphExtractor(provider="mock")
    g = ext.extract_knowledge_graph(LEASE_TEXT, "sha_idem", "x.pdf", "lease_contract")
    counts = (len(g.nodes), len(g.edges), len(g.links))
    ext.attach_theme(g, "lease_contract")
    assert (len(g.nodes), len(g.edges), len(g.links)) == counts


def test_no_theme_for_empty_doc_type():
    g = KnowledgeGraphExtractor(provider="mock").extract_knowledge_graph(LEASE_TEXT, "sha_none", "x.pdf", "")
    assert not any(n.node_type == THEME_NODE_TYPE for n in g.nodes)


def test_persist_and_reclassify_keeps_single_theme(tmp_path):
    repo = _repo(tmp_path)
    store = PropertyGraphStore(repository=repo)
    ext = KnowledgeGraphExtractor(
        provider="mock",
        theme_resolver=ThemeResolver(loader=make_db_taxonomy_loader(repo.conn, repo._lock)),
    )
    sha = "sha_reclassify"
    _add_doc(repo, sha, "lease_contract")

    # FK-safe persistence (edge endpoints are both knowledge_nodes)
    store.save_document_graph(ext.extract_knowledge_graph(LEASE_TEXT, sha, "a.pdf", "lease_contract"))
    assert _theme_links(repo, sha) == ["theme_legal_contract"]

    # Taxonomy evolution re-enqueues the doc with a new doc_type -> theme moves, no stale link
    store.save_document_graph(ext.extract_knowledge_graph(LEASE_TEXT, sha, "a.pdf", "financial_banking"))
    assert _theme_links(repo, sha) == ["theme_financial_banking"]

    cur = repo.conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM knowledge_edges WHERE source_id = ? AND target_id = ? AND relation_type = ?;",
        ("document_category_financial_banking", "theme_financial_banking", THEME_RELATION),
    )
    assert cur.fetchone()[0] == 1


def test_backfill_themes_existing_documents(tmp_path):
    repo = _repo(tmp_path)
    store = PropertyGraphStore(repository=repo)
    _add_doc(repo, "sha_b1", "lease_contract")
    _add_doc(repo, "sha_b2", "employment_contract")
    _add_doc(repo, "sha_b3", "career_cv")
    _add_doc(repo, "sha_b4", "")

    result = store.backfill_theme_links()

    assert result["documents_examined"] == 4
    assert result["documents_themed"] == 3
    assert result["theme_distribution"] == {"theme_legal_contract": 2, "theme_career_research": 1}
    assert _theme_links(repo, "sha_b2") == ["theme_legal_contract"]
    assert _theme_links(repo, "sha_b4") == []

    # Re-running is a no-op (idempotent)
    store.backfill_theme_links()
    assert _theme_links(repo, "sha_b1") == ["theme_legal_contract"]


def test_3d_knowledge_universe_thematic_layout(tmp_path):
    repo = _repo(tmp_path)
    store = PropertyGraphStore(repository=repo)
    ext = KnowledgeGraphExtractor(provider="mock")

    sha = "sha_lease_3d_test_12345678"
    _add_doc(repo, sha, "lease_contract")

    # Ingest document graph
    doc_graph = ext.extract_knowledge_graph(LEASE_TEXT, sha, "lease_zurich.pdf", "lease_contract")
    store.save_document_graph(doc_graph)

    # 1. Test Thematic Layout
    thematic_res = store.get_3d_knowledge_universe(limit=100, layout="thematic")
    assert thematic_res["layout"] == "thematic"
    assert "Life-Style Domains & Thematic Hubs" in [c["name"] for c in thematic_res["clusters"]]

    # Cluster 6 should be present
    cluster_6 = next(c for c in thematic_res["clusters"] if c["id"] == 6)
    assert cluster_6["archetype"] == "Themes"
    assert cluster_6["color"] == "#ec4899"

    node_ids = {n["id"] for n in thematic_res["nodes"]}
    assert "theme_legal_contract" in node_ids

    # Theme node check
    theme_node = next(n for n in thematic_res["nodes"] if n["id"] == "theme_legal_contract")
    assert theme_node["cluster"] == 6
    assert theme_node["is_hub"] is True
    assert theme_node["type"] == "theme"
    assert theme_node["size"] >= 6.0

    # Document node check (Planet orbiting Sun)
    doc_nodes = [n for n in thematic_res["nodes"] if n["type"] == "document"]
    assert len(doc_nodes) >= 1
    doc_node = doc_nodes[0]
    assert doc_node["theme_id"] == "theme_legal_contract"

    # Edge check: CATEGORIZED_AS edge connects document to theme
    edges = thematic_res["edges"]
    cat_edges = [
        e for e in edges
        if e["relation"] == THEME_RELATION and e["target"] == "theme_legal_contract"
    ]
    assert len(cat_edges) >= 1

    # 2. Test Spatial Layout also has cluster 6 and theme nodes
    spatial_res = store.get_3d_knowledge_universe(limit=100, layout="spatial")
    assert spatial_res["layout"] == "spatial"
    assert any(n["type"] == "theme" for n in spatial_res["nodes"])
    assert any(c["id"] == 6 for c in spatial_res["clusters"])


def test_sidecar_api_graph_3d_thematic_layout():
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    app = create_app()
    client = TestClient(app)

    # Query with layout=thematic
    res = client.get("/api/v1/sidecar/graph-3d?layout=thematic&limit=50")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["layout"] == "thematic"
    assert "clusters" in data
    assert any(c["id"] == 6 for c in data["clusters"])

    # Query with default layout
    res_default = client.get("/api/v1/sidecar/graph-3d?limit=50")
    assert res_default.status_code == 200
    assert res_default.json()["layout"] == "spatial"


def test_sidecar_api_theme_backfill():
    from fastapi.testclient import TestClient
    from backend.api.app import create_app
    app = create_app()
    client = TestClient(app)

    res = client.post("/api/v1/sidecar/theme-backfill")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "documents_examined" in data
    assert "documents_themed" in data

