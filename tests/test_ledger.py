"""Unit tests for SQLite WAL ledger, ALCOA+ audit trails, and FTS5 search."""

from reposcroller.ledger.repository import DocumentRepository


def test_upsert_and_retrieve_document(repo: DocumentRepository):
    repo.upsert_document(
        sha256_hash="abc123sha",
        simhash="1122334455667788",
        canonical_filename="Tax_Letter_2024.pdf",
        doc_type="pdf",
        lifecycle_status="final",
        completeness_score=0.95,
        maturity_score=0.88,
        page_count=3,
        text_snippet="Dear Taxpayer, enclosed is the official assessment for 2024.",
        full_text="Dear Taxpayer, enclosed is the official assessment for 2024. Zurich tax office."
    )

    doc = repo.get_document_by_sha256("abc123sha")
    assert doc is not None
    assert doc["canonical_filename"] == "Tax_Letter_2024.pdf"
    assert doc["lifecycle_status"] == "final"
    assert doc["maturity_score"] == 0.88

    # Verify FTS5 keyword search
    fts_res = repo.search_keyword_fts("Zurich tax")
    assert len(fts_res) == 1
    assert fts_res[0]["sha256_hash"] == "abc123sha"


def test_multiple_locations_single_hash(repo: DocumentRepository):
    # Ingest document
    repo.upsert_document(
        sha256_hash="hash_same_doc",
        simhash="aabbccddeeff0011",
        canonical_filename="Important_Notice.txt",
        doc_type="txt",
        lifecycle_status="final",
        completeness_score=0.9,
        maturity_score=0.85,
        page_count=1,
        text_snippet="Important notice contents."
    )

    # Record location 1: NAS share
    repo.record_location(
        sha256_hash="hash_same_doc",
        storage_root=r"\\SyNAS\CloudSpace\LexSpace",
        relative_path="Notices/Notice.txt",
        absolute_path=r"\\SyNAS\CloudSpace\LexSpace\Notices\Notice.txt",
        file_size=1024,
        mtime=1700000000.0,
        is_primary=True
    )

    # Record location 2: GDrive mirror
    repo.record_location(
        sha256_hash="hash_same_doc",
        storage_root=r"H:\My Drive",
        relative_path="Backups/Notice_copy.txt",
        absolute_path=r"H:\My Drive\Backups\Notice_copy.txt",
        file_size=1024,
        mtime=1700000000.0,
        is_primary=False
    )

    doc = repo.get_document_by_sha256("hash_same_doc")
    assert len(doc["locations"]) == 2

    stats = repo.get_stats()
    assert stats["total_unique_documents"] == 1
    assert stats["total_physical_locations"] == 2
    assert stats["duplicates_deduplicated"] == 1


def test_version_lineage_linking(repo: DocumentRepository):
    # Old draft
    repo.upsert_document(
        sha256_hash="hash_draft",
        simhash="1111111111111111",
        canonical_filename="Brief_draft.txt",
        doc_type="txt",
        lifecycle_status="draft",
        completeness_score=0.4,
        maturity_score=0.35,
        page_count=1,
        text_snippet="Draft text."
    )

    # New final
    repo.upsert_document(
        sha256_hash="hash_final",
        simhash="1111111111111112",
        canonical_filename="Brief_final.txt",
        doc_type="txt",
        lifecycle_status="final",
        completeness_score=0.9,
        maturity_score=0.85,
        page_count=2,
        text_snippet="Final text with signatures."
    )

    # Link: final supersedes draft
    repo.link_version_chain(
        parent_sha256="hash_draft",
        child_sha256="hash_final",
        relationship="supersedes",
        similarity_score=0.92
    )

    draft_doc = repo.get_document_by_sha256("hash_draft")
    final_doc = repo.get_document_by_sha256("hash_final")

    assert len(draft_doc["children"]) == 1
    assert draft_doc["children"][0]["child_sha256"] == "hash_final"
    assert len(final_doc["parents"]) == 1
    assert final_doc["parents"][0]["parent_sha256"] == "hash_draft"


def test_document_date_extraction_and_sorting(repo: DocumentRepository):
    # Ingest 3 documents with different date sources:
    # 1. European prefix: 05.08.25-... -> 2025-08-05
    repo.upsert_document(
        sha256_hash="doc_aug25",
        simhash="1000000000000001",
        canonical_filename="05.08.25-Zahlstelle-722Unia-Taggeld.pdf",
        doc_type="pdf",
        lifecycle_status="final",
        completeness_score=0.9,
        maturity_score=0.9,
        page_count=2,
        text_snippet="Invoice for August 2025"
    )

    # 2. ISO prefix: 1999_05_10_... -> 1999-05-10
    repo.upsert_document(
        sha256_hash="doc_may99",
        simhash="1000000000000002",
        canonical_filename="1999_05_10_LaboratoireMedical_France.pdf",
        doc_type="pdf",
        lifecycle_status="final",
        completeness_score=0.9,
        maturity_score=0.9,
        page_count=1,
        text_snippet="Lab test results"
    )

    # 3. No date in filename, but mtime provided (2020-01-15: 1579089600)
    repo.upsert_document(
        sha256_hash="doc_mtime20",
        simhash="1000000000000003",
        canonical_filename="GeneralNotice_NoDateInName.pdf",
        doc_type="pdf",
        lifecycle_status="final",
        completeness_score=0.8,
        maturity_score=0.8,
        page_count=1,
        text_snippet="General company memo."
    )
    repo.record_location(
        sha256_hash="doc_mtime20",
        storage_root=r"\\SyNAS\xcloud\docs",
        relative_path="memo.pdf",
        absolute_path=r"\\SyNAS\xcloud\docs\memo.pdf",
        file_size=1024,
        mtime=1579089600.0  # 2020-01-15
    )

    # Backfill/verify doc_date
    repo.backfill_document_dates()

    # Sort DESC (newest document date first)
    docs_desc = repo.get_all_documents(limit=10, sort_by="doc_date", sort_order="DESC")
    # Expected order: 2025-08-05 -> 2020-01-15 -> 1999-05-10
    shas_desc = [d["sha256_hash"] for d in docs_desc if d["sha256_hash"] in ("doc_aug25", "doc_may99", "doc_mtime20")]
    assert shas_desc == ["doc_aug25", "doc_mtime20", "doc_may99"]

    # Sort ASC (oldest document date first)
    docs_asc = repo.get_all_documents(limit=10, sort_by="doc_date", sort_order="ASC")
    # Expected order: 1999-05-10 -> 2020-01-15 -> 2025-08-05
    shas_asc = [d["sha256_hash"] for d in docs_asc if d["sha256_hash"] in ("doc_aug25", "doc_may99", "doc_mtime20")]
    assert shas_asc == ["doc_may99", "doc_mtime20", "doc_aug25"]

