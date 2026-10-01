"""Unit tests for global multilingual taxonomy, cross-lingual canonicalization, and topic group/ungroup."""

from backend.ai.taxonomy import TaxonomyManager, TaxonomyCategory, TaxonomyEvolutionEngine
from backend.ai.analyzer import DocumentAnalyzer
from backend.ledger.repository import DocumentRepository

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


def test_taxonomy_skill_sync_and_evolution(temp_db):
    """Test syncing taxonomy from skill file and running evolution engine."""

    mgr = TaxonomyManager(db_conn=temp_db)
    sync_res = mgr.sync_from_skill()
    assert sync_res["status"] == "synced"
    assert sync_res["version"] == "v1.0.0"

    # Verify career categories are present
    cats = {c.category_id: c for c in mgr.get_all_categories()}
    assert "career_research" in cats
    assert "career_cv" in cats
    assert "career_cover_letter" in cats
    assert "career_job_description" in cats
    assert "career_portfolio" in cats

    # Ingest test documents with older v0.9.0 taxonomy
    repo = DocumentRepository(conn=temp_db)
    repo.upsert_document(
        sha256_hash="sha_cv_01",
        simhash="1111000011110000",
        canonical_filename="2025_Antoine_Falempin_resume.pdf",
        doc_type="identity_credentials",
        lifecycle_status="final",
        completeness_score=0.95,
        maturity_score=0.90,
        page_count=2,
        text_snippet="Curriculum Vitae of Senior Software Engineer"
    )
    repo.upsert_document(
        sha256_hash="sha_mot_01",
        simhash="2222000022220000",
        canonical_filename="Lettre_de_motivation_Kyndryl.pdf",
        doc_type="formal_correspondence",
        lifecycle_status="final",
        completeness_score=0.95,
        maturity_score=0.90,
        page_count=1,
        text_snippet="Madame, Monsieur, je postule pour le poste..."
    )

    engine = TaxonomyEvolutionEngine(taxonomy_manager=mgr)
    
    # 1. Test Dry-Run
    dry_res = engine.evolve_ledger(dry_run=True, limit=10)
    assert dry_res["status"] == "completed"
    assert dry_res["dry_run"] is True
    assert dry_res["reclassifications_count"] == 2
    assert dry_res["applied_count"] == 0

    # 2. Test Execution
    live_res = engine.evolve_ledger(dry_run=False, limit=10)
    assert live_res["status"] == "completed"
    assert live_res["reclassifications_count"] == 2
    assert live_res["applied_count"] >= 2

    # Check updated ledger
    doc_cv = repo.get_document_by_sha256("sha_cv_01")
    assert doc_cv["doc_type"] == "career_cv"
    assert doc_cv["taxonomy_version"] == "v1.0.0"

    doc_mot = repo.get_document_by_sha256("sha_mot_01")
    assert doc_mot["doc_type"] == "career_cover_letter"
    assert doc_mot["taxonomy_version"] == "v1.0.0"


def test_german_application_letter_classification(temp_db):
    """Verify that German job application letters (with technical protocols mentioned) classify as career_cover_letter instead of corporate_governance."""
    mgr = TaxonomyManager(db_conn=temp_db)
    analyzer = DocumentAnalyzer(provider="heuristic", taxonomy_manager=mgr)

    text = """Antoine Guillaume Falempin M.Sc.
System Engineer IT-Infrastruktur & Kommunikationssysteme
Ottenbach (ZH), Schweiz

Ascom (Schweiz) AG
z.H. Hiring Manager
Eichtalstrasse 62
8634 Hombrechtikon

Zürich, 11.09.2026

Betreff: Bewerbung als System Engineer für IT-Infrastruktur und Kommunikationssysteme

Sehr geehrte Damen und Herren,

als erfahrener Systemintegrator mit fundierten Kenntnissen moderner Netzwerk- und Kommunikationsprotokolle bewerbe ich mich mit grosser Begeisterung für die ausgeschriebene Position."""

    filename = "2026-09-11_18-07_Ascom_SystemEngineer_A-Falempin_application_letter_de.docx"
    res = analyzer.analyze(text, filename=filename)
    assert res.document_category == "career_cover_letter"
    assert res.confidence_score >= 0.90


def test_ascom_job_description_classification(temp_db):
    """Verify that JobDescription documents (e.g. Ascom System Engineer) classify as career_job_description rather than lease_contract."""
    mgr = TaxonomyManager(db_conn=temp_db)
    analyzer = DocumentAnalyzer(provider="heuristic", taxonomy_manager=mgr)

    text = (
        "Job Details:----------job_title: System Engineercompany_name: Ascom"
        "contact_person_name: contact_email: contact_phone: contact_postal_address: Eichtalstrasse 62, 8634 Zurich"
        "job_languages: Deutsch (sehr gut), Englisch (gut)detected_description_language: Germanlanguage_code: de"
        "short_description: Ascom sucht einen System Engineer für IT-Infrastruktur und Kommunikationssysteme in der Gesundheitsbranche mit Einsatz in der Deutschschweiz."
        "job_url: https://ch.indeed.com/viewjob?jk=f5c849e2f457e703&from=shareddesktop_copyjob_desc_source: url"
        "long_description: Gestalte mit uns die Zukunft der GesundheitsversorgungAls System Engineer bei Ascom arbeitest du an Lösungen, die jeden Tag Leben retten und verbessern. "
        "Du bringst innovative Technologien dorthin, wo sie wirklich zählen – direkt in Krankenhäuser und kritische Infrastrukturen."
        "Dabei bist du in der ganzen Deutschschweiz im Einsatz."
    )

    filename = "2026-09-11_18-07-13_Ascom - System Engineer_JobDescription.docx"
    metadata = {
        "path": r"L:\My Drive\RAV\2025rav\2025-Positions\2026-09-11_18-07-13_Ascom - System Engineer_JobDescription.docx"
    }

    res = analyzer.analyze(text, filename=filename, metadata=metadata)
    assert res.document_category == "career_job_description"
    assert res.confidence_score >= 0.95
    assert "System Engineer" in res.summary
    assert res.document_category != "lease_contract"


def test_cv_classification_precedence_over_technical_architecture_and_tax(temp_db):
    """Verify that CV and Lebenslauf documents with technical or German engineering terms classify as career_cv rather than technical_architecture or tax_assessment."""
    mgr = TaxonomyManager(db_conn=temp_db)
    analyzer = DocumentAnalyzer(provider="heuristic", taxonomy_manager=mgr)

    # 1. Senior Software Engineer CV with software architecture and technical specs mentioned
    tech_cv_text = (
        "Antoine Guillaume Falempin M.Sc.\n"
        "Senior Software Engineer & Cloud Solutions Architect\n"
        "Professional Experience:\n"
        "- Designed high-throughput microservices architecture and technical specifications.\n"
        "- Delivered enterprise blueprint and managed cloud infrastructure."
    )
    res_tech = analyzer.analyze(
        tech_cv_text,
        filename="2026-0910_CV_AFalempin_SeniorSoftwareEngineer_LowLatencyDistributedSystems_en.pdf",
        metadata={"path": r"L:\My Drive\RAV\2025rav\2025-CV\2026-0910_CV_AFalempin_SeniorSoftwareEngineer_LowLatencyDistributedSystems_en.pdf"}
    )
    assert res_tech.document_category == "career_cv"
    assert res_tech.confidence_score >= 0.95
    assert res_tech.document_category != "technical_architecture"

    # 2. German Lebenslauf with Prozesssteuerung & Automation mentioned (previously false-positiving into tax_assessment)
    de_cv_text = (
        "Lebenslauf\n"
        "Antoine Guillaume Falempin M.Sc.\n"
        "Berufserfahrung:\n"
        "- Automation Engineer: Programmierung von Prozesssteuerungen und Messsystemen.\n"
        "- Risikobewertung und Qualitätssicherung in der Fertigungstechnik."
    )
    res_de = analyzer.analyze(
        de_cv_text,
        filename="2026-0329_CV_MSATAutoEngineer_AFalempin_Lebenslauf_de.pdf",
        metadata={"path": r"L:\My Drive\RAV\2025rav\2025-CV\2026-0329_CV_MSATAutoEngineer_AFalempin_Lebenslauf_de.pdf"}
    )
    assert res_de.document_category == "career_cv"
    assert res_de.confidence_score >= 0.95
    assert res_de.document_category != "tax_assessment"

    # 3. Concatenated CV filename like 2026CVdinda
    res_dinda = analyzer.analyze(
        "Dinda Ranadireksa\nBerufserfahrung:\n- Verkäuferin im Kundenservice\nAusbildung:\n- Handelsschule",
        filename="2026CVdinda_MigrosVerkauferin_v3.pdf",
        metadata={"path": r"L:\My Drive\Shared\2026DindaCV\CV\2026CVdinda_MigrosVerkauferin_v3.pdf"}
    )
    assert res_dinda.document_category == "career_cv"
    assert res_dinda.confidence_score >= 0.95



