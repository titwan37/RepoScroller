from _pytest import python_api
def list_court_decisions():
    import sqlite3; 
    conn = sqlite3.connect('backend/data/reposcroller_ledger.db'); 
    cur = conn.cursor(); 
    cur.execute('SELECT canonical_filename, doc_type, doc_date, reception_date FROM document_ledger WHERE doc_type = \'court_order\' ORDER BY doc_date DESC'); 
    rows = cur.fetchall(); 
    print(f'Total: {len(rows)}'); 
    print([print(r) for r in rows[:10]])


import sqlite3; conn = sqlite3.connect('backend/data/reposcroller_ledger.db'); cur = conn.cursor(); cur.execute('SELECT SUBSTR(doc_date, 1, 4) as yr, COUNT(*) FROM document_ledger WHERE doc_type = \'court_order\' GROUP BY yr ORDER BY yr'); print(cur.fetchall())

from backend.ledger.graph_store import PropertyGraphStore; gs = PropertyGraphStore(); res = gs.get_3d_knowledge_universe(layout='timeline', filters={'type': 'court_order'}); print('Nodes:', len(res['nodes']), 'Edges:', len(res['edges']), 'Axes:', res['axes']); doc_nodes = [n for n in res['nodes'] if n.get('type') == 'document']; print('Doc nodes:', len(doc_nodes)); print('Sample doc:', doc_nodes[0] if doc_nodes else None)

import sys; from backend.ledger.graph_store import PropertyGraphStore; gs = PropertyGraphStore(); res = gs.get_3d_knowledge_universe(layout='timeline', filters={'type': 'court_order'}); doc_nodes = [n for n in res['nodes'] if n.get('type') == 'document']; dates = [n.get('latest_date') for n in doc_nodes if n.get('latest_date')]; min_d = min(dates) if dates else None; max_d = max(dates) if dates else None; print(f'Doc nodes: {len(doc_nodes)}, Min date: {min_d}, Max date: {max_d}'); recent_docs = [n for n in doc_nodes if n.get('latest_date') and n['latest_date'] >= '2020-01-01']; print(f'Docs in last 6 years (>= 2020): {len(recent_docs)}')

import json; from backend.ledger.graph_store import PropertyGraphStore; gs = PropertyGraphStore(); res = gs.get_3d_knowledge_universe(layout='timeline', filters={'type': 'court_order'}); doc = [n for n in res['nodes'] if n.get('type') == 'document'][0]; print({k: v for k, v in doc.items() if k not in ['cluster_icon']})

import sqlite3; conn = sqlite3.connect('backend/data/reposcroller_ledger.db'); cur = conn.cursor(); cur.execute('SELECT canonical_filename, doc_date, doc_type FROM document_ledger WHERE LOWER(canonical_filename) LIKE \'%obergericht%\' OR LOWER(canonical_filename) LIKE \'%kantonsgericht%\' OR LOWER(canonical_filename) LIKE \'%staatsanwalt%\' OR LOWER(canonical_filename) LIKE \'%urteil%\' ORDER BY doc_date DESC LIMIT 30'); rows = cur.fetchall(); print(f'Found: {len(rows)}'); [print(r) for r in rows[:15]]

import sqlite3; conn = sqlite3.connect('backend/data/reposcroller_ledger.db'); cur = conn.cursor(); cur.execute('SELECT dl.canonical_filename, dl.doc_date, dl.doc_type FROM document_ledger dl WHERE LOWER(dl.canonical_filename) LIKE \'%obergericht%\' ORDER BY dl.doc_date DESC LIMIT 15'); print(cur.fetchall())

def generate_court_order_dossier():
    from backend.ledger.repository import DocumentRepository; 
    from backend.api.routes.dossier import _generate_deterministic_dossier; 
    repo = DocumentRepository(); 
    ctx = repo.get_entity_portrait_context('Court Order'); 
    md = _generate_deterministic_dossier(ctx); 
    print(md[md.find('## 5'):md.find('## 5') + 1600])