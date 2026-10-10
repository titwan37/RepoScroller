import re
import sqlite3
from typing import Dict, Any, Optional, Tuple, List

FOLDER_CATEGORY_RULES: List[Tuple[str, List[str], List[str]]] = [
    # (category_id, positive_patterns, negative_patterns)
    (
        "career_portfolio",
        ["portfolio", "portfolios", "arbeitsproben", "work-samples", "case-studies", "casestudies", "projektdokumentation"],
        ["investment-portfolio", "share-portfolio"]
    ),
    (
        "career_cv",
        ["cv", "cvs", "2025-cv", "2026-cv", "2019cv", "2020cv", "cv2015", "cv2014", "cv2009", "2018-cv", "cv-2019", "lebenslauf", "resume", "resumes", "curriculum"],
        ["jobdescription", "position", "lm", "cover_letter"]
    ),
    (
        "career_cover_letter",
        ["lm", "2025-lm", "lettre-de-motivation", "lettre_de_motivation", "lettres_de_motivation", "motivationsschreiben", "cover-letters", "coverletter", "candidature", "candidatures", "motivation_letter"],
        []
    ),
    (
        "career_job_description",
        ["positions", "2025-positions", "job-descriptions", "jobdescriptions", "job-profiles", "stellen", "stelleninserate", "stellenausschreibungen", "vacancies"],
        []
    ),
    (
        "career_profile",
        ["2026-profile", "kurzprofil", "kurzprofile", "executive-bio"],
        ["job-profiles"]
    ),
    (
        "financial_banking",
        ["postfinance", "zugerkantonalbank", "zkb", "kantonalbank", "banquepostale", "releve", "bankauszug", "kontoauszug", "cre_p_confirmationpayment", "rep_p_extrait_de_compte", "dep_p_fonds", "mastercardworld"],
        []
    ),
    (
        "financial_invoice",
        ["invoices", "rechnungen", "factures", "accounting", "buchhaltung", "quittungen", "receipts", "telecom", "sunrise", "salt", "wwz"],
        []
    ),
    (
        "insurance_policy",
        ["helsana", "assura", "groupemutuel", "swica", "axa", "allianz", "suva", "krankenkasse", "cap_rechtsschutz"],
        []
    ),
    (
        "tax_assessment",
        ["steuern", "steuererklaerung", "steuern2011", "steuern2013", "shareddocument-steuern", "taxation"],
        []
    ),
    (
        "statute_legislation",
        ["fedlex", "rechtssammlung", "erlasse", "systematische-rechtssammlung"],
        []
    ),
    (
        "administrative_order",
        ["strassenverkehrsamt", "auto_polizei", "einwohnerkontrolle", "sva", "ausweisung"],
        []
    ),
]

GENERIC_FOLDERS = {
    "scandepot", "pdf", "docs", "doc", "downloads", "temp", "tmp", "my drive", "shared",
    "archives", "saved from chrome", "run_260909", "2025_uncategorized", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"
}

def resolve_nearest_folder_category(relative_path: str, absolute_path: str = "") -> Optional[Tuple[str, str, float]]:
    # Prefer absolute_path as it contains full folder hierarchy
    raw_path = (absolute_path or relative_path or "").replace("\\", "/").strip()
    if not raw_path:
        return None
    
    parts = [p.strip().lower() for p in raw_path.split("/") if p.strip()]
    if len(parts) <= 1:
        return None
    
    # Exclude filename, traverse from immediate parent (depth 0) upwards
    dir_ancestors = list(reversed(parts[:-1]))
    
    for depth, folder in enumerate(dir_ancestors[:3]):  # check up to 3 levels: parent, grandparent, great-grandparent
        # Clean folder string for token matching
        clean_folder = re.sub(r'[^a-z0-9_-]', ' ', folder).strip()
        tokens = clean_folder.split()
        
        # Skip pure generic date / container folders at depth 0 to allow grandparent match
        if folder in GENERIC_FOLDERS or re.match(r'^\d{4}(?:[-_]\d{2})?$', folder):
            continue
            
        for cat_id, positives, negatives in FOLDER_CATEGORY_RULES:
            if any(neg in folder for neg in negatives):
                continue
            
            # Match either substring or token
            matched = False
            for pos in positives:
                if pos in folder or pos in tokens or f"-{pos}" in folder or f"_{pos}" in folder or folder.startswith(pos) or folder.endswith(pos):
                    matched = True
                    break
            
            if matched:
                weight = 0.98 if depth == 0 else (0.95 if depth == 1 else 0.90)
                return cat_id, f"Nearest-Folder Ancestry (depth={depth}: '{folder}' -> {cat_id})", weight

    return None

if __name__ == "__main__":
    conn = sqlite3.connect("backend/data/reposcroller_ledger.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, fl.relative_path, fl.absolute_path
        FROM document_ledger dl
        LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
        GROUP BY dl.sha256_hash;
    """)
    rows = cur.fetchall()
    print(f"Total documents scanned: {len(rows)}")
    
    realigned = {}
    folder_hits = 0
    portfolio_docs = []
    
    for sha, fn, current_type, rel_p, abs_p in rows:
        res = resolve_nearest_folder_category(rel_p or "", abs_p or "")
        if res:
            target_cat, rule, weight = res
            folder_hits += 1
            if target_cat == "career_portfolio":
                portfolio_docs.append((fn, current_type, rule))
            if target_cat != current_type:
                pair = f"{current_type} -> {target_cat}"
                realigned[pair] = realigned.get(pair, 0) + 1

    print(f"Total folder ancestry hits: {folder_hits} / {len(rows)}")
    print(f"Total portfolio documents found via folder ancestry: {len(portfolio_docs)}")
    print("\nTop realignments proposed by Nearest-Folder Ancestry:")
    for pair, cnt in sorted(realigned.items(), key=lambda x: x[1], reverse=True)[:25]:
        print(f"  {pair}: {cnt}")
