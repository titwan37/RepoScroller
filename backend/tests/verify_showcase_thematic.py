import os
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.ledger.repository import DocumentRepository
from backend.ledger.graph_store import PropertyGraphStore
from backend.api.app import create_app
import backend.ledger.db as db_mod

def run_verification():
    db_file = Path("backend/data/reposcroller_showcase.db").resolve()
    print(f"[*] Verifying showcase database: {db_file} ({db_file.stat().st_size / (1024**2):.2f} MB)")

    # 1. Direct Store Verification
    repo = DocumentRepository(db_path=db_file)
    store = PropertyGraphStore(repository=repo)

    spatial_res = store.get_3d_knowledge_universe(layout="spatial", limit=500)
    print(f"[+] Spatial View: {len(spatial_res['nodes'])} nodes, {len(spatial_res['edges'])} edges")

    thematic_res = store.get_3d_knowledge_universe(layout="thematic", limit=500)
    print(f"[+] Thematic Mindmap: {len(thematic_res['nodes'])} nodes, {len(thematic_res['edges'])} edges")
    
    print("[*] Thematic Clusters in Showcase Slice:")
    for c in thematic_res["clusters"]:
        c_id = c["id"]
        c_name = c["name"]
        rendered = len([n for n in thematic_res["nodes"] if n["cluster"] == c_id])
        total = c.get("total_in_db", 0)
        print(f"    Cluster [{c_id}] {c_name}: {rendered} rendered (total in showcase db: {total})")

    # Verify Sun Hubs
    hubs = [n for n in thematic_res["nodes"] if n.get("type") == "theme"]
    print(f"[+] Thematic Sun Hubs: {len(hubs)} / 11 present")
    assert len(hubs) == 11, f"Expected 11 theme hubs, got {len(hubs)}"
    for h in hubs:
        print(f"      Sun: {h['id']} ({h['name']}) -> {h.get('doc_count', 0)} orbiting documents")

    # Verify Orbiting Planets
    docs = [n for n in thematic_res["nodes"] if n.get("type") == "document"]
    print(f"[+] Document Planets: {len(docs)} orbiting documents present")
    assert len(docs) > 0, "Expected at least 1 document planet"
    
    # 2. HTTP API Verification with simulated fallback
    print("\n[*] Testing HTTP API with showcase slice fallback...")
    def mock_resolve(path=None):
        return db_file

    with patch.object(db_mod, "resolve_ledger_db_path", mock_resolve):
        with patch("backend.ledger.repository.resolve_ledger_db_path", mock_resolve):
            app = create_app()
            client = TestClient(app)
            
            # Fetch thematic layout from API
            res = client.get("/api/v1/sidecar/graph-3d?layout=thematic&limit=250")
            assert res.status_code == 200, f"API returned status {res.status_code}"
            data = res.json()
            assert data["status"] == "success"
            assert data["layout"] == "thematic"
            assert len(data["nodes"]) > 0
            
            api_hubs = [n for n in data["nodes"] if n.get("type") == "theme"]
            print(f"[+] API /api/v1/sidecar/graph-3d returned {len(data['nodes'])} nodes with {len(api_hubs)} thematic hubs.")
            assert len(api_hubs) == 11, f"Expected 11 theme hubs from API, got {len(api_hubs)}"

    print("\n[SUCCESS] Thematic Mindmap is resilient, stable, and verified with reposcroller_showcase.db!")

if __name__ == "__main__":
    run_verification()
