"""Unit tests for global multilingual taxonomy, cross-lingual canonicalization, and topic group/ungroup."""

from reposcroller.ai.taxonomy import TaxonomyManager, TaxonomyCategory
from reposcroller.ai.analyzer import DocumentAnalyzer
from reposcroller.ledger.repository import DocumentRepository


def test_taxonomy_seeding_multilingual(temp_db):
    mgr = TaxonomyManager(db_conn=temp_db)
    cats = mgr.get_all_categories()

    assert len(cats) >= 8
    # Find lease_contract
    lease = next((c for c in cats if c.category_id == "lease_contract"), None)
    assert lease is not None
    assert "Bail" in lease.name_fr
    assert "Miet" in lease.name_de
    assert "Lease" in lease.name_en


def test_cross_lingual_canonicalization(temp_db):
    """Verify French, German, and English texts for the same concept map to the identical canonical category."""
    mgr = TaxonomyManager(db_conn=temp_db)
    analyzer = DocumentAnalyzer(provider="heuristic", taxonomy_manager=mgr)

    # 1. French Lease document
    fr_text = "CONTRAT DE BAIL À LOYER\nEntre le bailleur et le locataire pour un appartement à Genève.\nLoyer mensuel: CHF 2500."
    res_fr = analyzer.analyze(fr_text, filename="Bail_Geneve_2024.pdf")
    assert res_fr.document_category == "lease_contract"

    # 2. German Lease document
    de_text = "MIETVERTRAG FÜR WOHNUNG\nZwischen Vermieter und Mieter für eine Wohnung in Zürich.\nMiete: CHF 2200."
    res_de = analyzer.analyze(de_text, filename="Mietvertrag_Zurich_2024.pdf")
    assert res_de.document_category == "lease_contract"

    # 3. English Lease document
    en_text = "RESIDENTIAL LEASE AGREEMENT\nBetween landlord and tenant for premises in Bern.\nMonthly rent: CHF 1800."
    res_en = analyzer.analyze(en_text, filename="Lease_Agreement_Bern_2024.pdf")
    assert res_en.document_category == "lease_contract"


def test_taxonomy_topic_association_merge(temp_db):
    """Test associating/merging two categories across languages into a single unified canonical topic."""
    mgr = TaxonomyManager(db_conn=temp_db)
    repo = DocumentRepository(conn=temp_db)

    # Create two temporary language-specific categories
    mgr.upsert_category(TaxonomyCategory(
        category_id="french_bail",
        name_en="French Lease",
        name_fr="Bail locatif",
        name_de="Mietvertrag Französisch",
        keywords=["bail", "loyer"]
    ))
    mgr.upsert_category(TaxonomyCategory(
        category_id="unified_lease",
        name_en="Unified Lease Agreement",
        name_fr="Bail unifié",
        name_de="Einheitlicher Mietvertrag",
        keywords=["lease", "miete"]
    ))

    # Ingest document under french_bail
    repo.upsert_document(
        sha256_hash="sha_fr_doc",
        simhash="1234567890abcdef",
        canonical_filename="Bail.pdf",
        doc_type="french_bail",
        lifecycle_status="final",
        completeness_score=0.9,
        maturity_score=0.85,
        page_count=2,
        text_snippet="Bail à loyer"
    )

    # Execute merge (Association)
    reassigned = mgr.merge_categories(source_category_id="french_bail", target_category_id="unified_lease")
    assert reassigned == 1

    # Verify document in ledger now has unified_lease
    doc = repo.get_document_by_sha256("sha_fr_doc")
    assert doc["doc_type"] == "unified_lease"

    # Source category is cleaned up
    assert mgr.get_category("french_bail") is None


def test_taxonomy_topic_dissociation_split(temp_db):
    """Test dissociating/ungrouping a broad category into specialized subtopics."""
    mgr = TaxonomyManager(db_conn=temp_db)
    repo = DocumentRepository(conn=temp_db)

    # Document 1: employment
    repo.upsert_document(
        sha256_hash="sha_emp",
        simhash="1111111111111111",
        canonical_filename="Job.pdf",
        doc_type="legal_contract",
        lifecycle_status="final",
        completeness_score=0.9,
        maturity_score=0.8,
        page_count=2,
        text_snippet="Employment contract"
    )

    # Document 2: commercial lease
    repo.upsert_document(
        sha256_hash="sha_lease",
        simhash="2222222222222222",
        canonical_filename="Lease.pdf",
        doc_type="legal_contract",
        lifecycle_status="final",
        completeness_score=0.9,
        maturity_score=0.8,
        page_count=3,
        text_snippet="Commercial lease"
    )

    # Dissociate into subcategories
    sub_employment = TaxonomyCategory(
        category_id="sub_employment",
        parent_id="legal_contract",
        name_en="Employment Subtopic",
        name_fr="Sous-thème Emploi",
        name_de="Unterthema Beschäftigung",
        keywords=["employment", "job"]
    )

    sub_lease = TaxonomyCategory(
        category_id="sub_lease",
        parent_id="legal_contract",
        name_en="Lease Subtopic",
        name_fr="Sous-thème Location",
        name_de="Unterthema Miete",
        keywords=["lease", "rental"]
    )

    reassigned = mgr.split_category(
        parent_category_id="legal_contract",
        new_subcategories=[sub_employment, sub_lease],
        document_reassignments={
            "sha_emp": "sub_employment",
            "sha_lease": "sub_lease"
        }
    )

    assert reassigned == 2
    doc_emp = repo.get_document_by_sha256("sha_emp")
    doc_lease = repo.get_document_by_sha256("sha_lease")
    assert doc_emp["doc_type"] == "sub_employment"
    assert doc_lease["doc_type"] == "sub_lease"
