import sys
sys.path.insert(0, r"c:\Dev\RepoScroller")

from backend.ledger.graph_store import PropertyGraphStore

gs = PropertyGraphStore()

res = gs.get_3d_knowledge_universe(filters={"theme": "Court Order"})
docs = [n for n in res["nodes"] if n.get("type") == "document"]
court_docs = [n for n in docs if any(k in n["name"].lower() for k in ["urteil", "obergericht", "bundesgericht", "court", "richter", "scheidung", "entscheid"])]

print(f"theme='Court Order' => Total nodes: {len(res['nodes'])}, Doc nodes: {len(docs)}, Court/Urteil docs: {len(court_docs)}", flush=True)
for d in court_docs[:5]:
    print(f"   • {d['name']} ({d.get('latest_date')})", flush=True)

res2 = gs.get_3d_knowledge_universe(filters={"q": "urteil"})
docs2 = [n for n in res2["nodes"] if n.get("type") == "document"]
print(f"\nq='urteil' => Total nodes: {len(res2['nodes'])}, Doc nodes: {len(docs2)}", flush=True)
for d in docs2[:5]:
    print(f"   • {d['name']} ({d.get('latest_date')})", flush=True)
