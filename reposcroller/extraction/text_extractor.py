"""Text and structural metadata extractor supporting PDF, DOCX, EML, Markdown, and TXT."""

import email
from email import policy
from pathlib import Path
from typing import Dict, Any, Tuple
import logging
import pymupdf
import zipfile
import xml.etree.ElementTree as ET

logger = logging.getLogger("reposcroller.extraction")


def extract_document_data(file_path: Path) -> Tuple[str, Dict[str, Any]]:
    """Extract raw text and structural metadata from a supported document file."""
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(file_path)
    elif ext == ".docx":
        return _extract_docx(file_path)
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
        logger.error(f"PDF extraction failed for '{file_path.name}' ({file_path}): {e}")
        metadata["extraction_error"] = str(e)

    full_text = "\n".join(text_parts).strip()
    return full_text, metadata


def _extract_docx(file_path: Path) -> Tuple[str, Dict[str, Any]]:
    """Extract clean readable text and document properties from Microsoft Word .docx files."""
    metadata: Dict[str, Any] = {
        "page_count": 1,
        "has_digital_signature": False,
        "author": None,
        "title": None,
        "creation_date": None,
    }
    paragraphs = []

    try:
        with zipfile.ZipFile(file_path, "r") as docx_zip:
            # 1. Parse main body text from word/document.xml
            if "word/document.xml" in docx_zip.namelist():
                xml_data = docx_zip.read("word/document.xml")
                root = ET.fromstring(xml_data)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                
                # Iterate through paragraph elements
                for p_elem in root.iterfind(".//w:p", ns):
                    runs = []
                    for t_elem in p_elem.iterfind(".//w:t", ns):
                        if t_elem.text:
                            runs.append(t_elem.text)
                    if runs:
                        p_text = "".join(runs).strip()
                        if p_text:
                            paragraphs.append(p_text)

            # 2. Extract core metadata from docProps/core.xml
            if "docProps/core.xml" in docx_zip.namelist():
                core_data = docx_zip.read("docProps/core.xml")
                core_root = ET.fromstring(core_data)
                for elem in core_root.iter():
                    tag = elem.tag.lower()
                    if "creator" in tag or "author" in tag:
                        metadata["author"] = elem.text
                    elif "title" in tag:
                        metadata["title"] = elem.text
                    elif "created" in tag or "date" in tag:
                        metadata["creation_date"] = elem.text

    except Exception as e:
        logger.error(f"DOCX extraction failed for '{file_path.name}' ({file_path}): {e}")
        metadata["extraction_error"] = str(e)

    full_text = "\n\n".join(paragraphs).strip()
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
        logger.error(f"Text file read failed for '{file_path.name}' ({file_path}): {e}")
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
        logger.error(f"EML extraction failed for '{file_path.name}' ({file_path}): {e}")
        text = ""
        metadata["extraction_error"] = str(e)

    return text.strip(), metadata

