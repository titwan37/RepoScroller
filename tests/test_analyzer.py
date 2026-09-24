"""Unit tests for DocumentAnalyzer (LLM & heuristic multilingual classification)."""

from reposcroller.ai.analyzer import DocumentAnalyzer
from reposcroller.ai.taxonomy import TaxonomyManager


def test_analyzer_contract_detection(temp_db):
    mgr = TaxonomyManager(db_conn=temp_db)
    analyzer = DocumentAnalyzer(provider="heuristic", taxonomy_manager=mgr)
    text = (
        "EMPLOYMENT AGREEMENT\n"
        "This Agreement is entered into between Acme Corporation and John Doe.\n"
        "The employee agrees to confidentiality and terms.\n"
        "Date: 2024-03-01."
    )
    result = analyzer.analyze(text=text, filename="Employment_Agreement_Acme.pdf")

    assert result.document_category in ["employment_contract", "legal_contract"]
    assert result.governing_date == "2024-03-01"
    assert "Acme Corporation" in result.parties_involved or "John Doe" in result.parties_involved
    assert result.confidence_score >= 0.80


def test_analyzer_court_order_detection(temp_db):
    mgr = TaxonomyManager(db_conn=temp_db)
    analyzer = DocumentAnalyzer(provider="heuristic", taxonomy_manager=mgr)
    text = (
        "Obergericht des Kantons Zug\n"
        "Urteil und Beschluss der I. Zivilkammer vom 15. Mai 2024.\n"
        "In Sachen Kläger gegen Beklagte betreffend Schadenersatz."
    )
    result = analyzer.analyze(text=text, filename="Obergericht_Urteil_20240515.pdf")

    assert result.document_category == "court_order"
    assert result.confidence_score >= 0.85


def test_analyzer_tax_letter_detection(temp_db):
    mgr = TaxonomyManager(db_conn=temp_db)
    analyzer = DocumentAnalyzer(provider="heuristic", taxonomy_manager=mgr)
    text = (
        "Kantonales Steueramt Zürich\n"
        "Veranlagungsverfügung für die direkte Bundessteuer 2023.\n"
        "Datum: 2024-04-12."
    )
    result = analyzer.analyze(text=text, filename="Steueramt_Veranlagung_2024.pdf")

    assert result.document_category in ["tax_assessment", "tax_letter"]
    assert result.governing_date == "2024-04-12"
