"""Document Intelligence and Cascaded LLM Categorizer for legal, financial, and procedural documents."""

import re
import json
import logging
from typing import List, Optional, Dict, Any
import httpx
from pydantic import BaseModel, Field
from reposcroller.config import settings

logger = logging.getLogger("reposcroller.analyzer")


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
                 taxonomy_manager=None):
        self.provider = provider or settings.LLM_PROVIDER
        self.openrouter_key = openrouter_key or settings.OPENROUTER_API_KEY
        self.ollama_url = (ollama_url or settings.OLLAMA_BASE_URL).rstrip("/")
        from reposcroller.ai.taxonomy import TaxonomyManager
        self.taxonomy = taxonomy_manager or TaxonomyManager()

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
            from reposcroller.ai.taxonomy import TaxonomyCategory
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
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                raw_json = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(raw_json)
                return DocumentAnalysisResult(**data)
        return None

    def _call_ollama(self, text: str, filename: str) -> Optional[DocumentAnalysisResult]:
        prompt = self._build_prompt(text, filename)
        url = f"{self.ollama_url}/api/chat"
        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0.1}
        }
        with httpx.Client(timeout=settings.OLLAMA_TIMEOUT) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                raw_json = resp.json()["message"]["content"]
                data = json.loads(raw_json)
                return DocumentAnalysisResult(**data)
        return None

    def _heuristic_analyze(self,
                           text: str,
                           filename: str,
                           metadata: Dict[str, Any]) -> DocumentAnalysisResult:
        """Deterministic multilingual heuristic classifier for Swiss & international documents."""
        combined = f"{filename}\n{text[:3000]}".lower()

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
                    # Match word boundary OR compound noun prefix/suffix (e.g. Steueramt, Mietvertrag)
                    if len(kw_clean) >= 4 and kw_clean in combined:
                        matched_kw += 1
                    elif re.search(rf"\b{re.escape(kw_clean)}\b", combined):
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

        # Inferred Title
        lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 3]
        title = lines[0][:80] if lines else filename

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
