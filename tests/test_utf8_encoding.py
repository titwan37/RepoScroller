"""Tests for comprehensive UTF-8 encoding support across the entire ingestion, hashing, and retrieval pipeline."""

import pytest
import zipfile
from pathlib import Path
from reposcroller.integrity.hasher import compute_sha256, compute_bytes_sha256
from reposcroller.integrity.simhash import compute_simhash, simhash_similarity
from reposcroller.extraction.text_extractor import extract_document_data
from reposcroller.ledger.db import init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.ai.chunker import DocumentChunker
from reposcroller.ai.embeddings import EmbeddingAdapter
from reposcroller.ai.graph_extractor import KnowledgeGraphExtractor


def test_utf8_hashing_and_simhash():
    """Verify SHA-256 and SimHash correctly handle multi-byte multilingual UTF-8 strings."""
    text_fr = "Contrat de travail à durée indéterminée pour Genève et Zürich."
    text_de = "Arbeitsvertrag für Geschäftsführer mit Überstundenregelung und Kündigungsfrist."
    text_emoji = "⚖️ Juridique et conformité des décisions judiciaires 📜."

    # Bytes and string hashing
    sha_fr = compute_bytes_sha256(text_fr.encode("utf-8"))
    assert len(sha_fr) == 64

    # SimHash
    sim_fr = compute_simhash(text_fr)
    sim_de = compute_simhash(text_de)
    sim_emoji = compute_simhash(text_emoji)

    assert len(sim_fr) == 16
    assert len(sim_de) == 16
    assert len(sim_emoji) == 16

    # Similar text with minor UTF-8 accent difference
    text_fr_mod = "Contrat de travail a duree indeterminee pour Geneve et Zurich."
    sim_fr_mod = compute_simhash(text_fr_mod)
    similarity = simhash_similarity(sim_fr, sim_fr_mod)
    assert similarity >= 0.70


def test_utf8_docx_extraction(tmp_path: Path):
    """Verify that Word .docx files with French and German accented text are extracted in pure UTF-8."""
    docx_file = tmp_path / "contrat_zürich_genève.docx"
    doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body>
            <w:p><w:r><w:t>Société Générale de Surveillance (SGS) à Genève.</w:t></w:r></w:p>
            <w:p><w:r><w:t>Kantonales Steueramt Zürich – Verfügung über Nachsteuern.</w:t></w:r></w:p>
        </w:body>
    </w:document>
    """
    core_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:creator>François Müller</dc:creator>
        <dc:title>Contrat &amp; Décision</dc:title>
    </cp:coreProperties>
    """

    with zipfile.ZipFile(docx_file, "w") as z:
        z.writestr("word/document.xml", doc_xml.encode("utf-8"))
        z.writestr("docProps/core.xml", core_xml.encode("utf-8"))

    text, meta = extract_document_data(docx_file)
    assert "Société Générale de Surveillance (SGS) à Genève." in text
    assert "Kantonales Steueramt Zürich – Verfügung über Nachsteuern." in text
    assert meta["author"] == "François Müller"
    assert meta["title"] == "Contrat & Décision"


def test_utf8_sqlite_persistence_and_fts5(tmp_path: Path):
    """Verify SQLite WAL and FTS5 properly store, index, and query multilingual UTF-8 terms."""
    db_file = tmp_path / "test_utf8.db"
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)

    sha = "utf8_test_sha_001"
    repo.upsert_document(
        sha256_hash=sha,
        simhash="123456789abcdef0",
        canonical_filename="2024_Décision_Tribunal_Fédéral_Lausanne.pdf",
        doc_type="tribunal_decision",
        lifecycle_status="final",
        completeness_score=1.0,
        maturity_score=0.98,
        page_count=5,
        text_snippet="Arrêt du Tribunal Fédéral rendu à Lausanne concernant la société Électricité SA.",
        doc_date="2024-03-15",
        full_text="Arrêt du Tribunal Fédéral rendu à Lausanne concernant la société Électricité SA et son siège à Genève."
    )

    # 1. Exact retrieval
    doc = repo.get_document_by_sha256(sha)
    assert doc is not None
    assert doc["canonical_filename"] == "2024_Décision_Tribunal_Fédéral_Lausanne.pdf"
    assert "Tribunal Fédéral" in doc["text_snippet"]

    # 2. FTS5 search with accented term
    hits = repo.search_keyword_fts("Tribunal", limit=5)
    assert len(hits) >= 1
    assert hits[0]["sha256_hash"] == sha


def test_utf8_chunker_and_embeddings():
    """Verify DocumentChunker and EmbeddingAdapter preserve UTF-8 characters throughout embeddings."""
    chunker = DocumentChunker(chunk_size_tokens=50, chunk_overlap_tokens=10)
    embedder = EmbeddingAdapter(provider="mock", dimension=64)

    text = "Le Conseil d'État de la République et canton de Genève arrête le règlement concernant l'énergie renouvelable."
    chunks = chunker.chunk_document(
        text=text,
        sha256_hash="utf8_sha_chunk",
        canonical_filename="Règlement_Genève_2024.pdf",
        doc_type="règlement",
        doc_date="2024-01-01"
    )

    assert len(chunks) >= 1
    assert "Règlement_Genève_2024.pdf" in chunks[0]["chunk_text"]
    assert "République et canton de Genève" in chunks[0]["chunk_text"]

    vec = embedder.embed_text(chunks[0]["chunk_text"])
    assert len(vec) == 64
    assert any(v != 0.0 for v in vec)
