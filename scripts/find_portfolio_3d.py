import sqlite3
from backend.ledger.db import get_db_connection
from backend.ledger.repository import DocumentRepository
from backend.ledger.graph_store import PropertyGraphStore

conn = get_db_connection()
repo = DocumentRepository(conn=conn)
store = PropertyGraphStore(repository=repo)

res = store.get_3d_knowledge_universe(layout="thematic", limit=500)
nodes = res["nodes"]

print("=== NODES IN 3D GRAPH WITH 'Portfolio' IN NAME ===")
for n in nodes:
    if "portfolio" in n["name"].lower():
        print(f"  ID: {n['id']}, Name: {n['name']}, Type: {n['type']}, Degree: {n['degree']}, DocCount: {n['doc_count']}, Coordinates: [{n['x']}, {n['y']}, {n['z']}]")
