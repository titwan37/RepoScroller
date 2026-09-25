"""Context-aware document chunker for Knowledge Base embedding and RAG retrieval."""

import re
from typing import List, Dict, Any, Optional
from reposcroller.config import settings


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
                       storage_root: str = "") -> List[Dict[str, Any]]:
        """Splits document text into overlapping token chunks with prepended metadata header."""
        if not text or not text.strip():
            return []

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
