"""Unit tests for MultiRootCrawler and DocumentSynchronizer."""

from pathlib import Path
from reposcroller.core.crawler import MultiRootCrawler
from reposcroller.core.synchronizer import DocumentSynchronizer
from reposcroller.ledger.repository import DocumentRepository


def test_synchronizer_ingestion_and_duplicate(synchronizer: DocumentSynchronizer, sample_files, repo: DocumentRepository):
    # Ingest final contract
    res1 = synchronizer.process_file(sample_files["final"], sample_files["root_a"])
    assert res1["status"] == "ingested"
    assert res1["maturity_score"] >= 0.65

    # Process bit-identical copy in root_b
    res2 = synchronizer.process_file(sample_files["copy"], sample_files["root_b"])
    assert res2["status"] == "exact_duplicate_recorded"
    assert res2["sha256"] == res1["sha256"]

    # Verify ledger has 1 unique document and 2 physical locations
    stats = repo.get_stats()
    assert stats["total_unique_documents"] == 1
    assert stats["total_physical_locations"] == 2
    assert stats["duplicates_deduplicated"] == 1


def test_batch_crawl_multiple_roots(synchronizer: DocumentSynchronizer, sample_files, repo: DocumentRepository):
    crawler = MultiRootCrawler(
        storage_roots=[sample_files["root_a"], sample_files["root_b"]],
        synchronizer=synchronizer
    )

    summary = crawler.scan_all_roots()
    assert summary["total_scanned"] == 4
    # final + draft + truncated = 3 unique documents ingested
    assert summary["total_ingested"] == 3
    # copy of final = 1 duplicate detected
    assert summary["total_duplicates_found"] == 1
    assert summary["total_errors"] == 0

    # Scan again without changes -> all should be "unchanged" fast-path
    summary_cached = crawler.scan_all_roots()
    assert summary_cached["total_unchanged"] == 4
    assert summary_cached["total_ingested"] == 0


def test_antichronological_scan_order(tmp_path: Path, synchronizer: DocumentSynchronizer):
    root = tmp_path / "order_test_root"
    root.mkdir()

    import time
    import os

    # Create files with deliberate staggered timestamps
    old_file = root / "2020_old_archive.txt"
    old_file.write_text("Old file content", encoding="utf-8")
    os.utime(old_file, (1577836800, 1577836800))  # Year 2020

    mid_file = root / "2022_mid_record.txt"
    mid_file.write_text("Mid file content", encoding="utf-8")
    os.utime(mid_file, (1640995200, 1640995200))  # Year 2022

    new_file = root / "2024_new_decision.txt"
    new_file.write_text("New file content", encoding="utf-8")
    os.utime(new_file, (1704067200, 1704067200))  # Year 2024

    crawler = MultiRootCrawler(storage_roots=[str(root)], synchronizer=synchronizer)

    processed_sequence = []
    def track_order(fpath, status, stats):
        processed_sequence.append(fpath.name)

    crawler.scan_all_roots(progress_callback=track_order, order="antichronological")

    # Anti-chronological order: 2024 -> 2022 -> 2020
    assert processed_sequence == [
        "2024_new_decision.txt",
        "2022_mid_record.txt",
        "2020_old_archive.txt"
    ]


def test_parallel_multi_root_crawl(tmp_path: Path, synchronizer: DocumentSynchronizer):
    # Setup 4 distinct storage roots
    roots = []
    for i in range(4):
        r = tmp_path / f"parallel_root_{i}"
        r.mkdir()
        (r / f"doc_{i}.txt").write_text(f"Content for parallel root {i}", encoding="utf-8")
        roots.append(str(r))

    crawler = MultiRootCrawler(storage_roots=roots, synchronizer=synchronizer, max_workers=4)
    summary = crawler.scan_all_roots(max_workers=4)

    assert summary["parallel_workers"] == 4
    assert summary["total_scanned"] == 4
    assert summary["total_ingested"] == 4
    assert len(summary["processed_roots"]) == 4
    assert summary["total_errors"] == 0

