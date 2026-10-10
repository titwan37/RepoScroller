import sqlite3
from collections import Counter
from backend.ai.taxonomy import TaxonomyManager, TaxonomyEvolutionEngine
from backend.ledger.db import get_db_connection

conn = get_db_connection()
mgr = TaxonomyManager(db_conn=conn)

# 1. Sync the skill file to ensure database registry is up to date
sync_info = mgr.sync_from_skill()
print(f"=== TAXONOMY SYNC ===")
print(f"Version: {sync_info['version']}, Status: {sync_info['status']}, Categories: {sync_info['categories_synced']}\n")

engine = TaxonomyEvolutionEngine(taxonomy_manager=mgr)
cur = conn.cursor()

# Query all documents with their paths
print("=== DRY-RUN EVALUATION: 'other' and 'lease_contract' ===")
cur.execute("""
    SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.text_snippet,
           fl.relative_path, fl.storage_root
    FROM document_ledger dl
    LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
    WHERE dl.doc_type IN ('other', 'lease_contract')
    GROUP BY dl.sha256_hash
""")
docs = [dict(r) for r in cur.fetchall()]
print(f"Loaded {len(docs)} documents to evaluate.\n")

other_transitions = Counter()
lease_transitions = Counter()
other_samples = {}
lease_samples = {}

for d in docs:
    old_cat = d["doc_type"]
    new_cat, rule, conf = engine.evaluate_document_reclassification(d)
    
    if old_cat == "other":
        other_transitions[new_cat] += 1
        if new_cat not in other_samples and new_cat != "other":
            other_samples[new_cat] = (d["canonical_filename"], rule, conf)
    elif old_cat == "lease_contract":
        lease_transitions[new_cat] += 1
        if new_cat not in lease_samples and new_cat != "lease_contract":
            lease_samples[new_cat] = (d["canonical_filename"], rule, conf)

print("------------------------------------------------------------")
print(f"RECLASSIFICATION OF 'other' (Total: {sum(other_transitions.values())}):")
print("------------------------------------------------------------")
for cat, cnt in other_transitions.most_common():
    pct = cnt / sum(other_transitions.values()) * 100
    print(f"  -> {cat:<24}: {cnt:>5} ({pct:>5.1f}%)")

print("\nSamples reclaimed from 'other':")
for cat, (fn, rule, conf) in other_samples.items():
    print(f"  [{cat}] {fn[:55]} (rule: {rule}, conf: {conf:.2f})")

print("\n------------------------------------------------------------")
print(f"RECLASSIFICATION OF 'lease_contract' (Total: {sum(lease_transitions.values())}):")
print("------------------------------------------------------------")
for cat, cnt in lease_transitions.most_common():
    pct = cnt / sum(lease_transitions.values()) * 100
    print(f"  -> {cat:<24}: {cnt:>5} ({pct:>5.1f}%)")

print("\nSamples reclaimed from 'lease_contract':")
for cat, (fn, rule, conf) in lease_samples.items():
    print(f"  [{cat}] {fn[:55]} (rule: {rule}, conf: {conf:.2f})")

print("\n------------------------------------------------------------")
reclaimed_other = sum(c for k, c in other_transitions.items() if k != "other")
cleaned_lease = sum(c for k, c in lease_transitions.items() if k != "lease_contract")
print(f"SUMMARY:")
print(f"  - Documents reclaimed from 'other': {reclaimed_other} / {sum(other_transitions.values())} ({reclaimed_other/sum(other_transitions.values())*100:.1f}%)")
print(f"  - False positives removed from 'lease_contract': {cleaned_lease} / {sum(lease_transitions.values())} ({cleaned_lease/sum(lease_transitions.values())*100:.1f}%)")
print(f"  - True verified lease contracts retained: {lease_transitions.get('lease_contract', 0)}")
print("------------------------------------------------------------")
