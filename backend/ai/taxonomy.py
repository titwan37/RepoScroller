"""Global Multilingual Taxonomy Manager & LLM Dynamic Topic Refiner (EN, FR, DE)."""

import json
import logging
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
import httpx
from backend.config import settings
from backend.ledger.db import get_db_connection, transaction
from backend.ledger.repository import DocumentRepository

logger = logging.getLogger("taxonomy")


class TaxonomyCategory(BaseModel):
    category_id: str = Field(description="Canonical slug e.g. 'employment_contract'")
    parent_id: Optional[str] = Field(default=None, description="Parent category slug for hierarchy")
    name_en: str = Field(description="English category label")
    name_fr: str = Field(description="French category label")
    name_de: str = Field(description="German category label")
    description: str = Field(default="", description="Scope and classification guidance")
    keywords: List[str] = Field(default_factory=list, description="Multilingual keywords")
    document_count: int = Field(default=0)


DEFAULT_TAXONOMY: List[Dict[str, Any]] = [
    {
        "category_id": "career_research",
        "parent_id": "theme_career_employment",
        "name_en": "Job Search & Career Dossiers",
        "name_fr": "Recherche d'emploi & Dossiers de candidature",
        "name_de": "Stellensuche & Bewerbungsdossiers",
        "description": "Job applications, career portfolios, profiles, resumes, and candidate dossier assets.",
        "keywords": ["career", "job", "candidature", "emploi", "bewerbung", "stelle", "recruitment", "recruteur", "positions", "rav", "stellensuche", "job search"]
    },
    {
        "category_id": "career_job_description",
        "parent_id": "career_research",
        "name_en": "Job Descriptions & Vacancy Postings",
        "name_fr": "Fiches de poste & Offres d'emploi",
        "name_de": "Stellenbeschreibungen & Inserate",
        "description": "Job descriptions, vacancy announcements, position requirements, and role profiles.",
        "keywords": [
            "job description", "jobdescription", "job details", "job posting", "job vacancy",
            "position description", "role description", "requirements profile", "anforderungsprofil",
            "stellenbeschreibung", "stellenausschreibung", "stelleninserat", "stellenprofil",
            "offene stelle", "offre d'emploi", "fiche de poste", "description de poste", "profil de poste"
        ]
    },
    {
        "category_id": "career_cv",
        "parent_id": "career_research",
        "name_en": "Curriculum Vitae & Resumes",
        "name_fr": "CV & Parcours professionnel",
        "name_de": "Lebenslauf & Résumés",
        "description": "Chronological & functional CVs, career timelines, and technical skill matrices.",
        "keywords": ["cv", "curriculum vitae", "resume", "work experience", "career history", "expérience professionnelle", "parcours", "lebenslauf", "berufserfahrung", "werdegang"]
    },
    {
        "category_id": "career_cover_letter",
        "parent_id": "career_research",
        "name_en": "Cover & Motivation Letters",
        "name_fr": "Lettres de motivation & Candidatures",
        "name_de": "Bewerbungsschreiben & Motivationsbriefe",
        "description": "Targeted cover letters, job application letters, and motivation pitches.",
        "keywords": [
            "cover letter", "letter of motivation", "job application", "application letter",
            "letter of application", "application_letter", "dear hiring manager", "hiring manager",
            "lettre de motivation", "lettre de candidature", "candidature", "postulation",
            "bewerbungsschreiben", "motivationsschreiben", "bewerbung als", "bewerbung für",
            "bewerbung auf", "bewerbung um die stelle", "stellenbewerbung", "initiativbewerbung"
        ]
    },
    {
        "category_id": "career_profile",
        "parent_id": "career_research",
        "name_en": "Professional Profiles & Bios",
        "name_fr": "Profils professionnels & Bio",
        "name_de": "Berufsprofile & Kurzbiografien",
        "description": "Executive biographies, professional summaries, speaker bios, and LinkedIn profiles.",
        "keywords": ["professional profile", "executive bio", "about me", "summary of qualifications", "linkedin profile", "profil professionnel", "résumé exécutif", "kurzprofil", "berufsprofil"]
    },
    {
        "category_id": "career_portfolio",
        "parent_id": "career_research",
        "name_en": "Work Portfolios & Case Studies",
        "name_fr": "Portfolios de projets & Réalisations",
        "name_de": "Arbeitsportfolios & Projektbeispiele",
        "description": "Work sample showcases, system blueprints, engineering case studies, and design dossiers.",
        "keywords": ["portfolio", "work samples", "case study", "project showcase", "selected achievements", "design dossier", "dossier de réalisations", "arbeitsproben", "projektdokumentation", "fallstudie", "referenzprojekte"]
    },
    {
        "category_id": "legal_contract",
        "parent_id": "theme_legal_justice",
        "name_en": "Contracts & Legal Agreements",
        "name_fr": "Contrats & Conventions juridiques",
        "name_de": "Verträge & Rechtliche Vereinbarungen",
        "description": "General binding agreements, service contracts, and mutual covenants.",
        "keywords": ["contract", "agreement", "contrat", "accord", "vertrag", "vereinbarung", "nda", "covenant"]
    },
    {
        "category_id": "employment_contract",
        "parent_id": "legal_contract",
        "name_en": "Employment & Labor Agreements",
        "name_fr": "Contrats de travail & Droit social",
        "name_de": "Arbeitsverträge & Personalwesen",
        "description": "Individual employment agreements, severance, wage terms, non-competes.",
        "keywords": ["employment", "job", "salary", "travail", "salaire", "employeur", "arbeitsvertrag", "lohn", "anstellung"]
    },
    {
        "category_id": "lease_contract",
        "parent_id": "theme_real_estate_housing",
        "name_en": "Lease & Real Estate Rental",
        "name_fr": "Bail d'habitation & Location immobilière",
        "name_de": "Mietverträge & Immobilienpacht",
        "description": "Commercial and residential tenancy agreements, rent guarantees.",
        "keywords": ["lease", "rent", "tenant", "bail", "loyer", "locataire", "miete", "mietvertrag", "vermieter"]
    },
    {
        "category_id": "court_order",
        "parent_id": "theme_legal_justice",
        "name_en": "Court Judgments & Judicial Orders",
        "name_fr": "Décisions de justice & Ordonnances",
        "name_de": "Gerichtsentscheide & Verfügungen",
        "description": "Judicial decrees, tribunal judgments, bailiff notices, court pleadings.",
        "keywords": ["judgment", "court", "decree", "tribunal", "ordonnance", "urteil", "entscheid", "gericht", "beschluss"]
    },
    {
        "category_id": "tax_assessment",
        "parent_id": "theme_taxation_accounting",
        "name_en": "Tax Assessments & Rulings",
        "name_fr": "Bordereaux fiscaux & Décisions d'imposition",
        "name_de": "Steuerveranlagungen & Rulings",
        "description": "Federal, cantonal, or municipal tax assessments, declarations, and tax advance rulings.",
        "keywords": ["tax", "assessment", "ruling", "impôt", "fisc", "taxation", "steuer", "veranlagung", "quellensteuer"]
    },
    {
        "category_id": "corporate_governance",
        "parent_id": "theme_corporate_business",
        "name_en": "Corporate Resolutions & Governance",
        "name_fr": "Gouvernance & Procès-verbaux de société",
        "name_de": "Unternehmensführung & Generalversammlungsprotokolle",
        "description": "Board minutes, shareholder assembly resolutions, statutes, commercial register extracts.",
        "keywords": [
            "board resolution", "shareholder", "statuts", "procès-verbal d'assemblée",
            "assemblée générale", "sitzungsprotokoll", "gv-protokoll", "versammlungsprotokoll",
            "verwaltungsratsprotokoll", "generalversammlung", "beschlussprotokoll", "statuten"
        ]
    },
    {
        "category_id": "financial_invoice",
        "parent_id": "theme_taxation_accounting",
        "name_en": "Invoices & Accounting Records",
        "name_fr": "Factures & Pièces comptables",
        "name_de": "Rechnungen & Buchhaltungsbelege",
        "description": "Bills, payment receipts, fee notes, balance sheets, expense claims.",
        "keywords": ["invoice", "bill", "payment", "facture", "quittance", "honoraire", "rechnung", "beleg", "zahlung"]
    },
    {
        "category_id": "statute_legislation",
        "parent_id": "theme_legal_justice",
        "name_en": "Legislation, Codes & Official Gazettes",
        "name_fr": "Législation, Codes & Recueils officiels",
        "name_de": "Gesetze, Erlasse & Amtliche Sammlungen",
        "description": "Federal and cantonal acts, decrees, official gazettes, systematic compilations (Fedlex, RO, RS, ZGB, OR, CC, CO).",
        "keywords": [
            "federal act", "statute", "legislation", "official compilation", "systematic collection of laws",
            "recueil officiel", "recueil systématique", "loi fédérale", "ordonnance fédérale", "code civil", "code des obligations",
            "bundesgesetz", "amtliche sammlung", "systematische rechtssammlung", "zivilgesetzbuch", "obligationenrecht", "verordnung",
            "fedlex", "ro-20", "rs-", "sr "
        ]
    },
    {
        "category_id": "financial_banking",
        "parent_id": "theme_banking_finance",
        "name_en": "Bank Statements & Financial Accounts",
        "name_fr": "Relevés bancaires & Comptes financiers",
        "name_de": "Bankauszüge & Finanzkonten",
        "description": "Bank account statements, mortgage statements, interest certificates, asset overviews, and banking correspondence.",
        "keywords": [
            "bank statement", "account statement", "mortgage statement", "interest certificate",
            "relevé bancaire", "extrait de compte", "attestation d'intérêts", "prêt hypothécaire",
            "kontoauszug", "bankauszug", "zinsausweis", "schuldzinsen", "hypothekarauszug",
            "zuger kantonalbank", "postfinance", "kantonalbank", "banking", "iban", "saldo", "zkb", "cre_p_"
        ]
    },
    {
        "category_id": "insurance_policy",
        "parent_id": "theme_insurance_social_security",
        "name_en": "Insurance Policies & Coverage",
        "name_fr": "Polices d'assurance & Couvertures",
        "name_de": "Versicherungspolicen & Deckungsnachweise",
        "description": "Health, household, accident, and liability insurance policies, general conditions (AVB/CGA), and coverage statements.",
        "keywords": [
            "insurance policy", "policy schedule", "certificate of insurance", "general conditions of insurance",
            "police d'assurance", "certificat d'assurance", "conditions générales d'assurance", "assurance maladie", "assurance ménage",
            "versicherungspolice", "versicherungsschein", "allgemeine versicherungsbedingungen", "deckungsausweis", "krankenkasse",
            "helsana", "axa", "allianz", "swica", "suva", "groupe mutuel", "zurich versicherung"
        ]
    },
    {
        "category_id": "administrative_order",
        "parent_id": "theme_public_administration",
        "name_en": "Administrative Decisions & Official Notices",
        "name_fr": "Décisions administratives & Notifications",
        "name_de": "Verwaltungsentscheide & Behördenverfügungen",
        "description": "Decisions and notices from executive public bodies (road traffic offices, police, RAV/unemployment, resident registers).",
        "keywords": [
            "administrative order", "official ruling", "vehicle registration", "driving license notice", "unemployment ruling",
            "décision administrative", "immatriculation", "permis de conduire", "décision orp", "contrôle des habitants",
            "verwaltungsentscheid", "behördliche verfügung", "fahrzeugausweis", "führerausweis", "rav entscheid", "einwohnerkontrolle",
            "strassenverkehrsamt", "kantonspolizei"
        ]
    },
    {
        "category_id": "technical_architecture",
        "parent_id": "theme_technical_architecture",
        "name_en": "Technical Architecture & Specifications",
        "name_fr": "Architecture technique & Spécifications",
        "name_de": "Technische Architektur & Spezifikationen",
        "description": "Blueprints, engineering designs, POC specs, code schemas, system maps.",
        "keywords": ["architecture", "spec", "blueprint", "poc", "spécification", "cahier des charges", "pflichtenheft", "entwurf"]
    },
    {
        "category_id": "technical_reference",
        "parent_id": "theme_education_training",
        "name_en": "Technical Reference, Books & Manuals",
        "name_fr": "Ouvrages techniques & Documentation",
        "name_de": "Fachliteratur, Handbücher & Lernmaterialien",
        "description": "Comprehensive engineering books, whitepapers, study modules, language course units, and technical documentation.",
        "keywords": [
            "technical manual", "handbook", "whitepaper", "textbook", "reference guide", "study guide", "training module",
            "manuel technique", "guide de référence", "livre blanc", "support de cours", "module de formation",
            "handbuch", "fachbuch", "referenzhandbuch", "schulungsunterlagen", "lernmodul", "vocabulary"
        ]
    },
    {
        "category_id": "formal_correspondence",
        "parent_id": "theme_legal_justice",
        "name_en": "Formal Correspondence & Notices",
        "name_fr": "Correspondance formelle & Courriers officiels",
        "name_de": "Formelle Korrespondenz & Behördenbriefe",
        "description": "Registered letters, notices of default, official inquiries, formal emails.",
        "keywords": ["letter", "notice", "inquiry", "courrier", "mise en demeure", "lettre", "brief", "mahnschreiben", "anzeige"]
    },
    {
        "category_id": "identity_credentials",
        "parent_id": "theme_education_training",
        "name_en": "Diplomas, Certificates & References",
        "name_fr": "Diplômes, Certificats de travail & ID",
        "name_de": "Zeugnisse, Arbeitsbestätigungen & Nachweise",
        "description": "Official diplomas, employer reference letters (Arbeitszeugnisse), certifications, ID cards.",
        "keywords": ["diploma", "degree certificate", "reference letter", "employment certificate", "certification", "transcript", "diplôme", "certificat de travail", "lettre de recommandation", "attestation", "diplom", "arbeitszeugnis", "arbeitsbestätigung", "abschlusszeugnis"]
    },
    # --- Level 0 Foundational Macro Themes (3D Knowledge Universe Solar Hubs) ---
    {
        "category_id": "theme_real_estate_housing",
        "parent_id": None,
        "name_en": "Real Estate & Housing",
        "name_fr": "Immobilier & Logement",
        "name_de": "Immobilien & Wohnen",
        "description": "Property ownership, residential tenancy contracts, property management, maintenance invoices, and housing operating costs.",
        "keywords": ["real estate", "housing", "tenancy", "property", "lease", "immobilier", "bail à loyer", "locataire", "loyer", "mietvertrag", "wohnen"]
    },
    {
        "category_id": "theme_banking_finance",
        "parent_id": None,
        "name_en": "Banking & Financial Wealth",
        "name_fr": "Banque & Patrimoine financier",
        "name_de": "Banken & Finanzvermögen",
        "description": "Bank account statements, mortgage agreements, wealth assets, credit/debit transaction notices, and banking correspondence.",
        "keywords": ["banking", "finance", "bank statement", "mortgage", "assets", "banque", "relevé bancaire", "compte", "patrimoine", "postfinance", "bankauszug"]
    },
    {
        "category_id": "theme_taxation_accounting",
        "parent_id": None,
        "name_en": "Taxation, Invoices & Accounting",
        "name_fr": "Fiscalité, Factures & Comptabilité",
        "name_de": "Steuern, Rechnungen & Buchhaltung",
        "description": "Cantonal and federal tax assessments, declaration dossiers, vendor invoices, payment vouchers, and accounting receipts.",
        "keywords": ["taxes", "tax assessment", "invoice", "accounting", "bill", "receipt", "impôts", "factures", "steuern", "rechnung"]
    },
    {
        "category_id": "theme_legal_justice",
        "parent_id": None,
        "name_en": "Legal, Justice & Judicial Proceedings",
        "name_fr": "Affaires juridiques, Justice & Procédures",
        "name_de": "Recht, Justiz & Gerichtsverfahren",
        "description": "Judicial rulings, court pleadings, lawyer correspondence, bilateral contracts, NDAs, and debt collection notifications.",
        "keywords": ["legal", "law", "court order", "attorney", "litigation", "contract", "juridique", "droit", "avocat", "tribunal", "recht", "gericht"]
    },
    {
        "category_id": "theme_career_employment",
        "parent_id": None,
        "name_en": "Career, Employment & Job Search",
        "name_fr": "Carrière, Emploi & Recherche de poste",
        "name_de": "Karriere, Arbeit & Stellensuche",
        "description": "Curriculum vitae, tailored application letters, employment agreements, employer references, job descriptions, and unemployment dossiers.",
        "keywords": ["career", "employment", "resume", "cv", "cover letter", "job vacancy", "portfolio", "emploi", "candidature", "lebenslauf", "bewerbung"]
    },
    {
        "category_id": "theme_education_training",
        "parent_id": None,
        "name_en": "Education, Training & Qualifications",
        "name_fr": "Éducation, Formation & Qualifications",
        "name_de": "Bildung, Ausbildung & Qualifikationen",
        "description": "Academic degrees, engineering diplomas, professional certifications, e-learning modules, language course units, and technical reference books.",
        "keywords": ["education", "degree", "diploma", "certification", "training", "course", "formation", "diplôme", "ausbildung", "weiterbildung"]
    },
    {
        "category_id": "theme_insurance_social_security",
        "parent_id": None,
        "name_en": "Insurance & Social Security",
        "name_fr": "Assurances & Sécurité sociale",
        "name_de": "Versicherungen & Sozialvorsorge",
        "description": "Health, household, vehicle, and accident insurance policies, general terms, claims dossiers, and state social security benefits.",
        "keywords": ["insurance", "policy", "health insurance", "social security", "coverage", "assurance", "caisse maladie", "versicherung", "krankenkasse"]
    },
    {
        "category_id": "theme_public_administration",
        "parent_id": None,
        "name_en": "Public Administration & Civic Notices",
        "name_fr": "Administration publique & Notifications officielles",
        "name_de": "Öffentliche Verwaltung & Behörden",
        "description": "Municipal and cantonal notices, road traffic vehicle registrations, driving license files, and resident control registers.",
        "keywords": ["administration", "government", "official notice", "vehicle registration", "municipality", "administration publique", "verwaltung", "behörden"]
    },
    {
        "category_id": "theme_family_civil_status",
        "parent_id": None,
        "name_en": "Family, Civil Status & Household",
        "name_fr": "Famille, État civil & Vie privée",
        "name_de": "Familie, Zivilstand & Haushalt",
        "description": "Civil status certificates, birth and marriage records, family identity documents, and domestic household management.",
        "keywords": ["family", "civil status", "household", "marriage", "identity", "famille", "état civil", "familie", "zivilstand"]
    },
    {
        "category_id": "theme_technical_architecture",
        "parent_id": None,
        "name_en": "Technical Architecture & Engineering Systems",
        "name_fr": "Architecture technique & Ingénierie logicielle",
        "name_de": "Technische Architektur & Softwaresysteme",
        "description": "System architecture blueprints, API schemas, engineering POC documentation, quality compliance standards, and code specifications.",
        "keywords": ["architecture", "engineering", "specification", "blueprint", "systems", "software", "spécification", "cahier des charges"]
    },
    {
        "category_id": "theme_corporate_business",
        "parent_id": None,
        "name_en": "Corporate Governance & Business Ventures",
        "name_fr": "Gouvernance d'entreprise & Affaires",
        "name_de": "Unternehmensführung & Geschäftstätigkeit",
        "description": "Commercial register records, shareholder resolutions, general assembly minutes, corporate statutes, and business agreements.",
        "keywords": ["corporate", "business", "governance", "shareholder", "commercial register", "minutes", "entreprise", "gesellschaft", "handelsregister"]
    }
]


class TaxonomyManager:
    """Manages persistence and retrieval of the dynamic multilingual taxonomy."""

    def __init__(self, db_conn=None):
        self._conn = db_conn
        self._owns_conn = db_conn is None
        self.ensure_initialized()

    @property
    def conn(self):
        if self._conn is None:
            self._conn = get_db_connection()
        return self._conn

    def close(self):
        if self._owns_conn and self._conn is not None:
            self._conn.close()
            self._conn = None

    def ensure_initialized(self):
        """Seed baseline multilingual categories if table is empty and migrate schema."""
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS global_taxonomy (
                category_id TEXT PRIMARY KEY,
                parent_id TEXT REFERENCES global_taxonomy(category_id),
                name_en TEXT NOT NULL,
                name_fr TEXT NOT NULL,
                name_de TEXT NOT NULL,
                description TEXT,
                keywords TEXT,
                document_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Ensure taxonomy_versions registry table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS taxonomy_versions (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                skill_file TEXT,
                status TEXT DEFAULT 'active',
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Ensure document_ledger has taxonomy_version column
        cur.execute("PRAGMA table_info(document_ledger);")
        cols = [r[1] for r in cur.fetchall()]
        if "taxonomy_version" not in cols:
            cur.execute("ALTER TABLE document_ledger ADD COLUMN taxonomy_version TEXT DEFAULT 'v0.9.0';")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ledger_taxonomy_version ON document_ledger(taxonomy_version);")

        self.conn.commit()

        # Seed categories if missing
        cur.execute("SELECT COUNT(*) FROM global_taxonomy")
        count = cur.fetchone()[0]
        if count == 0:
            # Pass 1: Seed all categories with parent_id=None to guarantee every category_id exists
            for item in DEFAULT_TAXONOMY:
                temp_item = dict(item)
                temp_item["parent_id"] = None
                self.upsert_category(TaxonomyCategory(**temp_item))
            # Pass 2: Set actual parent_id relationships
            for item in DEFAULT_TAXONOMY:
                if item.get("parent_id"):
                    self.upsert_category(TaxonomyCategory(**item))
        else:
            # Ensure all categories from DEFAULT_TAXONOMY (including newly added domains) are seeded
            for item in DEFAULT_TAXONOMY:
                cur.execute("SELECT category_id FROM global_taxonomy WHERE category_id = ?", (item["category_id"],))
                if not cur.fetchone():
                    temp_item = dict(item)
                    temp_item["parent_id"] = None
                    self.upsert_category(TaxonomyCategory(**temp_item))
            for item in DEFAULT_TAXONOMY:
                if item.get("parent_id"):
                    self.upsert_category(TaxonomyCategory(**item))

    def sync_from_skill(self, skill_path: Optional[Any] = None) -> Dict[str, Any]:
        """Parse YAML frontmatter and categories from taxonomy skill file and sync to database."""
        from pathlib import Path
        if skill_path is None:
            backend_dir = Path(__file__).resolve().parent.parent
            project_root = backend_dir.parent
            candidate_paths = [
                backend_dir / "taxonomy" / "taxonomy-v1.2.0.skill.md",
                project_root / "backend" / "taxonomy" / "taxonomy-v1.2.0.skill.md",
                Path("backend/taxonomy/taxonomy-v1.2.0.skill.md"),
                Path("taxonomy/taxonomy-v1.2.0.skill.md"),
                backend_dir / "taxonomy" / "taxonomy-v1.1.0.skill.md",
                project_root / "backend" / "taxonomy" / "taxonomy-v1.1.0.skill.md",
                Path("backend/taxonomy/taxonomy-v1.1.0.skill.md"),
                Path("taxonomy/taxonomy-v1.1.0.skill.md"),
                backend_dir / "taxonomy" / "taxonomy-v1.0.0.skill.md",
                project_root / "backend" / "taxonomy" / "taxonomy-v1.0.0.skill.md",
                Path("backend/taxonomy/taxonomy-v1.0.0.skill.md"),
                Path("taxonomy/taxonomy-v1.0.0.skill.md"),
            ]
            p = next((cp for cp in candidate_paths if cp.exists()), candidate_paths[0])
            skill_path = p

        skill_file_str = str(skill_path)
        version = "v1.2.0"
        name = "RepoScroller 3D Cosmos & Dual-Core Institutional Taxonomy"
        desc = "ALCOA+ Multilingual Taxonomy, 3D Cosmos Macro Themes & Classification Rules (EN, FR, DE) for Dual-Core Institutional & Career Research Document Intelligence."
        status = "active"

        if Path(skill_path).exists():
            try:
                content = Path(skill_path).read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        for line in parts[1].splitlines():
                            if ":" in line:
                                k, v = line.split(":", 1)
                                k = k.strip()
                                # Strip trailing inline comments (e.g. # candidate | active)
                                if "#" in v:
                                    v = v.split("#", 1)[0]
                                v = v.strip().strip('"').strip("'")
                                if k == "taxonomy_version":
                                    version = v
                                elif k == "version_name":
                                    name = v
                                elif k == "description":
                                    desc = v
                                elif k == "status":
                                    status = v
            except Exception as e:
                logger.warning(f"Error parsing skill file metadata: {e}")

        # Record version in taxonomy_versions table
        with transaction(self.conn) as cur:
            cur.execute("""
                INSERT INTO taxonomy_versions (version, name, description, skill_file, status, applied_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(version) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    status = excluded.status,
                    applied_at = CURRENT_TIMESTAMP;
            """, (version, name, desc, skill_file_str, status))

        # Upsert all categories from DEFAULT_TAXONOMY
        synced_count = 0
        for item in DEFAULT_TAXONOMY:
            self.upsert_category(TaxonomyCategory(**item))
            synced_count += 1

        return {
            "status": "synced",
            "version": version,
            "name": name,
            "skill_file": skill_file_str,
            "categories_synced": synced_count
        }

    def get_registered_versions(self) -> List[Dict[str, Any]]:
        """Fetch list of all registered taxonomy versions from taxonomy_versions table."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM taxonomy_versions ORDER BY applied_at DESC")
        return [dict(r) for r in cur.fetchall()]

    def upsert_category(self, cat: TaxonomyCategory) -> None:
        """Insert or update a taxonomy entry."""
        self._cached_categories = None
        kw_json = json.dumps(cat.keywords, ensure_ascii=False)
        with transaction(self.conn) as cur:
            cur.execute("""
                INSERT INTO global_taxonomy (
                    category_id, parent_id, name_en, name_fr, name_de,
                    description, keywords, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(category_id) DO UPDATE SET
                    parent_id = excluded.parent_id,
                    name_en = excluded.name_en,
                    name_fr = excluded.name_fr,
                    name_de = excluded.name_de,
                    description = excluded.description,
                    keywords = excluded.keywords,
                    updated_at = CURRENT_TIMESTAMP;
            """, (
                cat.category_id, cat.parent_id, cat.name_en, cat.name_fr,
                cat.name_de, cat.description, kw_json
            ))

    def get_all_categories(self, include_counts: bool = False) -> List[TaxonomyCategory]:
        """Fetch all categories with optional document counts from document_ledger."""
        if not include_counts and getattr(self, "_cached_categories", None):
            return self._cached_categories

        cur = self.conn.cursor()
        if include_counts:
            cur.execute("""
                SELECT t.*, 
                       (SELECT COUNT(*) FROM document_ledger dl WHERE dl.doc_type = t.category_id) as active_docs
                FROM global_taxonomy t
                ORDER BY t.parent_id IS NOT NULL, t.name_en ASC
            """)
        else:
            cur.execute("""
                SELECT t.*, t.document_count as active_docs
                FROM global_taxonomy t
                ORDER BY t.parent_id IS NOT NULL, t.name_en ASC
            """)
        rows = cur.fetchall()
        result = []
        for r in rows:
            try:
                kw = json.loads(r["keywords"]) if r["keywords"] else []
            except Exception:
                kw = []
            result.append(TaxonomyCategory(
                category_id=r["category_id"],
                parent_id=r["parent_id"],
                name_en=r["name_en"],
                name_fr=r["name_fr"],
                name_de=r["name_de"],
                description=r["description"] or "",
                keywords=kw,
                document_count=r["active_docs"]
            ))
        if not include_counts:
            self._cached_categories = result
        return result

    def get_category(self, category_id: str) -> Optional[TaxonomyCategory]:
        """Retrieve single category by canonical slug."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM global_taxonomy WHERE category_id = ?", (category_id,))
        r = cur.fetchone()
        if not r:
            return None
        try:
            kw = json.loads(r["keywords"]) if r["keywords"] else []
        except Exception:
            kw = []
        return TaxonomyCategory(
            category_id=r["category_id"],
            parent_id=r["parent_id"],
            name_en=r["name_en"],
            name_fr=r["name_fr"],
            name_de=r["name_de"],
            description=r["description"] or "",
            keywords=kw,
            document_count=r["document_count"]
        )

    def merge_categories(self, source_category_id: str, target_category_id: str) -> int:
        """ASSOCIATION: Merge source category into target, re-tagging all documents."""
        if source_category_id == target_category_id:
            return 0

        with transaction(self.conn) as cur:
            # Reassign all documents in document_ledger
            cur.execute("""
                UPDATE document_ledger
                SET doc_type = ?
                WHERE doc_type = ?;
            """, (target_category_id, source_category_id))
            reassigned = cur.rowcount

            # Merge keywords
            source_cat = self.get_category(source_category_id)
            target_cat = self.get_category(target_category_id)
            if source_cat and target_cat:
                merged_kw = list(set(target_cat.keywords + source_cat.keywords))
                cur.execute("""
                    UPDATE global_taxonomy
                    SET keywords = ?
                    WHERE category_id = ?;
                """, (json.dumps(merged_kw, ensure_ascii=False), target_category_id))

            # Record audit log
            cur.execute("""
                INSERT INTO audit_log (sha256_hash, action, details)
                VALUES ('SYSTEM', 'taxonomy_merged', ?);
            """, (f"Merged {source_category_id} into {target_category_id} ({reassigned} documents updated)",))

            # Delete source category
            cur.execute("DELETE FROM global_taxonomy WHERE category_id = ?", (source_category_id,))

            return reassigned

    def split_category(self,
                       parent_category_id: str,
                       new_subcategories: List[TaxonomyCategory],
                       document_reassignments: Dict[str, str]) -> int:
        """DISSOCIATION: Ungroup / split broad category into refined subtopics."""
        # 1. Insert new subcategories
        for sub in new_subcategories:
            sub.parent_id = parent_category_id
            self.upsert_category(sub)

        # 2. Reassign specific document hashes to new categories
        reassigned = 0
        with transaction(self.conn) as cur:
            for sha256, target_cat in document_reassignments.items():
                cur.execute("""
                    UPDATE document_ledger
                    SET doc_type = ?
                    WHERE sha256_hash = ?;
                """, (target_cat, sha256))
                reassigned += cur.rowcount

            cur.execute("""
                INSERT INTO audit_log (sha256_hash, action, details)
                VALUES ('SYSTEM', 'taxonomy_split', ?);
            """, (f"Split {parent_category_id} into {len(new_subcategories)} subcategories ({reassigned} docs reassigned)",))

        return reassigned

    def format_taxonomy_for_prompt(self) -> str:
        """Format the active taxonomy into a compact multilingual guide for LLM inference."""
        cats = self.get_all_categories()
        lines = []
        for c in cats:
            parent_note = f" (subtopic of {c.parent_id})" if c.parent_id else ""
            lines.append(
                f"- `{c.category_id}`{parent_note}: EN: \"{c.name_en}\" | FR: \"{c.name_fr}\" | DE: \"{c.name_de}\""
            )
        return "\n".join(lines)


class TaxonomyRefiner:
    """Uses LLM reasoning to evaluate discovery clusters, associating (merging) or dissociating (splitting) topics."""

    def __init__(self, taxonomy_manager: Optional[TaxonomyManager] = None):
        self.taxonomy = taxonomy_manager or TaxonomyManager()

    def bootstrap_macro_themes(self):
        """Extracts topology, synthesizes Macro Themes with keywords/weights, and seeds the DB."""
        print(f"📂 Extracting topology from {settings.DB_PATH}...")
        
        with sqlite3.connect(settings.DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT fl.relative_path 
                FROM file_locations fl
                JOIN document_ledger dl ON fl.sha256_hash = dl.sha256_hash
            """)
            rows = cur.fetchall()
            
            if not rows:
                print("⚠️ No data found. Run a crawler scan first.")
                return

            # Build weighted folder topology
            topology = defaultdict(int)
            for (rel_path,) in rows:
                parts = Path(rel_path).parts
                if len(parts) > 1:
                    macro_folder = "/".join(parts[:2])
                    topology[macro_folder] += 1
                    
            sorted_topology = dict(sorted(topology.items(), key=lambda item: item[1], reverse=True))
            topology_str = "\n".join([f"- {f} ({c} docs)" for f, c in list(sorted_topology.items())[:100]])

        print(f"🧠 Synthesizing Macro Themes using {settings.chat_model}...")

        prompt = f"""You are a Chief Information Architect. 
Analyze the following physical folder topology and document counts from a digital repository.
Deduce exactly 10 to 15 "Macro Life Domains" (Themes) that logically group these folders.

Requirements:
1. Assign a short machine-readable slug starting with 'theme_' (e.g., "theme_real_estate").
2. Generate a multilingual array of 8-16 relevant search keywords.
3. Aggregate the document counts of the constituent folders into a total "weight" integer.
4. Output STRICTLY in JSON format.

Folder Topology:
{topology_str}

Output JSON format:
{{
  "macro_themes": [
    {{
      "slug": "theme_name",
      "name_en": "English Name",
      "name_fr": "French Name",
      "name_de": "German Name",
      "description": "Short description",
      "keywords": ["keyword1", "keyword2", "keyword3", "keyword4"],
      "weight": 150
    }}
  ]
}}"""

        result_text = self._call_llm(prompt)
        
        try:
            clean_json = result_text.strip().removeprefix("```json").removesuffix("```").strip()
            themes = json.loads(clean_json).get("macro_themes", [])
            
            inserted_nodes = 0
            
            for t in themes:
                # 1. Upsert into the formal global_taxonomy ledger
                cat = TaxonomyCategory(
                    category_id=t["slug"],
                    parent_id=None,  # These are root macro domains
                    name_en=t.get("name_en", t["slug"]),
                    name_fr=t.get("name_fr", ""),
                    name_de=t.get("name_de", ""),
                    description=t.get("description", ""),
                    keywords=t.get("keywords", []),
                    document_count=t.get("weight", 0)
                )
                self.taxonomy.upsert_category(cat)

                # 2. Insert into the 3D Knowledge Graph as solar hubs
                properties = json.dumps({
                    "name_en": t.get("name_en"),
                    "name_fr": t.get("name_fr"),
                    "name_de": t.get("name_de"),
                    "description": t.get("description"),
                    "keywords": t.get("keywords", []),
                    "aggregated_weight": t.get("weight", 0)
                }, ensure_ascii=False)
                
                with sqlite3.connect(settings.DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT OR IGNORE INTO knowledge_nodes (node_id, node_type, name, properties_json)
                        VALUES (?, 'theme', ?, ?)
                    """, (t["slug"], t.get("name_en", t["slug"]), properties))
                    if cur.rowcount > 0:
                        inserted_nodes += 1
                        
            print(f"🎉 Successfully seeded {len(themes)} taxonomy roots and {inserted_nodes} 3D graph hubs!")
            
        except Exception as e:
            print(f"❌ Failed to parse or save themes.\nError: {e}")


    def ingest_reviewed_themes(self, json_path: str):
        """Reads a human-reviewed foundational themes JSON and seeds the taxonomy and Knowledge Graph."""
        import json
        import sqlite3
        from pathlib import Path
        from backend.config import settings
        from backend.ai.taxonomy import TaxonomyCategory

        path = Path(json_path)
        if not path.exists():
            print(f"❌ File not found: {json_path}")
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        themes = data.get("macro_themes", [])
        if not themes:
            print("⚠️ No themes found under the 'macro_themes' key.")
            return

        inserted_nodes = 0
        updated_nodes = 0
        
        for t in themes:
            # Safely format the slug (e.g., "Real Estate" -> "theme_real_estate")
            raw_slug = t.get("slug", "unknown").lower().strip()
            slug = raw_slug if raw_slug.startswith("theme_") else f"theme_{raw_slug.replace(' & ', '_').replace(' ', '_')}"

            # 1. Upsert into the formal global_taxonomy ledger
            cat = TaxonomyCategory(
                category_id=slug,
                parent_id=None,
                name_en=t.get("name_en", slug),
                name_fr=t.get("name_fr", ""),
                name_de=t.get("name_de", ""),
                description=t.get("description", ""),
                keywords=t.get("keywords", []),
                document_count=t.get("weight", 0)
            )
            self.taxonomy.upsert_category(cat)

            # 2. Insert into the 3D Knowledge Graph as solar hubs
            properties = json.dumps({
                "name_en": t.get("name_en"),
                "name_fr": t.get("name_fr"),
                "name_de": t.get("name_de"),
                "description": t.get("description"),
                "keywords": t.get("keywords", []),
                "aggregated_weight": t.get("weight", 0)
            }, ensure_ascii=False)
            
            with sqlite3.connect(settings.DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR IGNORE INTO knowledge_nodes (node_id, node_type, name, properties_json)
                    VALUES (?, 'theme', ?, ?)
                """, (slug, t.get("name_en", slug), properties))
                
                # If the hub already exists, update it with your manual JSON reviews
                if cur.rowcount > 0:
                    inserted_nodes += 1
                else:
                    cur.execute("""
                        UPDATE knowledge_nodes 
                        SET name = ?, properties_json = ? 
                        WHERE node_id = ? AND node_type = 'theme'
                    """, (t.get("name_en", slug), properties, slug))
                    updated_nodes += 1
                    
        print(f"🎉 Successfully ingested {len(themes)} taxonomy roots! ({inserted_nodes} new, {updated_nodes} updated 3D graph hubs)")

    def run_refinement(self, sample_size: int = 100) -> Dict[str, Any]:
        """Analyze documents across the ledger, propose and execute topic association/dissociation."""
        repo = DocumentRepository(conn=self.taxonomy.conn)
        docs = repo.get_all_documents(limit=sample_size)
        if not docs:
            return {"status": "no_documents", "actions_taken": []}

        # Build topic clustering prompt
        tax_guide = self.taxonomy.format_taxonomy_for_prompt()
        doc_summaries = []
        for d in docs:
            doc_summaries.append({
                "sha256": d["sha256_hash"][:12],
                "filename": d["canonical_filename"],
                "current_type": d["doc_type"],
                "snippet": (d.get("text_snippet") or "")[:150]
            })

        prompt = f"""You are an ALCOA+ Multilingual Taxonomy Refiner (EN, FR, DE).
Your job is to optimize and evolve the global document taxonomy by grouping (associating) synonyms or ungrouping (dissociating) broad categories into refined subtopics.

Active Multilingual Taxonomy:
{tax_guide}

Sample Document Ledgers:
{json.dumps(doc_summaries, indent=2)}

Evaluate whether:
1. Two existing categories are synonyms across languages (e.g., German Mietvertrag vs French Bail) and should be MERGED (association).
2. A category contains distinct sub-clusters with 2+ documents that should be SPLIT into a new subcategory (dissociation).
3. Any documents should be extended to a novel canonical category.

Return ONLY a valid JSON object:
{{
  "proposed_merges": [
    {{"source_id": "...", "target_id": "...", "reason": "..."}}
  ],
  "proposed_new_subcategories": [
    {{
      "category_id": "<canonical_slug>",
      "parent_id": "<parent_slug_or_null>",
      "name_en": "...",
      "name_fr": "...",
      "name_de": "...",
      "description": "...",
      "keywords": ["..."]
    }}
  ],
  "reassignments": [
    {{"sha256_prefix": "...", "new_category": "..."}}
  ]
}}
"""
        # Execute LLM or deterministic fallback
        llm_response = self._call_llm(prompt)
        actions = []

        if llm_response:
            # 1. Execute Merges (Association)
            for m in llm_response.get("proposed_merges", []):
                s_id = m.get("source_id")
                t_id = m.get("target_id")
                if s_id and t_id and self.taxonomy.get_category(s_id) and self.taxonomy.get_category(t_id):
                    reassigned = self.taxonomy.merge_categories(s_id, t_id)
                    actions.append(f"Merged `{s_id}` into `{t_id}` ({reassigned} documents updated). Reason: {m.get('reason')}")

            # 2. Add New Subcategories
            for sub in llm_response.get("proposed_new_subcategories", []):
                cat = TaxonomyCategory(**sub)
                self.taxonomy.upsert_category(cat)
                actions.append(f"Created new refined category `{cat.category_id}` ({cat.name_en} / {cat.name_fr} / {cat.name_de})")

            # 3. Apply Reassignments
            if llm_response.get("reassignments"):
                with transaction(self.taxonomy.conn) as cur:
                    for reas in llm_response["reassignments"]:
                        prefix = reas.get("sha256_prefix")
                        new_cat = reas.get("new_category")
                        if prefix and new_cat:
                            cur.execute("""
                                UPDATE document_ledger
                                SET doc_type = ?
                                WHERE sha256_hash LIKE ?;
                            """, (new_cat, f"{prefix}%"))

        return {
            "status": "completed",
            "actions_taken": actions,
            "current_taxonomy_size": len(self.taxonomy.get_all_categories())
        }

    def _call_llm(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Call OpenRouter or Ollama; fallback to None if offline."""
        if settings.OPENROUTER_API_KEY:
            try:
                with httpx.Client(timeout=20.0) as client:
                    resp = client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": settings.OPENROUTER_MODEL,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.2,
                            "response_format": {"type": "json_object"}
                        }
                    )
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        return json.loads(content)
            except Exception as e:
                logger.warning(f"Taxonomy LLM call failed: {e}")

        # Local Ollama fallback
        import time
        t0 = time.time()
        target_model = settings.chat_model
        try:
            with httpx.Client(timeout=settings.OLLAMA_TIMEOUT) as client:
                resp = client.post(
                    f"{settings.chat_url}/api/chat",
                    json={
                        "model": target_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "format": "json",
                        "stream": False,
                        "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                        "options": {"num_ctx": getattr(settings, "OLLAMA_NUM_CTX", 2048)}
                    }
                )
                elapsed_ms = (time.time() - t0) * 1000
                from backend.ai.telemetry import workload_telemetry
                if resp.status_code == 200:
                    workload_telemetry.record_chat(
                        latency_ms=elapsed_ms,
                        success=True,
                        node=workload_telemetry.chat_active_node,
                        model=target_model
                    )
                    content = resp.json()["message"]["content"]
                    return json.loads(content)
                else:
                    workload_telemetry.record_chat(
                        latency_ms=elapsed_ms,
                        success=False,
                        node=workload_telemetry.chat_active_node,
                        model=target_model
                    )
        except Exception:
            elapsed_ms = (time.time() - t0) * 1000
            from backend.ai.telemetry import workload_telemetry
            workload_telemetry.record_chat(
                latency_ms=elapsed_ms,
                success=False,
                node=workload_telemetry.chat_active_node,
                model=target_model
            )
            pass

        return None


class TaxonomyEvolutionEngine:
    """Orchestrates ALCOA+ compliant document re-classification according to new taxonomy versions."""

    def __init__(self, taxonomy_manager: Optional[TaxonomyManager] = None):
        self.taxonomy = taxonomy_manager or TaxonomyManager()

    def get_evolution_status(self, target_version: str = "v1.1.0") -> Dict[str, Any]:
        """Return distribution of documents by taxonomy_version and doc_type."""
        cur = self.taxonomy.conn.cursor()
        cur.execute("""
            SELECT COALESCE(taxonomy_version, 'v0.9.0') as ver, COUNT(*) as count
            FROM document_ledger
            GROUP BY ver
            ORDER BY count DESC;
        """)
        versions = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("""
            SELECT doc_type, COUNT(*) as count
            FROM document_ledger
            GROUP BY doc_type
            ORDER BY count DESC;
        """)
        categories = {r[0]: r[1] for r in cur.fetchall()}

        total = sum(versions.values())
        migrated = versions.get(target_version, 0)
        pending = total - migrated

        return {
            "target_version": target_version,
            "total_documents": total,
            "migrated_documents": migrated,
            "pending_documents": pending,
            "migration_percent": round((migrated / max(1, total)) * 100, 2),
            "version_distribution": versions,
            "category_distribution": categories
        }

    def evaluate_document_reclassification(self, doc: Dict[str, Any]) -> Tuple[str, str, float]:
        """
        Evaluate whether a document qualifies for a new taxonomy category using Section 4 Disambiguation Rules.
        Returns: (target_category, rule_applied, confidence)
        """
        # Parse file, path and text
        fn = (doc.get("canonical_filename") or "").lower()
        path = (doc.get("relative_path") or "").lower()
        abs_p = (doc.get("absolute_path") or "").lower()
        snippet = (doc.get("text_snippet") or "").lower()
        combined = f"{fn} {path} {abs_p} {snippet}"
        old_cat = doc.get("doc_type") or "other"

        # -------------------------------------------------------------
        # NEAREST-FOLDER ANCESTRY PARSING (Depth 0 = immediate folder)
        # -------------------------------------------------------------
        raw_path = (doc.get("absolute_path") or doc.get("relative_path") or "").replace("\\", "/").strip()
        parts = [p.strip() for p in raw_path.split("/") if p.strip()]
        dir_ancestors = list(reversed(parts[:-1])) if len(parts) > 1 else []
        leaf_folder = dir_ancestors[0].lower() if dir_ancestors else ""
        parent_folder = dir_ancestors[1].lower() if len(dir_ancestors) > 1 else ""

        # 1. TOP PRIORITY: Portfolio & Work Samples (Nearest-Folder Ancestry & Filename)
        if any(k in fn for k in ["portfolio-booklet", "portfolio_booklet", "portfolio booklet", "arbeitsproben", "case_study", "casestudy"]) or \
           (leaf_folder and "portfolio" in leaf_folder and not any(k in fn for k in ["jobdescription", "job_description", "_jp.pdf", "cover_letter", "coverletter", "application_letter"])):
            return "career_portfolio", f"Rule 4.0 (Nearest-Folder Ancestry '{leaf_folder}' + Portfolio)", 0.98

        # 2. CV & Lebenslauf (Rule 4.1 + Nearest-Folder Ancestry)
        fn_split = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', doc.get("canonical_filename") or "")
        fn_split = re.sub(r'([0-9]+)([a-zA-Z]+)', r'\1 \2', fn_split)
        fn_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', fn_split)
        fn_tokens = re.sub(r'[_.\-]+', ' ', fn_split).lower()
        is_reference = any(k in fn for k in ["certificat de travail", "arbeitszeugnis", "arbeitsbestätigung", "reference letter", "reference_letter"])

        if not is_reference and (
            re.search(r'(?:^|[^a-z0-9])(cv|curriculum[\s_-]*vitae|lebenslauf|resume)(?:[^a-z0-9]|$)', fn) or
            re.search(r'\b(cv|curriculum|lebenslauf|resume)\b', fn_tokens) or
            any(k in fn for k in ["_cv_", "-cv-", "_cv.", "-cv.", "cv_", "cv-", "lebenslauf", "curriculum_vitae", "curriculum-vitae"]) or
            re.search(r'\b(curriculum vitae|lebenslauf)\b', combined) or
            (leaf_folder and any(cv_k in leaf_folder for cv_k in ["2025-cv", "2026-cv", "cv2015", "cv2014", "2019cv", "2020cv", "2018-cv", "cv-2019", "cv_masters", "cv_tailored"]) and not any(k in fn for k in ["jobdescription", "application_letter", "cover_letter", "stellenbeschreib"])) or
            (("experience" in combined or "berufserfahrung" in combined or "parcours" in combined) and
             ("education" in combined or "ausbildung" in combined or "formation" in combined) and
             any(p in path for p in ["cv", "resume", "lebenslauf"])) or
            (any(p in path for p in ["2025-cv", "2026-cv", "/cv/", "\\cv\\"]) and not any(k in fn for k in ["jobdescription", "application_letter", "cover_letter"]))
        ):
            return "career_cv", "Rule 4.1 (CV / Lebenslauf Top Priority)", 0.98

        # 3. Rule 4.2: Cover Letter vs Formal Correspondence (Nearest-Folder Ancestry + Form Factor)
        if any(k in fn for k in ["motivation", "candidature", "cover_letter", "coverletter", "bewerbungsschreiben", "motivationsschreiben", "application_letter"]) or \
           "lettre de motivation" in combined or "bewerbung um die stelle" in combined or \
           (leaf_folder and any(lm_k in leaf_folder for lm_k in ["2025-lm", "lm", "motivation_letter"]) and not any(k in fn for k in ["jobdescription", "stellenbeschreib", "_jp.pdf"])) or \
           ("candidature" in combined and any(sal in combined for sal in ["madame, monsieur", "sehr geehrte damen und herren", "dear hiring manager"])):
            return "career_cover_letter", "Rule 4.2 (Cover Letter)", 0.95

        # 4. Rule 4.5: Job Descriptions & Vacancies (including _JP.pdf) vs Employment/Lease agreements
        if fn.endswith("_jp.pdf") or fn.endswith("-jp.pdf") or "_jp." in fn or "-jp." in fn or \
           any(k in fn for k in ["jobdescription", "job_description", "job-description", "stellenbeschreibung", "stellenausschreibung", "stelleninserat", "fiche de poste", "fiche_de_poste"]) or \
           "job details:----------job_title:" in combined or \
           ("job details" in combined and any(k in combined for k in ["job_title", "company_name", "job_url", "short_description"])) or \
           any(phrase in combined for phrase in ["job description", "stellenbeschreibung", "stellenausschreibung", "stelleninserat", "anforderungsprofil", "deine aufgaben als", "ihre aufgaben als", "wir suchen per sofort"]) or \
           (leaf_folder and any(p in leaf_folder for p in ["positions", "stellen", "vacancies", "job-descriptions", "job-profiles"]) and not any(k in fn for k in ["coverletter", "cover_letter", "application_letter", "lebenslauf"])) or \
           (any(p in path for p in ["positions", "stellen", "vacancies", "job-descriptions"]) and any(k in fn for k in ["job", "position", "description", "engineer", "architect", "manager", "developer"])):
            return "career_job_description", "Rule 4.5 (Job Description & _JP.pdf)", 0.98

        # 5. Rule 4.6: Swiss Federal & Cantonal Legislation (statute_legislation)
        if any(k in fn for k in ["fedlex", "fedlex-data-admin", "ro-20", "rs-20", "rs-10", "rs-0."]) or \
           "fedlex-data-admin-ch" in combined or \
           (leaf_folder and "fedlex" in leaf_folder) or \
           any(p in path for p in ["fedlex", "fedlex_library", "rechtssammlung"]) or \
           any(phrase in combined for phrase in ["systematische rechtssammlung", "recueil officiel", "recueil systématique", "loi fédérale sur", "bundesgesetz über", "zivilgesetzbuch", "obligationenrecht", "sr 1", "sr 2", "sr 3", "sr 4", "sr 5", "sr 6", "sr 7", "sr 8", "sr 9"]):
            return "statute_legislation", "Rule 4.6 (Legislation & Fedlex)", 0.98

        # 6. Rule 4.7: Banking & Account Statements (financial_banking)
        if fn.startswith("cre_p_") or "_kontoauszug" in fn or "kontoauszug" in fn or "bankauszug" in fn or "zinsausweis" in fn or "hypothek" in fn or \
           (leaf_folder and any(b_k in leaf_folder for b_k in ["postfinance", "zugerkantonalbank", "zkb", "releve", "kontoauszug", "bankauszug", "cre_p_"])) or \
           ("postfinance" in combined and any(k in combined for k in ["cre_p_", "konto", "iban", "gutschrift", "belastung", "relevé", "extrait"])) or \
           ("zuger kantonalbank" in combined and any(k in combined for k in ["konto", "saldo", "zinsausweis", "auszug"])) or \
           any(phrase in combined for phrase in ["relevé de compte", "extrait de compte", "attestation d'intérêts", "kontosaldo", "hypothekarauszug"]):
            return "financial_banking", "Rule 4.7 (Banking & Account Statements)", 0.96

        # 7. Rule 4.8: Insurance Policies & Coverage (insurance_policy)
        if (leaf_folder and any(ins_k in leaf_folder for ins_k in ["helsana", "assura", "groupemutuel", "swica", "krankenkasse", "cap_rechtsschutz"])) or \
           (any(ins in combined for ins in ["helsana", "axa", "allianz", "swica", "suva", "groupe mutuel", "zurich versicherung", "sanitas", "css versicherung"]) and \
            any(term in combined for term in ["police", "versicherungspolice", "assurance combinée", "versicherungsschein", "deckungsnachweis", "police d'assurance", "krankenkasse", "versicherungsvertrag", "police details", "assurance animaux", "assurance ménage"])):
            return "insurance_policy", "Rule 4.8 (Insurance Policies)", 0.95

        # 8. Rule 4.9: Administrative Decisions & Public Authority Notices (administrative_order)
        if (leaf_folder and any(adm_k in leaf_folder for adm_k in ["strassenverkehrsamt", "auto_polizei", "einwohnerkontrolle", "ausweisung"])) or \
           (any(auth in combined for auth in ["strassenverkehrsamt", "kantonspolizei", "einwohnerkontrolle", "sva zürich", "rav", "inno park", "innopark"]) and \
            any(term in combined for term in ["verfügung", "fahrzeug", "führerausweis", "decision", "décision", "immatriculation", "ordnungswidrigkeit", "umfrage kundenzufriedenheit", "kursbestätigung"])):
            return "administrative_order", "Rule 4.9 (Administrative Decisions)", 0.94

        # 9. Rule 4.10: Technical Books & Educational Resources (technical_reference)
        if any(k in fn for k in ["big book", "big-book", "vocabulary", "handbook", "textbook"]) or \
           fn.startswith("p1 vocabulary") or fn.startswith("p1u") or fn.startswith("n2p2") or \
           any(term in combined for term in ["the big book of", "vocabulary unit", "sprachkurs", "kursunterlagen"]):
            return "technical_reference", "Rule 4.10 (Technical Reference & Books)", 0.92

        # 10. Rule 4.5: Professional Profile vs CV
        if any(k in fn for k in ["profil", "profile", "executive_bio", "kurzprofil"]) and \
           (leaf_folder and "profile" in leaf_folder or "linkedin" in combined) and \
           not re.search(r'\b(cv|curriculum)\b', fn):
            return "career_profile", "Rule 4.5 (Professional Profile)", 0.90

        # 11. Rule 4.11: Strict Guardrail for Tenancy & Lease Contracts (False Positive Removal)
        if old_cat == "lease_contract":
            has_lease_terms = any(k in combined for k in [
                "mietvertrag", "geschäftsmietvertrag", "wohnungsmietvertrag", "mietzins", "mieter", "vermieter",
                "wohnungsabnahme", "bail à loyer", "bail a loyer", "contrat de bail", "bailleur", "locataire",
                "loyer mensuel", "état des lieux", "tenancy agreement"
            ])
            if not has_lease_terms:
                # Document was falsely tagged as lease_contract
                if fn.endswith("_ingestionreport.md") or "ingestion audit" in combined or fn.endswith(".md"):
                    return "technical_architecture", "Rule 4.11 (Lease Guardrail -> Technical Doc)", 0.90
                # Fall back to other to remove contamination
                return "other", "Rule 4.11 (Lease Guardrail - False Positive Removal)", 0.85

        return old_cat, "Unchanged Baseline", 0.70

    def evolve_ledger(self,
                      dry_run: bool = True,
                      limit: int = 500,
                      source_root_filter: Optional[str] = None,
                      target_version: str = "v1.1.0") -> Dict[str, Any]:
        """
        Scan candidates and evolve categorization to target_version.
        If dry_run is True, returns proposed changes without committing.
        If dry_run is False, updates document_ledger, enqueues to kb_processing_queue, and logs audit trail.
        """
        cur = self.taxonomy.conn.cursor()

        # Select candidate documents
        query = """
            SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.text_snippet,
                   COALESCE(dl.taxonomy_version, 'v0.9.0') as current_tax_ver,
                   fl.relative_path, fl.absolute_path, fl.storage_root
            FROM document_ledger dl
            LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
            WHERE (dl.taxonomy_version IS NULL OR dl.taxonomy_version != ?)
        """
        params = [target_version]
        if source_root_filter:
            query += " AND (fl.storage_root LIKE ? OR fl.relative_path LIKE ?)"
            params.extend([f"%{source_root_filter}%", f"%{source_root_filter}%"])

        query += " GROUP BY dl.sha256_hash LIMIT ?;"
        params.append(limit)

        cur.execute(query, tuple(params))
        candidates = [dict(r) for r in cur.fetchall()]

        proposals = []
        applied_count = 0
        reclassified_by_type = {}

        for doc in candidates:
            sha = doc["sha256_hash"]
            old_cat = doc.get("doc_type") or "other"
            new_cat, rule, conf = self.evaluate_document_reclassification(doc)

            is_reclassified = (new_cat != old_cat)

            proposal = {
                "sha256": sha,
                "filename": doc["canonical_filename"],
                "old_category": old_cat,
                "new_category": new_cat,
                "is_changed": is_reclassified,
                "rule_applied": rule,
                "confidence": conf
            }
            proposals.append(proposal)

            if is_reclassified:
                reclassified_by_type[new_cat] = reclassified_by_type.get(new_cat, 0) + 1

        if not dry_run and proposals:
            with transaction(self.taxonomy.conn) as cur_tx:
                for p in proposals:
                    sha = p["sha256"]
                    new_cat = p["new_category"]
                    old_cat = p["old_category"]
                    rule = p["rule_applied"]

                    # 1. Update ledger
                    cur_tx.execute("""
                        UPDATE document_ledger
                        SET doc_type = ?, taxonomy_version = ?
                        WHERE sha256_hash = ?;
                    """, (new_cat, target_version, sha))

                    # 2. Re-enqueue to KB sidecar for vector chunk re-embedding if category changed
                    if p["is_changed"]:
                        cur_tx.execute("""
                            INSERT INTO kb_processing_queue (sha256_hash, status, enqueued_at)
                            VALUES (?, 'pending', CURRENT_TIMESTAMP)
                            ON CONFLICT(sha256_hash) DO UPDATE SET
                                status = 'pending',
                                enqueued_at = CURRENT_TIMESTAMP;
                        """, (sha,))

                        # 3. Record ALCOA+ Audit Log
                        cur_tx.execute("""
                            INSERT INTO audit_log (sha256_hash, action, details, actor)
                            VALUES (?, 'taxonomy_evolution', ?, 'TaxonomyEvolutionEngine');
                        """, (sha, f"Evolved from '{old_cat}' to '{new_cat}' via {rule} ({target_version})"))

                    applied_count += 1

        return {
            "status": "completed",
            "dry_run": dry_run,
            "target_version": target_version,
            "candidates_examined": len(candidates),
            "reclassifications_count": sum(reclassified_by_type.values()),
            "reclassified_by_type": reclassified_by_type,
            "applied_count": applied_count if not dry_run else 0,
            "sample_proposals": [p for p in proposals if p["is_changed"]][:25]
        }

