"""Global Multilingual Taxonomy Manager & LLM Dynamic Topic Refiner (EN, FR, DE)."""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
import httpx
from reposcroller.config import settings
from reposcroller.ledger.db import get_db_connection, transaction
from reposcroller.ledger.repository import DocumentRepository

logger = logging.getLogger("reposcroller.taxonomy")


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
        "parent_id": None,
        "name_en": "Job Search & Career Dossiers",
        "name_fr": "Recherche d'emploi & Dossiers de candidature",
        "name_de": "Stellensuche & Bewerbungsdossiers",
        "description": "Job applications, career portfolios, profiles, resumes, and candidate dossier assets.",
        "keywords": ["career", "job", "candidature", "emploi", "bewerbung", "stelle", "recruitment", "recruteur"]
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
        "keywords": ["cover letter", "letter of motivation", "job application", "dear hiring manager", "lettre de motivation", "candidature", "postulation", "bewerbungsschreiben", "motivationsschreiben", "bewerbung um die stelle"]
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
        "parent_id": None,
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
        "parent_id": "legal_contract",
        "name_en": "Lease & Real Estate Rental",
        "name_fr": "Bail d'habitation & Location immobilière",
        "name_de": "Mietverträge & Immobilienpacht",
        "description": "Commercial and residential tenancy agreements, rent guarantees.",
        "keywords": ["lease", "rent", "tenant", "bail", "loyer", "locataire", "miete", "mietvertrag", "vermieter"]
    },
    {
        "category_id": "court_order",
        "parent_id": None,
        "name_en": "Court Judgments & Judicial Orders",
        "name_fr": "Décisions de justice & Ordonnances",
        "name_de": "Gerichtsentscheide & Verfügungen",
        "description": "Judicial decrees, tribunal judgments, bailiff notices, court pleadings.",
        "keywords": ["judgment", "court", "decree", "tribunal", "ordonnance", "urteil", "entscheid", "gericht", "beschluss"]
    },
    {
        "category_id": "tax_assessment",
        "parent_id": None,
        "name_en": "Tax Assessments & Rulings",
        "name_fr": "Bordereaux fiscaux & Décisions d'imposition",
        "name_de": "Steuerveranlagungen & Rulings",
        "description": "Federal, cantonal, or municipal tax assessments, declarations, and tax advance rulings.",
        "keywords": ["tax", "assessment", "ruling", "impôt", "fisc", "taxation", "steuer", "veranlagung", "quellensteuer"]
    },
    {
        "category_id": "corporate_governance",
        "parent_id": None,
        "name_en": "Corporate Resolutions & Governance",
        "name_fr": "Gouvernance & Procès-verbaux de société",
        "name_de": "Unternehmensführung & Generalversammlungsprotokolle",
        "description": "Board minutes, shareholder assembly resolutions, statutes, commercial register extracts.",
        "keywords": ["board", "resolution", "shareholder", "statuts", "procès-verbal", "assemblée", "protokoll", "gv", "statuten"]
    },
    {
        "category_id": "financial_invoice",
        "parent_id": None,
        "name_en": "Invoices & Accounting Records",
        "name_fr": "Factures & Pièces comptables",
        "name_de": "Rechnungen & Buchhaltungsbelege",
        "description": "Bills, payment receipts, fee notes, balance sheets, expense claims.",
        "keywords": ["invoice", "bill", "payment", "facture", "quittance", "honoraire", "rechnung", "beleg", "zahlung"]
    },
    {
        "category_id": "technical_architecture",
        "parent_id": None,
        "name_en": "Technical Architecture & Specifications",
        "name_fr": "Architecture technique & Spécifications",
        "name_de": "Technische Architektur & Spezifikationen",
        "description": "Blueprints, engineering designs, POC specs, code schemas, system maps.",
        "keywords": ["architecture", "spec", "blueprint", "poc", "spécification", "cahier des charges", "pflichtenheft", "entwurf"]
    },
    {
        "category_id": "formal_correspondence",
        "parent_id": None,
        "name_en": "Formal Correspondence & Notices",
        "name_fr": "Correspondance formelle & Courriers officiels",
        "name_de": "Formelle Korrespondenz & Behördenbriefe",
        "description": "Registered letters, notices of default, official inquiries, formal emails.",
        "keywords": ["letter", "notice", "inquiry", "courrier", "mise en demeure", "lettre", "brief", "mahnschreiben", "anzeige"]
    },
    {
        "category_id": "identity_credentials",
        "parent_id": None,
        "name_en": "Diplomas, Certificates & References",
        "name_fr": "Diplômes, Certificats de travail & ID",
        "name_de": "Zeugnisse, Arbeitsbestätigungen & Nachweise",
        "description": "Official diplomas, employer reference letters (Arbeitszeugnisse), certifications, ID cards.",
        "keywords": ["diploma", "degree certificate", "reference letter", "employment certificate", "certification", "transcript", "diplôme", "certificat de travail", "lettre de recommandation", "attestation", "diplom", "arbeitszeugnis", "arbeitsbestätigung", "abschlusszeugnis"]
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
            for item in DEFAULT_TAXONOMY:
                self.upsert_category(TaxonomyCategory(**item))
        else:
            # Ensure the career_research categories are seeded even if prior taxonomy existed
            cur.execute("SELECT category_id FROM global_taxonomy WHERE category_id = 'career_research'")
            if not cur.fetchone():
                for item in DEFAULT_TAXONOMY:
                    if item["category_id"].startswith("career_"):
                        self.upsert_category(TaxonomyCategory(**item))

    def sync_from_skill(self, skill_path: Optional[Any] = None) -> Dict[str, Any]:
        """Parse YAML frontmatter and categories from taxonomy skill file and sync to database."""
        from pathlib import Path
        if skill_path is None:
            p = Path("taxonomy/taxonomy-v1.0.0.skill.md")
            if not p.exists():
                p = Path(settings.BASE_DIR if hasattr(settings, "BASE_DIR") else ".") / "taxonomy" / "taxonomy-v1.0.0.skill.md"
            skill_path = p

        skill_file_str = str(skill_path)
        version = "v1.0.0"
        name = "RepoScroller Baseline Multilingual Taxonomy (with Career Research Axis)"
        desc = "ALCOA+ Multilingual Taxonomy & Classification Rules (EN, FR, DE) for Legal, Financial, Corporate, Technical, and Career Research Document Intelligence."
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

    def get_all_categories(self) -> List[TaxonomyCategory]:
        """Fetch all categories with up-to-date document counts from document_ledger."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT t.*, 
                   (SELECT COUNT(*) FROM document_ledger dl WHERE dl.doc_type = t.category_id) as active_docs
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
                from reposcroller.ai.telemetry import workload_telemetry
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
            from reposcroller.ai.telemetry import workload_telemetry
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

    def get_evolution_status(self, target_version: str = "v1.0.0") -> Dict[str, Any]:
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
        fn = (doc.get("canonical_filename") or "").lower()
        path = (doc.get("relative_path") or "").lower()
        snippet = (doc.get("text_snippet") or "").lower()
        combined = f"{fn} {path} {snippet}"
        old_cat = doc.get("doc_type") or "other"

        # Rule 4.2: Cover Letter vs Formal Correspondence
        if any(k in fn for k in ["motivation", "candidature", "cover_letter", "coverletter", "bewerbungsschreiben", "motivationsschreiben"]) or \
           "lettre de motivation" in combined or "bewerbung um die stelle" in combined or \
           ("candidature" in combined and any(sal in combined for sal in ["madame, monsieur", "sehr geehrte damen und herren", "dear hiring manager"])):
            return "career_cover_letter", "Rule 4.2 (Cover Letter)", 0.95

        # Rule 4.4: CV / Resumes
        if (re.search(r'\b(cv|curriculum[\s_-]*vitae|lebenslauf|resume)\b', fn) or "parcours" in fn) and \
           not any(k in fn for k in ["certificat", "zeugnis", "attestation", "diplom"]):
            return "career_cv", "Rule 4.4 (CV / Resume Filename)", 0.96

        if "curriculum vitae" in snippet or "lebenslauf" in snippet or \
           ("expérience professionnelle" in combined and "formation" in combined) or \
           ("berufserfahrung" in combined and "ausbildung" in combined):
            return "career_cv", "Rule 4.4 (CV Content)", 0.92

        # Rule 4.3: Portfolios & Case Studies vs Technical Architecture
        if any(k in fn for k in ["portfolio", "arbeitsproben", "projektdokumentation", "case_study", "casestudy"]) or \
           "work samples" in combined or "dossier de réalisations" in combined:
            return "career_portfolio", "Rule 4.3 (Work Portfolio)", 0.93

        # Rule 4.5: Professional Profile vs CV
        if any(k in fn for k in ["profil", "profile", "executive_bio", "kurzprofil"]) and \
           any(k in combined for k in ["linkedin", "professionnel", "kurzprofil", "executive bio", "about me"]) and \
           not re.search(r'\b(cv|curriculum)\b', fn):
            return "career_profile", "Rule 4.5 (Professional Profile)", 0.90

        # Rule 4.4: Employer Reference letters (retain or move to identity_credentials)
        if any(k in combined for k in ["certificat de travail", "arbeitszeugnis", "arbeitsbestätigung", "reference letter"]):
            return "identity_credentials", "Rule 4.4 (Employer Reference)", 0.95

        return old_cat, "Unchanged Baseline", 0.70

    def evolve_ledger(self,
                      dry_run: bool = True,
                      limit: int = 500,
                      source_root_filter: Optional[str] = None,
                      target_version: str = "v1.0.0") -> Dict[str, Any]:
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
                   fl.relative_path, fl.storage_root
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

