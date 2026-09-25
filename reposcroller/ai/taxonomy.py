"""Global Multilingual Taxonomy Manager & LLM Dynamic Topic Refiner (EN, FR, DE)."""

import json
import logging
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
        "name_en": "Identity, Credentials & CVs",
        "name_fr": "Identité, Diplômes & CV",
        "name_de": "Identitätsnachweise, Zeugnisse & Lebenslauf",
        "description": "Resumes, certificates, diplomas, ID scans, employment references.",
        "keywords": ["cv", "resume", "diploma", "passport", "diplôme", "attestation", "certificat", "lebenslauf", "arbeitszeugnis"]
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
        """Seed baseline multilingual categories if table is empty."""
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
        self.conn.commit()
        cur.execute("SELECT COUNT(*) FROM global_taxonomy")
        if cur.fetchone()[0] == 0:
            for item in DEFAULT_TAXONOMY:
                self.upsert_category(TaxonomyCategory(
                    category_id=item["category_id"],
                    parent_id=item["parent_id"],
                    name_en=item["name_en"],
                    name_fr=item["name_fr"],
                    name_de=item["name_de"],
                    description=item["description"],
                    keywords=item["keywords"],
                ))

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
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": settings.OLLAMA_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "format": "json",
                        "stream": False
                    }
                )
                if resp.status_code == 200:
                    content = resp.json()["message"]["content"]
                    return json.loads(content)
        except Exception:
            pass

        return None
