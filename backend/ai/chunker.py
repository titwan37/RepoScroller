"""Context-aware document chunker for Knowledge Base embedding and RAG retrieval."""

import re
from typing import List, Dict, Any, Optional
from backend.config import settings


class DocumentChunker:
    """Splits full document text into semantic chunks with context headers and overlap."""

    def __init__(self,
                 chunk_size_tokens: Optional[int] = None,
                 chunk_overlap_tokens: Optional[int] = None):
        self.chunk_size = chunk_size_tokens or settings.CHUNK_SIZE_TOKENS
        self.chunk_overlap = chunk_overlap_tokens or settings.CHUNK_OVERLAP_TOKENS

    def chunk_document(self,
                       text: str,
                       sha256_hash: str,
                       canonical_filename: str = "",
                       doc_type: str = "",
                       doc_date: str = "",
                       storage_root: str = "",
                       articles: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Splits document text into overlapping token chunks or structured legal article chunks."""
        if articles:
            return self.chunk_legal_statute(
                articles=articles,
                sha256_hash=sha256_hash,
                canonical_filename=canonical_filename,
                storage_root=storage_root,
            )

        if not text or not text.strip():
            return []

        # Auto-detect Fedlex formatted passages (e.g. from get_document_full_text or statute documents)
        if not articles and (doc_type == "statute_legislation" or text.startswith("passage: ")):
            passages = [p.strip() for p in re.split(r'\n{2,}(?=passage: )', text.strip()) if p.strip()]
            if len(passages) > 0 and passages[0].startswith("passage: "):
                parsed_articles = []
                for p in passages:
                    m_sr = re.search(r'SR\s*(\d+(?:\.\d+)?)', p)
                    sr_code = m_sr.group(1) if m_sr else "UNKNOWN"
                    m_art = re.search(r'(Art\.?\s*\d+[a-z]?)', p)
                    art_num = m_art.group(1) if m_art else "Art."
                    binding_key = f"{sr_code}_{art_num}"
                    parsed_articles.append({
                        "sr_code": sr_code,
                        "article_num": art_num,
                        "binding_key": binding_key,
                        "full_text": p,
                        "paragraphs": [p],
                    })
                return self.chunk_legal_statute(
                    articles=parsed_articles,
                    sha256_hash=sha256_hash,
                    canonical_filename=canonical_filename,
                    storage_root=storage_root,
                )

        # Create context header to prepend to every chunk
        header_parts = []
        if canonical_filename:
            header_parts.append(f"Document: {canonical_filename}")
        if doc_type:
            header_parts.append(f"Category: {doc_type.upper()}")
        if doc_date:
            header_parts.append(f"Date: {doc_date}")
        if storage_root:
            header_parts.append(f"Source: {storage_root}")

        header = f"[{' | '.join(header_parts)}]\n" if header_parts else ""

        # Break text into paragraphs/sections first to preserve semantic boundaries
        paragraphs = re.split(r'\n{2,}', text.strip())
        words: List[str] = []
        for p in paragraphs:
            p_words = p.split()
            if p_words:
                words.extend(p_words)
                words.append("\n\n")

        if not words:
            return []

        chunks: List[Dict[str, Any]] = []
        step = max(1, self.chunk_size - self.chunk_overlap)
        idx = 0
        chunk_index = 0

        while idx < len(words):
            window_words = words[idx:idx + self.chunk_size]
            chunk_body = " ".join(window_words).replace(" \n\n ", "\n\n").strip()
            if chunk_body:
                full_chunk_text = f"{header}{chunk_body}".strip()
                chunks.append({
                    "chunk_id": f"{sha256_hash}_{chunk_index}",
                    "sha256_hash": sha256_hash,
                    "chunk_index": chunk_index,
                    "chunk_text": full_chunk_text,
                    "token_count": len(window_words),
                    "canonical_filename": canonical_filename,
                    "doc_type": doc_type,
                    "doc_date": doc_date,
                })
                chunk_index += 1

            idx += step

        return chunks

    def chunk_legal_statute(self,
                            articles: List[Dict[str, Any]],
                            sha256_hash: str,
                            canonical_filename: str = "",
                            storage_root: str = "") -> List[Dict[str, Any]]:
        """Chunk a structured legal statute at article granularity with full legal metadata."""
        if not articles:
            return []

        chunks: List[Dict[str, Any]] = []
        for idx, art in enumerate(articles):
            binding_key = art.get("binding_key", f"art_{idx}")
            sr_code = art.get("sr_code", "")
            art_num = art.get("article_num", "")
            lang = art.get("lang", "fr")
            title = art.get("title", "")
            short_form = art.get("short_form", "")
            article_heading = art.get("article_heading", "")
            full_text = art.get("full_text", "")
            pdf_ref = art.get("pdf_reference_path", "")

            # If full_text isn't formatted, assemble passage header
            if not full_text:
                heading_str = f" — {article_heading}" if article_heading else ""
                short_label = f" ({short_form} SR {sr_code})" if short_form else f" (SR {sr_code})"
                text_content = art.get("text_content") or " ".join(art.get("paragraphs", []))
                full_text = f"passage: {title}{short_label}, {art_num}{heading_str}: {text_content}".strip()

            words = full_text.split()
            # If article is small/medium (fits in 1.5 * chunk_size), keep intact as 1 chunk
            if len(words) <= int(self.chunk_size * 1.5):
                chunks.append({
                    "chunk_id": f"{sha256_hash}_{binding_key}_0",
                    "sha256_hash": sha256_hash,
                    "chunk_index": idx,
                    "chunk_text": full_text,
                    "token_count": len(words),
                    "canonical_filename": canonical_filename,
                    "doc_type": "statute_legislation",
                    "sr_code": sr_code,
                    "article_num": art_num,
                    "binding_key": binding_key,
                    "lang": lang,
                    "short_form": short_form,
                    "article_heading": article_heading,
                    "pdf_reference_path": pdf_ref,
                })
            else:
                # Exceptionally long article: split into sub-paragraph chunks preserving header
                paragraphs = art.get("paragraphs") or [full_text]
                header = f"passage: {title} ({short_form} SR {sr_code}), {art_num} — {article_heading} (Cont.):\n"
                sub_idx = 0
                for p in paragraphs:
                    p_text = p.strip()
                    if not p_text:
                        continue
                    chunks.append({
                        "chunk_id": f"{sha256_hash}_{binding_key}_{sub_idx}",
                        "sha256_hash": sha256_hash,
                        "chunk_index": idx * 100 + sub_idx,
                        "chunk_text": f"{header}{p_text}".strip(),
                        "token_count": len(p_text.split()),
                        "canonical_filename": canonical_filename,
                        "doc_type": "statute_legislation",
                        "sr_code": sr_code,
                        "article_num": art_num,
                        "binding_key": binding_key,
                        "lang": lang,
                        "short_form": short_form,
                        "article_heading": article_heading,
                        "pdf_reference_path": pdf_ref,
                    })
                    sub_idx += 1

        return chunks
