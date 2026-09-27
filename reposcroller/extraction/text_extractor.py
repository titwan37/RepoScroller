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
    import time
    t0 = time.time()
    
    # Ignore temporary/lock files (e.g., Microsoft Word ~$ files)
    if file_path.name.startswith("~$"):
        return "", {"extraction_error": "Skipped temporary lock file"}

    ext = file_path.suffix.lower()

    if ext == ".pdf":
        res = _extract_pdf(file_path)
    elif ext == ".docx":
        res = _extract_docx(file_path)
    elif ext in [".txt", ".md"]:
        res = _extract_text_file(file_path)
    elif ext == ".eml":
        res = _extract_eml(file_path)
    else:
        # Fallback for unrecognized text files
        res = _extract_text_file(file_path)

    elapsed_ms = (time.time() - t0) * 1000
    try:
        from reposcroller.ai.telemetry import workload_telemetry
        text_content, _ = res
        workload_telemetry.record_io_read(ext=ext, bytes_read=len(text_content.encode("utf-8")), latency_ms=elapsed_ms)
    except Exception:
        pass

    return res


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

LLM_Ontology_Expert = """
You are a domain-expert Knowledge Graph ontology engineer and data certifier for a legal, corporate, and document repository.

Extract structured entities and semantic relationships from the provided document text according to our strict entity taxonomy.

### ENTITY ONTOLOGY RULES:
1. "currency": Canonical monetary unit (ISO code or symbol).
   - ONLY allowed values: "CHF", "EUR", "USD", "GBP", "JPY".
   - Do NOT create nodes for raw numeric amounts (e.g., do NOT extract "1,200 CHF" or "$50,000").
2. "financial_pillar": High-level contractual financial classifications.
   - Standard categories:
     * "rent": Lease payments, rental income, tenant rent, storage rent.
     * "salary": Wages, base compensation, executive pay, director fees, bonuses.
     * "mortgage": Hypothek, property loans, secured debt instruments.
     * "fee": Advisory fees, retainer, transaction fees, management fees, notary charges.
     * "fine": Penalties, contractual damages, late charges, administrative sanctions.
     * "interest": Loan interest, compounding yield, coupon payments, late interest (Verzugszins).
     * "insurance_premium": Policy payments, social security contributions (AHV/ALV).
3. "organization": Bona fide corporate, institutional, or government bodies (e.g., "Swisscom AG", "Kantonales Steueramt Zürich"). Reject UI terms or technical phrases.
4. "person": Real human beings (First Last). Reject roles ("Landlord"), titles, or section labels.
5. "contract_type": Legal instrument classification (e.g., "Mietvertrag", "Employment Contract", "Loan Agreement").
6. "location": Standard cities or cantons (e.g., "Zurich", "Geneva", "Zug").
7. "statute": Legal code or article (e.g., "Art. 253 OR", "ZGB", "Art. 320 OR").

### RELATIONSHIP SCHEMA:
- (organization|person) -[:PAYS|RECEIVES]-> (financial_pillar)
- (financial_pillar) -[:DENOMINATED_IN]-> (currency)
- (contract_type) -[:INVOLVES_PAYMENT]-> (financial_pillar)
- (contract_type) -[:STIPULATES_CURRENCY]-> (currency)
- (financial_pillar) -[:GOVERNED_BY]-> (statute)

Document Text:
\"\"\"
{text}
\"\"\"

Output strictly valid JSON conforming to this structure:
{
  "entities": [
    {"type": "currency", "name": "CHF"},
    {"type": "financial_pillar", "name": "rent"},
    {"type": "person", "name": "Jane Doe"},
    {"type": "organization", "name": "Immobilien AG"}
  ],
  "relationships": [
    {"source": "Jane Doe", "target": "rent", "relation": "PAYS"},
    {"source": "Immobilien AG", "target": "rent", "relation": "RECEIVES"},
    {"source": "rent", "target": "CHF", "relation": "DENOMINATED_IN"}
  ]
}
Do NOT include markdown explanations, markdown fences, or text outside the JSON object.
"""