from backend.ledger.db import get_db_connection
from collections import Counter

conn = get_db_connection()
cur = conn.cursor()

print("=== CHECKING 'lease_contract' REAL CONTENT ===")
cur.execute("SELECT canonical_filename, text_snippet FROM document_ledger WHERE doc_type = 'lease_contract'")
rows = cur.fetchall()
print(f"Total classified as lease_contract: {len(rows)}")

sample_cnt = 0
suspicious = 0
for fn, snip in rows:
    text = f"{fn} {snip or ''}".lower()
    # Check if it actually mentions rent, mietvertrag, bail, bailleur, locataire, mietzins
    has_lease_terms = any(k in text for k in ["mietvertrag", "bail à loyer", "bail a loyer", "bailleur", "locataire", "mieter", "vermieter", "mietzins", "wohnungsabnahme"])
    if not has_lease_terms:
        suspicious += 1
        if sample_cnt < 15:
            print(f"  Suspicious lease_contract: {fn} | {(snip or '')[:80].strip()}")
            sample_cnt += 1

print(f"\nSuspicious lease_contract count: {suspicious} / {len(rows)} ({suspicious/len(rows)*100:.1f}%)")
