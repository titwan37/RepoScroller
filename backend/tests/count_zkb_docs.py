import sqlite3
import re

conn = sqlite3.connect('backend/data/reposcroller_ledger.db')
cur = conn.cursor()

# Check documents where canonical_filename or text mentions Zuger Kantonalbank or ZugerKB or ZGKB
pat = re.compile(r'\b(zuger\s+kantonal\s*bank|zugerkb|zgkb)\b', re.IGNORECASE)

cur.execute("SELECT sha256_hash, canonical_filename, text_snippet FROM document_ledger")
docs = cur.fetchall()

matched_shas = set()
for sha, fname, snip in docs:
    if pat.search(fname or "") or pat.search(snip or ""):
        matched_shas.add(sha)

print(f"Matched by filename or snippet: {len(matched_shas)} docs")

# Check chunks as well
cur.execute("SELECT DISTINCT sha256_hash FROM document_chunks WHERE LOWER(chunk_text) LIKE '%zuger%kantonal%' OR LOWER(chunk_text) LIKE '%zugerkb%' OR LOWER(chunk_text) LIKE '%zgkb%'")
chunk_shas = {r[0] for r in cur.fetchall()}
print(f"Matched by chunk_text: {len(chunk_shas)} docs")

all_shas = matched_shas | chunk_shas
print(f"Total unique documents matching Zuger Kantonalbank: {len(all_shas)}")

# Sample matching filenames
for sha in list(all_shas)[:10]:
    cur.execute("SELECT canonical_filename FROM document_ledger WHERE sha256_hash = ?", (sha,))
    print(" -", cur.fetchone()[0])
