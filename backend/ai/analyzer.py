"""Document Intelligence and Cascaded LLM Categorizer for legal, financial, and procedural documents."""

import re
import json
import time
import logging
from typing import List, Optional, Dict, Any
import httpx
from pydantic import BaseModel, Field
from backend.config import settings

logger = logging.getLogger("analyzer")


class DocumentAnalysisResult(BaseModel):
    """Structured document intelligence output."""
    document_category: str = Field(
        default="other",
        description="Canonical taxonomy slug e.g. 'employment_contract', 'court_order', 'tax_assessment'"
    )
    title: str = Field(default="", description="Formal or inferred document title")
    governing_date: Optional[str] = Field(default=None, description="ISO Date YYYY-MM-DD")
    parties_involved: List[str] = Field(default_factory=list, description="Entities, signers, or institutions")
    summary: str = Field(default="", description="Concise 1-2 sentence description")
    lifecycle_status: str = Field(default="final", description="draft, review, final, superseded")
    confidence_score: float = Field(default=0.7, description="Confidence score 0.0 - 1.0")
    new_category_meta: Optional[Dict[str, Any]] = Field(default=None, description="Multilingual metadata if LLM discovered a novel category")


class DocumentAnalyzer:
    """Cascaded Document Intelligence Analyzer (LLM + Rule-Based Heuristic Fallback)."""

    def __init__(self,
                 provider: Optional[str] = None,
                 openrouter_key: Optional[str] = None,
                 ollama_url: Optional[str] = None,
                 ollama_model: Optional[str] = None,
                 taxonomy_manager=None):
        self.provider = provider or settings.LLM_PROVIDER
        self.openrouter_key = openrouter_key or settings.OPENROUTER_API_KEY
        self._custom_ollama_url = ollama_url
        self._custom_ollama_model = ollama_model
        from backend.ai.taxonomy import TaxonomyManager
        self.taxonomy = taxonomy_manager or TaxonomyManager()

    @property
    def ollama_url(self) -> str:
        """Target Ollama base URL dynamically resolved from backend.active chat routing (PC1 vs PC2)."""
        return (self._custom_ollama_url or settings.chat_url).rstrip("/")

    @property
    def ollama_model(self) -> str:
        """Target LLM model dynamically resolved: OLLAMA_MODEL_PC1 (3b) on PC1 vs OLLAMA_MODEL_PC2 (8b) on PC2."""
        return self._custom_ollama_model or settings.chat_model

    def analyze(self,
                text: str,
                filename: str,
                metadata: Optional[Dict[str, Any]] = None) -> DocumentAnalysisResult:
        """Run cascaded analysis: attempt LLM router if configured; fallback to robust heuristics."""
        metadata = metadata or {}

        # 1. Try OpenRouter if key is present
        if (self.provider in ["auto", "openrouter"]) and self.openrouter_key:
            try:
                res = self._call_openrouter(text, filename)
                if res:
                    self._check_and_register_new_category(res)
                    return res
            except Exception as e:
                logger.warning(f"OpenRouter analysis failed: {e}. Falling back...")

        # 2. Try Ollama if configured
        if (self.provider in ["auto", "ollama"]):
            try:
                res = self._call_ollama(text, filename)
                if res:
                    self._check_and_register_new_category(res)
                    return res
            except Exception as e:
                logger.debug(f"Ollama offline/unavailable: {e}. Falling back...")

        # 3. Deterministic Heuristic Categorizer (Offline / High-Speed)
        return self._heuristic_analyze(text, filename, metadata)

    def _check_and_register_new_category(self, result: DocumentAnalysisResult):
        """Auto-register novel topics discovered by the LLM into the global taxonomy."""
        if result.new_category_meta and result.document_category:
            meta = result.new_category_meta
            from backend.ai.taxonomy import TaxonomyCategory
            cat = TaxonomyCategory(
                category_id=result.document_category,
                parent_id=meta.get("parent_id"),
                name_en=meta.get("name_en", result.document_category),
                name_fr=meta.get("name_fr", result.document_category),
                name_de=meta.get("name_de", result.document_category),
                description=meta.get("description", "Auto-discovered category"),
                keywords=meta.get("keywords", [])
            )
            self.taxonomy.upsert_category(cat)
            logger.info(f"Dynamically extended taxonomy with novel category: {cat.category_id}")

    def _build_prompt(self, text: str, filename: str) -> str:
        snippet = text[:4000]
        taxonomy_guide = self.taxonomy.format_taxonomy_for_prompt()

        return f"""You are an ALCOA+ document intelligence engine for a multilingual repository (English, French, German).
Analyze the following document and classify it into the global taxonomy, or extend the taxonomy if this represents a distinct novel topic.

Active Global Multilingual Taxonomy:
{taxonomy_guide}

Filename: {filename}
Text Snippet:
\"\"\"
{snippet}
\"\"\"

Instructions:
1. Choose the most specific matching `category_id` from the active taxonomy above.
2. If the document represents a genuinely distinct topic NOT adequately covered, propose a new canonical slug for `document_category` and provide `new_category_meta` with 'name_en', 'name_fr', 'name_de', and 'parent_id' (or null).

Return ONLY a valid JSON object matching this schema:
{{
  "document_category": "<category_id slug>",
  "title": "<inferred document title>",
  "governing_date": "<YYYY-MM-DD or null>",
  "parties_involved": ["<party 1>", "<party 2>"],
  "summary": "<concise 1-2 sentence summary>",
  "lifecycle_status": "draft" | "review" | "final" | "superseded",
  "confidence_score": <float between 0.0 and 1.0>,
  "new_category_meta": null | {{
     "parent_id": "<parent_slug_or_null>",
     "name_en": "...",
     "name_fr": "...",
     "name_de": "...",
     "description": "...",
     "keywords": ["..."]
  }}
}}
"""

    def _call_openrouter(self, text: str, filename: str) -> Optional[DocumentAnalysisResult]:
        prompt = self._build_prompt(text, filename)
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/titwan37/RepoScroller",
            "X-Title": "RepoScroller",
        }
        payload = {
            "model": settings.OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        t0 = time.time()
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    elapsed_ms = (time.time() - t0) * 1000
                    from backend.ai.telemetry import workload_telemetry
                    workload_telemetry.record_chat(latency_ms=elapsed_ms, success=True)
                    raw_json = resp.json()["choices"][0]["message"]["content"]
                    data = json.loads(raw_json)
                    return DocumentAnalysisResult(**data)
        except Exception:
            elapsed_ms = (time.time() - t0) * 1000
            from backend.ai.telemetry import workload_telemetry
            workload_telemetry.record_chat(latency_ms=elapsed_ms, success=False)
            raise
        return None

    def _call_ollama(self, text: str, filename: str) -> Optional[DocumentAnalysisResult]:
        import time
        t0 = time.time()
        prompt = self._build_prompt(text, filename)
        url = f"{self.ollama_url}/api/chat"
        target_model = self.ollama_model
        payload = {
            "model": target_model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": 0.1,
                "num_ctx": getattr(settings, "OLLAMA_NUM_CTX", 2048)
            }
        }
        try:
            with httpx.Client(timeout=settings.OLLAMA_TIMEOUT) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    elapsed_ms = (time.time() - t0) * 1000
                    from backend.ai.telemetry import workload_telemetry
                    workload_telemetry.record_chat(
                        latency_ms=elapsed_ms,
                        success=True,
                        node=workload_telemetry.chat_active_node,
                        model=target_model
                    )
                    raw_json = resp.json()["message"]["content"]
                    data = json.loads(raw_json)
                    return DocumentAnalysisResult(**data)
        except Exception:
            elapsed_ms = (time.time() - t0) * 1000
            from backend.ai.telemetry import workload_telemetry
            workload_telemetry.record_chat(
                latency_ms=elapsed_ms,
                success=False,
                node=workload_telemetry.chat_active_node,
                model=target_model
            )
            raise
        return None

    def _heuristic_analyze(self,
                           text: str,
                           filename: str,
                           metadata: Dict[str, Any]) -> DocumentAnalysisResult:
        """Deterministic multilingual heuristic classifier for Swiss & international documents."""
        path_str = str(metadata.get("path") or metadata.get("relative_path") or metadata.get("storage_root") or "").lower()
        combined = f"{filename}\n{path_str}\n{text[:3000]}".lower()

        category = "other"
        confidence = 0.70

        # Match against active multilingual taxonomy (EN, FR, DE)
        best_category = "other"
        best_score = 0.50

        try:
            for cat in self.taxonomy.get_all_categories():
                matched_kw = 0
                for kw in cat.keywords:
                    kw_clean = kw.lower().strip()
                    # Match word boundary (safe across languages, avoids 'rent' matching 'different', 'lease' matching 'please')
                    if re.search(rf"\b{re.escape(kw_clean)}\b", combined):
                        matched_kw += 1
                    # Or match German compound noun fragments for long stems (>= 6 chars, excluding common English words)
                    elif len(kw_clean) >= 6 and kw_clean not in {"tenant", "agreement", "covenant", "candidature", "position"} and kw_clean in combined:
                        matched_kw += 1

                if matched_kw > 0:
                    score = min(0.95, 0.72 + (0.08 * matched_kw))
                    # Prioritize specific subcategories over broad parents
                    if cat.parent_id:
                        score += 0.05
                    if score > best_score:
                        best_score = score
                        best_category = cat.category_id
        except Exception:
            pass

        # Disambiguation Precedence Rules (Section 4 of taxonomy-v1.0.0.skill.md)
        fn_lower = filename.lower()
        fn_split = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', filename)
        fn_split = re.sub(r'([0-9]+)([a-zA-Z]+)', r'\1 \2', fn_split)
        fn_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', fn_split)
        fn_tokens = re.sub(r'[_.\-]+', ' ', fn_split).lower()
        is_reference = any(k in fn_lower for k in ["certificat de travail", "arbeitszeugnis", "arbeitsbestätigung", "reference letter", "reference_letter"])

        # 1. TOP PRIORITY: Curriculum Vitae & Lebenslauf (Rule 4.1)
        if not is_reference and (
            re.search(r'(?:^|[^a-z0-9])(cv|curriculum[\s_-]*vitae|lebenslauf|resume)(?:[^a-z0-9]|$)', fn_lower) or
            re.search(r'\b(cv|curriculum|lebenslauf|resume)\b', fn_tokens) or
            any(k in fn_lower for k in ["_cv_", "-cv-", "_cv.", "-cv.", "cv_", "cv-", "lebenslauf", "curriculum_vitae", "curriculum-vitae"]) or
            re.search(r'\b(curriculum vitae|lebenslauf)\b', combined) or
            (("experience" in combined or "berufserfahrung" in combined or "parcours" in combined) and
             ("education" in combined or "ausbildung" in combined or "formation" in combined) and
             any(p in path_str for p in ["cv", "resume", "lebenslauf"])) or
            (any(p in path_str for p in ["2025-cv", "2026-cv", "/cv/", "\\cv\\"]) and not any(k in fn_lower for k in ["jobdescription", "application_letter", "cover_letter"]))
        ):
            best_category = "career_cv"
            best_score = max(best_score, 0.98)
        elif any(k in fn_lower for k in [
            "jobdescription", "job_description", "job-description", "job description",
            "stellenbeschreibung", "stellenausschreibung", "stelleninserat", "fiche_de_poste", "fiche de poste"
        ]) or \
           "job details:----------job_title:" in combined or \
           ("job details" in combined and any(k in combined for k in ["job_title", "company_name", "job_url", "short_description"])) or \
           any(phrase in combined for phrase in [
               "job description", "stellenbeschreibung", "stellenausschreibung", "stelleninserat",
               "anforderungsprofil", "aufgaben und anforderungen", "wir suchen per sofort",
               "deine aufgaben als", "ihre aufgaben als", "profil recherché", "description du poste"
           ]) or \
           (any(p in combined for p in ["positions", "rav"]) and any(k in combined for k in ["job_title", "job details", "engineer", "entwickler", "architect"])):
            best_category = "career_job_description"
            best_score = max(best_score, 0.96)
        elif any(k in fn_lower for k in [
            "motivation", "candidature", "cover_letter", "coverletter", "cover-letter",
            "application_letter", "applicationletter", "application-letter", "application letter",
            "bewerbungsschreiben", "motivationsschreiben", "bewerbung"
        ]) or \
           any(phrase in combined for phrase in [
               "lettre de motivation", "lettre de candidature", "bewerbung um die stelle",
               "bewerbung als", "bewerbung für die stelle", "bewerbung auf die stelle",
               "bewerbung auf ihre stellenausschreibung", "stellenbewerbung", "initiativbewerbung",
               "application letter", "letter of application"
           ]) or \
           (("candidature" in combined or "bewerbung" in combined or "application" in combined) and
            any(sal in combined for sal in [
                "madame, monsieur", "sehr geehrte damen und herren", "sehr geehrte",
                "dear hiring manager", "hiring manager", "z.h. hiring manager",
                "recruiting team", "talent acquisition"
            ])):
            best_category = "career_cover_letter"
            best_score = max(best_score, 0.95)
        elif any(k in fn_lower for k in ["portfolio", "arbeitsproben", "projektdokumentation", "case_study", "casestudy"]) or \
             "work samples" in combined or "dossier de réalisations" in combined:
            best_category = "career_portfolio"
            best_score = max(best_score, 0.93)
        elif any(k in fn_lower for k in ["profil", "profile", "executive_bio", "kurzprofil"]) and \
             not re.search(r'\b(cv|curriculum)\b', fn_lower):
            best_category = "career_profile"
            best_score = max(best_score, 0.92)
        elif any(k in combined for k in ["certificat de travail", "arbeitszeugnis", "arbeitsbestätigung", "reference letter"]):
            best_category = "identity_credentials"
            best_score = max(best_score, 0.95)
        elif any(k in combined for k in ["kontoauszug", "bankauszug", "zinsausweis", "schuldzinsen", "hypothekarauszug", "relevé bancaire", "zuger kantonalbank", "postfinance"]) or \
             any(k in fn_lower for k in ["kontoauszug", "zinsabrechnung", "zinsausweis", "bankauszug", "schuldzinsen", "hypothek", "banküberweisung"]):
            best_category = "financial_banking"
            best_score = max(best_score, 0.94)

        category = best_category
        confidence = round(best_score, 2)

        # Date extraction
        gov_date = None
        date_match = re.search(r"\b(20\d{2})[-_/.](0[1-9]|1[0-2])[-_/.](0[1-9]|[12]\d|3[01])\b", combined)
        if date_match:
            gov_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
        elif "creation_date" in metadata and metadata["creation_date"]:
            gov_date = str(metadata["creation_date"])[:10]

        # Extract parties
        parties = []
        party_match = re.search(r"(?:between|zwischen|entre)\s+([A-Z][a-zA-Z\s]+?)\s+(?:and|und|et)\s+([A-Z][a-zA-Z\s]+?)(?:[.,\n]|$)", text[:1500])
        if party_match:
            p1 = party_match.group(1).strip()
            p2 = party_match.group(2).strip()
            if len(p1) < 40 and len(p2) < 40:
                parties = [p1, p2]

        # Lifecycle status
        status = "final"
        if re.search(r"(\bdraft\b|brouillon|entwurf|temp|wip|_draft)", combined):
            status = "draft"
        elif re.search(r"(\bpartial\b|truncated|\[cut\]|\[truncated\])", combined):
            status = "truncated"

        # Inferred Title (stripping previous category tags or chunk headers)
        cleaned_lines = []
        for line in text.splitlines():
            l_str = line.strip()
            if len(l_str) > 3:
                l_str = re.sub(r"^\[(?:Document:[^\]]+|[A-Z_]+)\]\s*", "", l_str).strip()
                l_str = re.sub(r"^(?:[A-Za-z\s]+document regarding\s*)", "", l_str, flags=re.IGNORECASE).strip()
                if len(l_str) > 3:
                    cleaned_lines.append(l_str)
        title = cleaned_lines[0][:80] if cleaned_lines else filename

        summary = f"{category.replace('_', ' ').title()} document regarding {title[:50]}."
        if gov_date:
            summary += f" Date: {gov_date}."

        return DocumentAnalysisResult(
            document_category=category,
            title=title,
            governing_date=gov_date,
            parties_involved=parties,
            summary=summary,
            lifecycle_status=status,
            confidence_score=confidence
        )
