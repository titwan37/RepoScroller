import sqlite3
from collections import Counter
import re
from backend.ledger.db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

print("=== SAMPLE CANONICAL FILENAMES ===")
cur.execute("SELECT canonical_filename FROM document_ledger LIMIT 15")
for row in cur.fetchall():
    print(" ", row[0])

print("\n=== CLUSTERING 'other' DOCUMENTS (5752 total) ===")
cur.execute("SELECT canonical_filename, text_snippet FROM document_ledger WHERE doc_type = 'other'")
other_docs = cur.fetchall()

keywords_counter = Counter()
bank_keywords = ["banque", "bank", "konto", "postfinance", "bcv", "ubs", "credit suisse", "iban", "kontoauszug", "relevé"]
insurance_keywords = ["assurance", "versicherung", "axa", "allianz", "helvetia", "groupe mutuel", "swica", "suva", "police", "versicherungs"]
tax_keywords = ["steuer", "impot", "tax", "steuern", "déclaration"]
admin_keywords = ["attestation", "notification", "confirmation", "certificat", "bestätigung", "kündigung", "resiliation"]
medical_keywords = ["arzt", "medecin", "ordonnance", "rezept", "krankenkasse", "spital", "hopital", "gesundheit", "caisse-maladie"]
pension_keywords = ["lpp", "bvg", "avs", "ahv", "prevoyance", "vorsorge", "pension"]
utility_keywords = ["swisscom", "salt", "sunrise", "strom", "electricite", "sig", "gaz", "bill", "facture"]

category_matches = Counter()

for fn, snip in other_docs:
    text = f"{fn} {snip or ''}".lower()
    matched = False
    if any(k in text for k in bank_keywords):
        category_matches["banking_financial"] += 1
        matched = True
    if any(k in text for k in insurance_keywords):
        category_matches["insurance_policy"] += 1
        matched = True
    if any(k in text for k in tax_keywords):
        category_matches["tax_documents"] += 1
        matched = True
    if any(k in text for k in medical_keywords):
        category_matches["healthcare_medical"] += 1
        matched = True
    if any(k in text for k in pension_keywords):
        category_matches["pension_social_security"] += 1
        matched = True
    if any(k in text for k in utility_keywords):
        category_matches["telecom_utility_invoice"] += 1
        matched = True
    if not matched:
        category_matches["unmatched_other"] += 1

print("\nCategory breakdown of 'other' documents:")
for cat, count in category_matches.most_common():
    print(f"  {cat}: {count} ({count/len(other_docs)*100:.1f}%)")

print("\n=== TOP ENTITY LINK TYPES AND NAMES ===")
cur.execute("""
    SELECT e.entity_type, e.name, COUNT(l.document_id) as cnt
    FROM entities e
    JOIN document_entity_links l ON e.entity_id = l.entity_id
    GROUP BY e.entity_id
    ORDER BY cnt DESC
    LIMIT 30
""")
for row in cur.fetchall():
    print(f"  [{row[0]}] {row[1]}: {row[2]} docs")

print("\n=== SAMPLE UNMATCHED 'other' FILENAMES ===")
count = 0
for fn, snip in other_docs:
    text = f"{fn} {snip or ''}".lower()
    if not any(k in text for k in bank_keywords + insurance_keywords + tax_keywords + medical_keywords + pension_keywords + utility_keywords):
        print(f"  {fn} | {(snip or '')[:80].strip()}")
        count += 1
        if count >= 20:
            break
