"""Tests for document text extraction including .docx, .pdf, and plain text."""

import zipfile
from pathlib import Path
from reposcroller.extraction.text_extractor import extract_document_data


def test_extract_docx_clean_text(tmp_path: Path):
    """Verify that .docx files are properly unzipped and parsed into clean paragraphs without XML/binary tags."""
    docx_file = tmp_path / "sample.docx"

    # Create a synthetic valid .docx zip structure
    doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body>
            <w:p><w:r><w:t>Application for Machine Learning Engineer position.</w:t></w:r></w:p>
            <w:p><w:r><w:t>Dear Hiring Team at Giotto.ai,</w:t></w:r></w:p>
            <w:p><w:r><w:t>I am writing to express my strong interest in the AI role.</w:t></w:r></w:p>
        </w:body>
    </w:document>
    """
    core_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:creator>Alice Developer</dc:creator>
        <dc:title>ML Application Letter</dc:title>
    </cp:coreProperties>
    """

    with zipfile.ZipFile(docx_file, "w") as z:
        z.writestr("word/document.xml", doc_xml)
        z.writestr("docProps/core.xml", core_xml)

    text, metadata = extract_document_data(docx_file)

    assert "Application for Machine Learning Engineer position." in text
    assert "Dear Hiring Team at Giotto.ai," in text
    assert "PK" not in text
    assert "word/document.xml" not in text
    assert metadata["author"] == "Alice Developer"
    assert metadata["title"] == "ML Application Letter"
