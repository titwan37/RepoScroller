"""Text and structural metadata extractor supporting PDF, EML, Markdown, and TXT."""

import email
from email import policy
from pathlib import Path
from typing import Dict, Any, Tuple
import pymupdf


def extract_document_data(file_path: Path) -> Tuple[str, Dict[str, Any]]:
    """Extract raw text and structural metadata from a supported document file."""
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(file_path)
    elif ext in [".txt", ".md"]:
        return _extract_text_file(file_path)
    elif ext == ".eml":
        return _extract_eml(file_path)
    else:
        # Fallback for unrecognized text files
        return _extract_text_file(file_path)


def _extract_pdf(file_path: Path) -> Tuple[str, Dict[str, Any]]:
    """Extract text, page count, digital signature presence, and metadata from PDF."""
    text_parts = []
    metadata: Dict[str, Any] = {
        "page_count": 0,
        "has_digital_signature": False,
        "author": None,
        "title": None,
        "creation_date": None,
    }

    try:
        doc = pymupdf.open(str(file_path))
        metadata["page_count"] = len(doc)
        meta = doc.metadata or {}
        metadata["author"] = meta.get("author")
        metadata["title"] = meta.get("title")
        metadata["creation_date"] = meta.get("creationDate")

        # Check for signature fields
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text_parts.append(page.get_text())

            # Detect interactive form fields / signature widgets
            for widget in page.widgets():
                if widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                    metadata["has_digital_signature"] = True

        doc.close()
    except Exception as e:
        metadata["extraction_error"] = str(e)

    full_text = "\n".join(text_parts).strip()
    return full_text, metadata


def _extract_text_file(file_path: Path) -> Tuple[str, Dict[str, Any]]:
    """Extract text from plain text or markdown files."""
    metadata: Dict[str, Any] = {
        "page_count": 1,
        "has_digital_signature": False,
    }
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception as e:
        text = ""
        metadata["extraction_error"] = str(e)

    return text.strip(), metadata


def _extract_eml(file_path: Path) -> Tuple[str, Dict[str, Any]]:
    """Extract email headers and body text from .eml files."""
    metadata: Dict[str, Any] = {
        "page_count": 1,
        "has_digital_signature": False,
        "attachments": [],
    }
    try:
        with open(file_path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        metadata["subject"] = msg.get("subject")
        metadata["from"] = msg.get("from")
        metadata["to"] = msg.get("to")
        metadata["date"] = msg.get("date")

        body_parts = []
        for part in msg.walk():
            content_type = part.get_content_type()
            filename = part.get_filename()
            if filename:
                metadata["attachments"].append(filename)
            elif content_type in ["text/plain", "text/markdown"]:
                payload = part.get_payload(decode=True)
                if payload:
                    body_parts.append(payload.decode("utf-8", errors="replace"))

        text = "\n\n".join(body_parts)
    except Exception as e:
        text = ""
        metadata["extraction_error"] = str(e)

    return text.strip(), metadata
