from backend.ledger.graph_store import PropertyGraphStore
from backend.ledger.repository import DocumentRepository

repo = DocumentRepository()
gs = PropertyGraphStore(repo)

res = gs.get_3d_knowledge_universe(limit=200, filters={"location": "zurich"})
print("Current nodes count:", len(res["nodes"]))
print("Current edges count:", len(res["edges"]))
print("Node names:", [n["name"] for n in res["nodes"]])
