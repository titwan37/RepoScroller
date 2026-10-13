"""Unit tests for Fedlex and Akoma Ntoso Swiss Law ingestion pipeline in RepoScroller."""

import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

from backend.config import settings
from backend.extraction.fedlex_parser import (
    is_akoma_ntoso_xml,
    detect_sr_and_lang,
    parse_akoma_ntoso_xml,
    SWISS_LAW_CATALOG,
)
from backend.extraction.text_extractor import extract_document_data
from backend.ai.chunker import DocumentChunker
from backend.ai.graph_extractor import KnowledgeGraphExtractor


SAMPLE_AKOMA_NTOSO = """<?xml version="1.0" encoding="UTF-8"?>
<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0">
  <act name="legislation">
    <meta>
      <identification source="#ch.bk">
        <FRBRWork>
          <FRBRnumber value="220"/>
          <FRBRlanguage language="fr"/>
        </FRBRWork>
      </identification>
    </meta>
    <body>
      <article eId="art_1">
        <num>Art. 1</num>
        <heading>A. Conclusion du contrat / I. Offre et acceptation</heading>
        <paragraph eId="art_1/para_1">
          <p>Le contrat est parfait lorsque les parties ont, réciproquement et d'une manière concordante, manifesté leur volonté.</p>
        </paragraph>
        <paragraph eId="art_1/para_2">
          <p>Cette manifestation peut être expresse ou tacite.</p>
        </paragraph>
      </article>
      <article eId="art_2">
        <num>Art. 2</num>
        <heading>II. Points secondaires</heading>
        <paragraph eId="art_2/para_1">
          <p>Si les parties se sont mises d'accord sur tous les points essentiels, le contrat est réputé conclu.</p>
        </paragraph>
      </article>
    </body>
  </act>
</akomaNtoso>
"""


def test_config_swiss_law():
    """Verify Swiss law configuration mappings and extensions."""
    assert ".xml" in settings.SUPPORTED_EXTENSIONS
    assert settings.get_sr_code_for_abbrev("CO") == "220"
    assert settings.get_sr_code_for_abbrev("OR") == "220"
    assert settings.get_sr_code_for_abbrev("CC") == "210"
    assert settings.get_sr_code_for_abbrev("ZGB") == "210"
    assert settings.is_swiss_law_root(r"\\SyNAS\CloudSpace\LexSpace\Fedlex_Library") is True


def test_fedlex_xml_detection_and_parsing():
    """Verify that Akoma Ntoso 3.0 XML is correctly detected, parsed, and bound."""
    with tempfile.TemporaryDirectory() as tmpdir:
        xml_file = Path(tmpdir) / "RS-220-20240101-FR.xml"
        xml_file.write_text(SAMPLE_AKOMA_NTOSO, encoding="utf-8")

        assert is_akoma_ntoso_xml(xml_file) is True
        sr_code, lang = detect_sr_and_lang(xml_file)
        assert sr_code == "220"
        assert lang == "fr"

        text, meta = parse_akoma_ntoso_xml(xml_file)
        assert meta["is_fedlex_xml"] is True
        assert meta["sr_code"] == "220"
        assert meta["lang"] == "fr"
        assert meta["articles_count"] == 2
        assert "220_Art. 1" in meta["binding_keys"]
        assert "220_Art. 2" in meta["binding_keys"]

        art1 = meta["articles"][0]
        assert art1["article_num"] == "Art. 1"
        assert art1["binding_key"] == "220_Art. 1"
        assert "Offre et acceptation" in art1["article_heading"]
        assert "passage: Code des obligations (CO SR 220), Art. 1" in art1["full_text"]


def test_text_extractor_routes_xml():
    """Verify that extract_document_data routes Akoma Ntoso XML files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        xml_file = Path(tmpdir) / "SR_220_test.xml"
        xml_file.write_text(SAMPLE_AKOMA_NTOSO, encoding="utf-8")

        text, meta = extract_document_data(xml_file)
        assert meta.get("is_fedlex_xml") is True
        assert meta.get("sr_code") == "220"
        assert len(meta.get("articles", [])) == 2


def test_chunker_preserves_article_boundaries():
    """Verify that DocumentChunker chunks legal documents at the article boundary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        xml_file = Path(tmpdir) / "RS-220-20240101-FR.xml"
        xml_file.write_text(SAMPLE_AKOMA_NTOSO, encoding="utf-8")

        text, meta = extract_document_data(xml_file)
        chunker = DocumentChunker(chunk_size_tokens=600, chunk_overlap_tokens=80)

        chunks = chunker.chunk_document(
            text=text,
            sha256_hash="fake_sha_220",
            canonical_filename=xml_file.name,
            doc_type="statute_legislation",
            articles=meta.get("articles")
        )

        assert len(chunks) == 2
        assert chunks[0]["binding_key"] == "220_Art. 1"
        assert chunks[0]["sr_code"] == "220"
        assert chunks[0]["article_num"] == "Art. 1"
        assert "passage: Code des obligations (CO SR 220), Art. 1" in chunks[0]["chunk_text"]
        assert chunks[1]["binding_key"] == "220_Art. 2"
        assert chunks[1]["article_num"] == "Art. 2"


def test_graph_extractor_statute_citation():
    """Verify that general documents citing Swiss law generate canonical statute hierarchy nodes."""
    extractor = KnowledgeGraphExtractor()

    contract_text = (
        "Le présent contrat de travail individuel est soumis au droit suisse, "
        "en particulier aux dispositions de l'art. 337 CO concernant la résiliation immédiate "
        "pour de justes motifs, ainsi qu'aux règles générales de l'Art. 320 CO."
    )

    doc_graph = extractor.extract_knowledge_graph(
        text=contract_text,
        sha256_hash="doc_contract_sha_123",
        filename="Contrat_Travail_2024.pdf",
        doc_type="employment_contract"
    )

    node_ids = {n.node_id for n in doc_graph.nodes}
    assert "statute_sr_220" in node_ids
    assert "statute_sr_220_art_337" in node_ids
    assert "statute_sr_220_art_320" in node_ids

    # Check PART_OF hierarchical edges
    part_of_edges = [e for e in doc_graph.edges if e.relation_type == "PART_OF"]
    assert any(e.source_id == "statute_sr_220_art_337" and e.target_id == "statute_sr_220" for e in part_of_edges)
    assert any(e.source_id == "statute_sr_220_art_320" and e.target_id == "statute_sr_220" for e in part_of_edges)

    # Check governing_law document link
    gov_links = [l for l in doc_graph.links if l.role == "governing_law"]
    linked_nodes = {l.node_id for l in gov_links}
    assert "statute_sr_220_art_337" in linked_nodes
    assert "statute_sr_220_art_320" in linked_nodes
