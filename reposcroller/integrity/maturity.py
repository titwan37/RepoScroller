"""Heuristic version and document maturity scoring engine (ALCOA+ Accurate/Complete)."""

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from reposcroller.config import settings


class MaturityEvaluator:
    """Evaluates document completeness, signature evidence, naming signals, and lifecycle status."""

    def __init__(self,
                 w_completeness: float = None,
                 w_signatures: float = None,
                 w_date: float = None,
                 w_naming: float = None):
        self.w_completeness = w_completeness if w_completeness is not None else settings.MATURITY_WEIGHT_COMPLETENESS
        self.w_signatures = w_signatures if w_signatures is not None else settings.MATURITY_WEIGHT_SIGNATURES
        self.w_date = w_date if w_date is not None else settings.MATURITY_WEIGHT_DATE
        self.w_naming = w_naming if w_naming is not None else settings.MATURITY_WEIGHT_NAMING

        # Ensure weights sum to 1.0
        total_w = self.w_completeness + self.w_signatures + self.w_date + self.w_naming
        if total_w > 0:
            self.w_completeness /= total_w
            self.w_signatures /= total_w
            self.w_date /= total_w
            self.w_naming /= total_w

    def evaluate(self,
                 file_path: Path,
                 text: str,
                 metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Compute the composite MaturityScore and classify lifecycle status."""
        metadata = metadata or {}
        filename = file_path.name.lower()

        completeness_score, truncation_detected = self._score_completeness(text, metadata)
        signature_score = self._score_signatures(text, metadata)
        naming_score, version_tag = self._score_naming(filename)
        date_score, doc_date = self._score_date(filename, text, metadata)

        composite_score = (
            self.w_completeness * completeness_score +
            self.w_signatures * signature_score +
            self.w_naming * naming_score +
            self.w_date * date_score
        )
        composite_score = round(max(0.0, min(1.0, composite_score)), 4)

        lifecycle_status = self._determine_lifecycle(
            composite_score=composite_score,
            naming_score=naming_score,
            signature_score=signature_score,
            truncation_detected=truncation_detected,
            filename=filename
        )

        return {
            "maturity_score": composite_score,
            "lifecycle_status": lifecycle_status,
            "completeness_score": completeness_score,
            "signature_score": signature_score,
            "naming_score": naming_score,
            "date_score": date_score,
            "detected_date": doc_date,
            "version_tag": version_tag,
            "truncation_detected": truncation_detected,
        }

    def _score_completeness(self, text: str, metadata: Dict[str, Any]) -> Tuple[float, bool]:
        """Score document completeness based on length, page markers, and end blocks."""
        if not text or len(text.strip()) < 50:
            return 0.1, True

        score = 0.5
        text_lower = text.lower()
        page_count = metadata.get("page_count", 1)

        # Check closing/signature blocks in German, French, English
        end_indicators = [
            r"unterschrift", r"unterzeichnet", r"gez\.", r"signature", r"signé",
            r"sincerely", r"cordialement", r"mit freundlichen grüssen",
            r"hochachtungsvoll", r"fait à", r"ort, datum", r"conclusion",
            r"seite \d+ von \d+", r"page \d+ of \d+"
        ]
        found_indicators = sum(1 for pat in end_indicators if re.search(pat, text_lower[-1500:]))
        if found_indicators > 0:
            score += min(0.35, 0.15 * found_indicators)

        # Truncation signals
        truncation_signals = [
            r"\.{4,}", r"\[cut\]", r"\[truncated\]", r"\[suite au prochain\]",
            r"scan error", r"unvollständig"
        ]
        is_truncated = any(re.search(pat, text_lower) for pat in truncation_signals)
        if is_truncated:
            score -= 0.4

        if page_count > 1:
            score += 0.15

        return round(max(0.0, min(1.0, score)), 2), is_truncated

    def _score_signatures(self, text: str, metadata: Dict[str, Any]) -> float:
        """Detect digital signatures, notary stamps, or official seals."""
        score = 0.0

        # Check digital PDF signature flag from extractor
        if metadata.get("has_digital_signature"):
            return 1.0

        text_lower = text.lower()
        sig_stamps = [
            r"digital signiert", r"digitally signed", r"elektronische signatur",
            r"beglaubigt", r"notar", r"notariell", r"apostille", r"amtlicher stempel",
            r"sceau", r"legalisé", r"certifié conforme", r"qualifizierte elektronische"
        ]
        matches = sum(1 for pat in sig_stamps if re.search(pat, text_lower))
        if matches > 0:
            score += min(0.9, 0.45 * matches)
        else:
            # Weaker physical signature indicator
            weak_sig = [r"unterschrift", r"signature", r"gez\.", r"signé"]
            if any(re.search(pat, text_lower[-1000:]) for pat in weak_sig):
                score += 0.4

        return round(max(0.0, min(1.0, score)), 2)

    def _score_naming(self, filename: str) -> Tuple[float, Optional[str]]:
        """Score based on conventions like _final, _signed, _v2, vs _draft, _temp."""
        score = 0.5
        tag = None

        if re.search(r"(_|\b)(final|def|definitive|signed|signe|unterschrieben)(\.|\b)", filename):
            score += 0.4
            tag = "final"
        elif re.search(r"(_|\b)(v\d+(\.\d+)?|rev\d+)(\.|\b)", filename):
            match = re.search(r"(v\d+(\.\d+)?|rev\d+)", filename)
            tag = match.group(0) if match else "versioned"
            score += 0.2
        elif re.search(r"(_|\b)(draft|brouillon|entwurf|temp|tmp|wip)(\.|\b)", filename):
            score -= 0.35
            tag = "draft"
        elif re.search(r"(_|\b)(part|partial|tronque|truncated|copy|copie)(\.|\b)", filename):
            score -= 0.3
            tag = "partial"

        return round(max(0.0, min(1.0, score)), 2), tag

    def _score_date(self, filename: str, text: str, metadata: Dict[str, Any]) -> Tuple[float, Optional[str]]:
        """Detect and score document date relevance."""
        # 1. Search date in filename (YYYY-MM-DD or YYYYMMDD)
        date_match = re.search(r"(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])", filename)
        if date_match:
            doc_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
            return 0.8, doc_date

        # 2. Check metadata creation / mod date
        if "creation_date" in metadata and metadata["creation_date"]:
            return 0.7, str(metadata["creation_date"])[:10]

        # 3. Search in text
        text_date_match = re.search(r"\b(20\d{2})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", text[:2000])
        if text_date_match:
            doc_date = f"{text_date_match.group(1)}-{text_date_match.group(2)}-{text_date_match.group(3)}"
            return 0.6, doc_date

        return 0.4, None

    def _determine_lifecycle(self,
                             composite_score: float,
                             naming_score: float,
                             signature_score: float,
                             truncation_detected: bool,
                             filename: str) -> str:
        """Categorize into: draft, review, final, truncated."""
        if truncation_detected or "partial" in filename or "tronque" in filename:
            return "truncated"
        if naming_score >= 0.8 or signature_score >= 0.8 or composite_score >= 0.75:
            return "final"
        if naming_score <= 0.3 or "draft" in filename or "entwurf" in filename or composite_score < 0.4:
            return "draft"
        return "review"
