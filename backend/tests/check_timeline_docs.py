import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")

from backend.ledger.graph_store import PropertyGraphStore

gs = PropertyGraphStore()
res = gs.get_3d_knowledge_universe(layout="timeline")

doc_nodes = [n for n in res["nodes"] if n.get("node_type") == "document"]
print(f"Total nodes in timeline: {len(res['nodes'])}, doc nodes: {len(doc_nodes)}")

court_docs = [n for n in doc_nodes if any(k in n["name"].lower() for k in ["urteil", "obergericht", "bundesgericht", "court"])]
print(f"Court/Urteil docs in timeline: {len(court_docs)}")
for n in court_docs[:10]:
    print(" -", n["name"])

# Also check by doc_type in properties_json
court_order_docs = [n for n in doc_nodes if "court_order" in n.get("properties_json", "")]
print(f"Docs with doc_type court_order in timeline: {len(court_order_docs)}")
