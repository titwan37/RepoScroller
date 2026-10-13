import os
import shutil
import sqlite3
import time
from collections import Counter
from pathlib import Path
from backend.ai.taxonomy import TaxonomyManager, TaxonomyEvolutionEngine
from backend.ledger.db import get_db_connection, resolve_ledger_db_path

db_path = resolve_ledger_db_path()
print(f"Target Database: {db_path}")

# Step 1: Create snapshot backup
backup_path = db_path.with_name(f"{db_path.name}.bak_v1.1.0")
print(f"Creating backup: {backup_path} ...")
shutil.copy2(db_path, backup_path)
print(f"Backup successfully created ({backup_path.stat().st_size / (1024*1024):.2f} MB).\n")

# Step 2: Initialize Taxonomy Manager and sync skill
conn = get_db_connection()
mgr = TaxonomyManager(db_conn=conn)
sync_info = mgr.sync_from_skill()
print(f"Taxonomy Skill Sync: Version {sync_info['version']} ({sync_info['status']}) - {sync_info['categories_synced']} categories.\n")

engine = TaxonomyEvolutionEngine(taxonomy_manager=mgr)
cur = conn.cursor()

# Step 3: Run in-place evolution across all documents
print("Scanning document ledger for taxonomy v1.1.0 migration...")
cur.execute("""
    SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.text_snippet,
           COALESCE(dl.taxonomy_version, 'v0.9.0') as current_tax_ver,
           fl.relative_path, fl.storage_root
    FROM document_ledger dl
    LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
    GROUP BY dl.sha256_hash
""")
all_docs = [dict(r) for r in cur.fetchall()]
total_docs = len(all_docs)
print(f"Loaded {total_docs} documents for classification evaluation.\n")

t0 = time.time()
updates = []
reclassifications = Counter()
old_categories = Counter()

for doc in all_docs:
    sha = doc["sha256_hash"]
    old_cat = doc.get("doc_type") or "other"
    old_categories[old_cat] += 1
    new_cat, rule, conf = engine.evaluate_document_reclassification(doc)
    
    if new_cat != old_cat:
        reclassifications[(old_cat, new_cat)] += 1
        updates.append((new_cat, "v1.1.0", sha, old_cat, rule))
    else:
        # Just update taxonomy version stamp to v1.1.0 if not already
        if doc.get("current_tax_ver") != "v1.1.0":
            updates.append((old_cat, "v1.1.0", sha, old_cat, "Unchanged Baseline"))

print(f"Evaluated {total_docs} documents in {time.time() - t0:.2f}s.")
print(f"Total documents with reclassified doc_type: {sum(c for (o, n), c in reclassifications.items())}")
print(f"Total records to stamp with v1.1.0: {len(updates)}\n")

# Step 4: Batch Execute in a Single Transaction
print("Applying in-place database transaction...")
cur.execute("BEGIN TRANSACTION;")
try:
    # 1. Update document ledger in bulk
    cur.executemany("""
        UPDATE document_ledger
        SET doc_type = ?, taxonomy_version = ?
        WHERE sha256_hash = ?;
    """, [(u[0], u[1], u[2]) for u in updates])

    # 2. Write audit log entries for meaningful reclassifications
    audit_entries = []
    for u in updates:
        new_cat, _, sha, old_cat, rule = u
        if new_cat != old_cat:
            details = f"Taxonomy v1.1.0: reclassified from '{old_cat}' to '{new_cat}' via {rule}"
            audit_entries.append((sha, "taxonomy_reclassified", details, "TaxonomyEvolutionEngine-v1.1.0"))

    if audit_entries:
        cur.executemany("""
            INSERT INTO audit_log (sha256_hash, action, details, actor)
            VALUES (?, ?, ?, ?);
        """, audit_entries)

    # 3. Update global_taxonomy document_count
    cur.execute("""
        UPDATE global_taxonomy
        SET document_count = (
            SELECT COUNT(*) FROM document_ledger dl WHERE dl.doc_type = global_taxonomy.category_id
        );
    """)

    conn.commit()
    print("Database transaction successfully committed!\n")
except Exception as e:
    conn.rollback()
    print(f"Error during migration! Rolled back. Details: {e}")
    raise

# Step 5: Post-migration verification
print("============================================================")
print("FINAL POST-MIGRATION CATEGORY BREAKDOWN (document_ledger)")
print("============================================================")
cur.execute("""
    SELECT doc_type, COUNT(*) as cnt
    FROM document_ledger
    GROUP BY doc_type
    ORDER BY cnt DESC;
""")
post_categories = cur.fetchall()
for row in post_categories:
    pct = row[1] / total_docs * 100
    print(f"  {row[0]:<28}: {row[1]:>5} ({pct:>5.1f}%)")

print("\n============================================================")
print("TAXONOMY VERSION DISTRIBUTION")
print("============================================================")
cur.execute("""
    SELECT taxonomy_version, COUNT(*) as cnt
    FROM document_ledger
    GROUP BY taxonomy_version
    ORDER BY cnt DESC;
""")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

print("\n============================================================")
print("TOP MIGRATION TRANSITIONS")
print("============================================================")
for (old_c, new_c), cnt in reclassifications.most_common(15):
    print(f"  {old_c} -> {new_c}: {cnt}")
