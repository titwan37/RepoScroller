import re
import sqlite3
from typing import Dict, Any, Optional, Tuple, List

def evaluate_self_driven_classification(doc: Dict[str, Any]) -> Tuple[str, str, float]:
    fn = (doc.get("canonical_filename") or "").lower()
    path = (doc.get("relative_path") or "").lower()
    abs_path = (doc.get("absolute_path") or "").lower()
    snippet = (doc.get("text_snippet") or "").lower()
    combined = f"{fn} {path} {abs_path} {snippet}"
    old_cat = doc.get("doc_type") or "other"

    # 1. IMMEDIATE FOLDER ANCESTRY EXTRACTION
    raw_path = (abs_path or path or "").replace("\\", "/").strip()
    parts = [p.strip() for p in raw_path.split("/") if p.strip()]
    dir_ancestors = list(reversed(parts[:-1])) if len(parts) > 1 else []
    leaf_folder = dir_ancestors[0] if dir_ancestors else ""
    parent_folder = dir_ancestors[1] if len(dir_ancestors) > 1 else ""

    # -------------------------------------------------------------
    # LEVEL A: EXPLICIT STRONG FORM-FACTOR FILENAME PATTERNS
    # -------------------------------------------------------------
    # A.1. Portfolio Booklet
    if any(k in fn for k in ["portfolio-booklet", "portfolio_booklet", "portfolio booklet", "arbeitsproben"]) or \
       (leaf_folder and "portfolio" in leaf_folder and not any(k in fn for k in ["jobdescription", "application_letter", "coverletter", "cover_letter"])):
        return "career_portfolio", f"Self-Driven Ancestry (folder '{leaf_folder}' + portfolio booklet)", 0.98

    # A.2. CV & Lebenslauf
    is_reference = any(k in fn for k in ["certificat de travail", "arbeitszeugnis", "arbeitsbestätigung", "reference letter", "reference_letter"])
    if not is_reference and (
        re.search(r'(?:^|[^a-z0-9])(cv|curriculum[\s_-]*vitae|lebenslauf|resume)(?:[^a-z0-9]|$)', fn) or
        any(k in fn for k in ["_cv_", "-cv-", "_cv.", "-cv.", "cv_", "cv-", "lebenslauf", "curriculum_vitae", "curriculum-vitae"]) or
        (leaf_folder and any(cv_k in leaf_folder for cv_k in ["2025-cv", "2026-cv", "cv2015", "cv2014", "2019cv", "2020cv", "2018-cv", "cv-2019", "cv_masters", "cv_tailored"]) and not any(k in fn for k in ["jobdescription", "application_letter", "coverletter", "cover_letter", "stellenbeschreib"]))
    ):
        return "career_cv", f"Self-Driven Ancestry (folder '{leaf_folder}' + CV)", 0.98

    # A.3. Explicit Job Description & _JP.pdf
    if fn.endswith("_jp.pdf") or fn.endswith("-jp.pdf") or "_jp." in fn or "-jp." in fn or \
       any(k in fn for k in ["jobdescription", "job_description", "job-description", "stellenbeschreibung", "stellenausschreibung", "stelleninserat", "fiche de poste", "fiche_de_poste"]) or \
       "job details:----------job_title:" in snippet or \
       (leaf_folder and any(p_k in leaf_folder for p_k in ["2025-positions", "job-descriptions", "job-profiles", "positions"]) and not any(k in fn for k in ["coverletter", "cover_letter", "application_letter", "lebenslauf"])):
        return "career_job_description", f"Self-Driven Ancestry (folder '{leaf_folder}' + Job Vacancy)", 0.98

    # A.4. Cover Letter & Letter of Motivation
    if any(k in fn for k in ["coverletter", "cover_letter", "cover letter", "motivationsschreiben", "bewerbungsschreiben", "application_letter", "lettre de motivation", "lettre_de_motivation"]) or \
       (leaf_folder and any(lm_k in leaf_folder for lm_k in ["2025-lm", "lm", "motivation_letter"]) and not any(k in fn for k in ["jobdescription", "stellenbeschreib", "_jp.pdf"])):
        return "career_cover_letter", f"Self-Driven Ancestry (folder '{leaf_folder}' + Motivation Letter)", 0.95

    # A.5. Legislation & Official Codes (Fedlex)
    if any(k in fn for k in ["fedlex", "fedlex-data-admin", "ro-20", "rs-20", "rs-10", "rs-0."]) or \
       (leaf_folder and "fedlex" in leaf_folder):
        return "statute_legislation", f"Self-Driven Ancestry (folder '{leaf_folder}' + Fedlex)", 0.98

    # A.6. Banking & Financial Statements
    if fn.startswith("cre_p_") or "_kontoauszug" in fn or "kontoauszug" in fn or "bankauszug" in fn or "zinsausweis" in fn or \
       (leaf_folder and any(b_k in leaf_folder for b_k in ["postfinance", "zugerkantonalbank", "releve", "kontoauszug", "bankauszug", "cre_p_"])):
        return "financial_banking", f"Self-Driven Ancestry (folder '{leaf_folder}' + Banking)", 0.96

    # A.7. Insurance Policies
    if (leaf_folder and any(ins_k in leaf_folder for ins_k in ["helsana", "assura", "groupemutuel", "swica", "krankenkasse", "cap_rechtsschutz"])) or \
       (any(ins in combined for ins in ["helsana", "axa", "allianz", "swica", "suva", "groupe mutuel", "zurich versicherung", "sanitas", "css versicherung"]) and
        any(term in combined for term in ["police", "versicherungspolice", "assurance combinée", "versicherungsschein", "deckungsnachweis", "police d'assurance", "krankenkasse", "versicherungsvertrag"])):
        return "insurance_policy", f"Self-Driven Ancestry (folder '{leaf_folder}' + Insurance)", 0.95

    # A.8. Administrative Decisions
    if (leaf_folder and any(adm_k in leaf_folder for adm_k in ["strassenverkehrsamt", "auto_polizei", "einwohnerkontrolle", "ausweisung"])) or \
       (any(auth in combined for auth in ["strassenverkehrsamt", "kantonspolizei", "einwohnerkontrolle", "sva zürich"]) and
        any(term in combined for term in ["verfügung", "fahrzeug", "führerausweis", "decision", "décision", "immatriculation"])):
        return "administrative_order", f"Self-Driven Ancestry (folder '{leaf_folder}' + Admin Order)", 0.94

    # A.9. Tax Assessments
    if (leaf_folder and any(tx_k in leaf_folder for tx_k in ["steuern", "taxation", "steuererklaerung"])) or \
       (any(k in fn for k in ["steuerausweis", "steuererklärung", "steuerveranlagung", "tax_return", "bordereau fiscal"]) and "steuer" in combined):
        return "tax_assessment", f"Self-Driven Ancestry (folder '{leaf_folder}' + Tax)", 0.95

    # A.10. Technical Reference Books
    if any(k in fn for k in ["big book", "big-book", "vocabulary", "handbook", "textbook"]) or \
       fn.startswith("p1 vocabulary") or fn.startswith("p1u") or fn.startswith("n2p2"):
        return "technical_reference", "Self-Driven Form Factor (Technical Reference)", 0.92

    # A.11. Professional Profile
    if any(k in fn for k in ["profil", "profile", "executive_bio", "kurzprofil"]) and \
       (leaf_folder and "profile" in leaf_folder or "linkedin" in combined) and \
       not re.search(r'\b(cv|curriculum)\b', fn):
        return "career_profile", "Self-Driven Form Factor (Profile)", 0.90

    # A.12. Strict Guardrail for Tenancy & Lease Contracts (False Positive Removal)
    if old_cat == "lease_contract":
        has_lease_terms = any(k in combined for k in [
            "mietvertrag", "geschäftsmietvertrag", "wohnungsmietvertrag", "mietzins", "mieter", "vermieter",
            "wohnungsabnahme", "bail à loyer", "bail a loyer", "contrat de bail", "bailleur", "locataire",
            "loyer mensuel", "état des lieux", "tenancy agreement"
        ])
        if not has_lease_terms:
            if fn.endswith("_ingestionreport.md") or "ingestion audit" in combined or fn.endswith(".md"):
                return "technical_architecture", "Lease Guardrail -> Technical Doc", 0.90
            return "other", "Lease Guardrail - False Positive Removal", 0.85

    return old_cat, "Unchanged Baseline", 0.70

if __name__ == "__main__":
    conn = sqlite3.connect("backend/data/reposcroller_ledger.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.text_snippet,
               fl.relative_path, fl.absolute_path
        FROM document_ledger dl
        LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
        GROUP BY dl.sha256_hash;
    """)
    rows = [dict(zip([col[0] for col in cur.description], r)) for r in cur.fetchall()]
    print(f"Total documents scanned: {len(rows)}")

    cat_counts = {}
    reclassified = {}
    portfolio_docs = []

    for doc in rows:
        target_cat, rule, weight = evaluate_self_driven_classification(doc)
        cat_counts[target_cat] = cat_counts.get(target_cat, 0) + 1
        if target_cat == "career_portfolio":
            portfolio_docs.append((doc["canonical_filename"], doc["doc_type"], rule))
        if target_cat != doc["doc_type"]:
            pair = f"{doc['doc_type']} -> {target_cat}"
            reclassified[pair] = reclassified.get(pair, 0) + 1

    print(f"\nTotal Portfolio Documents Result: {len(portfolio_docs)}")
    print("\nPortfolio Documents Sample:")
    for fn, old, rule in portfolio_docs[:15]:
        print(f"  [{old} -> portfolio] {fn[:60]}... ({rule})")

    print("\nTop 20 Category Reclassifications:")
    for pair, cnt in sorted(reclassified.items(), key=lambda x: x[1], reverse=True)[:20]:
        print(f"  {pair}: {cnt}")

    print("\nFinal Proposed Category Breakdown:")
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat}: {cnt}")
