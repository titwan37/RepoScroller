import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")

from backend.ledger.graph_store import PropertyGraphStore
from collections import Counter

gs = PropertyGraphStore()
res = gs.get_3d_knowledge_universe(layout="timeline")

types = Counter(n.get("type") for n in res["nodes"])
print("Actual node types in timeline:", types)

doc_nodes = [n for n in res["nodes"] if n.get("type") == "document"]
print(f"Total doc nodes: {len(doc_nodes)}")
court_docs = [n for n in doc_nodes if any(k in n["name"].lower() for k in ["urteil", "obergericht", "bundesgericht", "court"])]
print(f"Court docs in timeline: {len(court_docs)}")
for n in court_docs[:10]:
    print(" -", n["name"])
