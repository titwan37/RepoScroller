"""Tests for raw scanner postponement, ignore patterns, and rename upgrades."""

import time
from pathlib import Path
import pytest
from backend.config import settings
from backend.core.crawler import is_raw_scan_postponed, is_file_ignored, DocumentEventHandler
from backend.ledger.repository import DocumentRepository
from backend.core.synchronizer import DocumentSynchronizer


def test_is_raw_scan_postponed(tmp_path: Path):
    scan_file = tmp_path / "Xerox Scan_20261011202109.PDF"
    scan_file.write_text("dummy scan content", encoding="utf-8")

    # Fresh scan should be postponed
    assert is_raw_scan_postponed(scan_file) is True

    # Renamed file should NOT be postponed
    renamed_file = tmp_path / "2026-10-11-Zuger-Polizei-Report.pdf"
    renamed_file.write_text("dummy scan content", encoding="utf-8")
    assert is_raw_scan_postponed(renamed_file) is False


def test_is_file_ignored_patterns(tmp_path: Path):
    # Scanner logs and temporary files should be ignored
    job_log = tmp_path / "job_history.txt"
    job_log.write_text("job logged", encoding="utf-8")
    assert is_file_ignored(job_log) is True

    office_lock = tmp_path / "~$Contract.docx"
    office_lock.write_text("lock", encoding="utf-8")
    assert is_file_ignored(office_lock) is True

    tmp_file = tmp_path / "report.tmp"
    tmp_file.write_text("tmp", encoding="utf-8")
    assert is_file_ignored(tmp_file) is True

    # Raw Xerox Scan should be ignored / postponed
    xerox_scan = tmp_path / "Xerox Scan_20261011202611.PDF"
    xerox_scan.write_text("scan", encoding="utf-8")
    assert is_file_ignored(xerox_scan) is True

    # Proper document should NOT be ignored
    legit_doc = tmp_path / "2026-10-11-Mietvertrag.pdf"
    legit_doc.write_text("valid document", encoding="utf-8")
    assert is_file_ignored(legit_doc) is False


def test_observer_postpones_raw_scan(tmp_path: Path):
    scan_file = tmp_path / "Xerox Scan_20261011204848.PDF"
    scan_file.write_text("raw scan", encoding="utf-8")

    class MockSynchronizer:
        def __init__(self):
            self.processed = []
        def process_file(self, path, root):
            self.processed.append(path.name)
            return {"status": "ingested"}

    mock_sync = MockSynchronizer()
    handler = DocumentEventHandler(synchronizer=mock_sync, storage_root=str(tmp_path))

    class MockEvent:
        def __init__(self, path):
            self.src_path = str(path)
            self.is_directory = False

    # on_created for raw scan: should be postponed and NOT processed
    handler.on_created(MockEvent(scan_file))
    assert len(mock_sync.processed) == 0

    # on_created for renamed file: should be processed
    renamed_file = tmp_path / "2026-10-11-Invoice.pdf"
    renamed_file.write_text("renamed invoice", encoding="utf-8")
    handler.on_created(MockEvent(renamed_file))
    assert mock_sync.processed == ["2026-10-11-Invoice.pdf"]


def test_synchronizer_upgrades_canonical_filename(tmp_path: Path):
    from backend.ledger.db import init_db
    db_file = tmp_path / "test_upgrade.db"
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)

    # Ingest file originally as Xerox Scan_...
    sha = "test_sha_upgrade_12345"
    repo.upsert_document(
        sha256_hash=sha,
        simhash="123",
        canonical_filename="Xerox Scan_20261011202109.PDF",
        doc_type="legal_contract",
        lifecycle_status="final",
        completeness_score=1.0,
        maturity_score=1.0,
        page_count=1,
        text_snippet="Test text",
        doc_date="2026-10-11",
        full_text="Test text",
    )
    repo.record_location(
        sha256_hash=sha,
        storage_root=str(tmp_path),
        relative_path="Xerox Scan_20261011202109.PDF",
        absolute_path=str(tmp_path / "Xerox Scan_20261011202109.PDF"),
        file_size=100,
        mtime=time.time(),
        is_primary=True,
    )

    doc_before = repo.get_document_by_sha256(sha)
    assert doc_before["canonical_filename"] == "Xerox Scan_20261011202109.PDF"

    # Now the file is discovered under its renamed meaningful name
    renamed_file = tmp_path / "2026-10-11-Zuger-Polizei-Einvernahme.pdf"
    renamed_file.write_text("Test text", encoding="utf-8")

    class MockAnalyzer:
        pass
    class MockEvaluator:
        pass

    sync = DocumentSynchronizer(repository=repo)
    # Patch compute_sha256 to return our sha
    import backend.core.synchronizer as sync_mod
    orig_hash = sync_mod.compute_sha256
    sync_mod.compute_sha256 = lambda p: sha

    try:
        res = sync.process_file(renamed_file, str(tmp_path))
        assert res["status"] == "exact_duplicate_recorded"
        assert res["canonical_filename"] == "2026-10-11-Zuger-Polizei-Einvernahme.pdf"

        # Check in DB that canonical_filename was upgraded!
        doc_after = repo.get_document_by_sha256(sha)
        assert doc_after["canonical_filename"] == "2026-10-11-Zuger-Polizei-Einvernahme.pdf"
    finally:
        sync_mod.compute_sha256 = orig_hash
        repo.close()
