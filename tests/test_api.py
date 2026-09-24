"""Integration tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient
from reposcroller.api.app import app
from reposcroller.ledger.db import init_db


@pytest.fixture(autouse=True)
def setup_api_db(tmp_path, monkeypatch):
    test_db = tmp_path / "api_test_ledger.db"
    monkeypatch.setattr("reposcroller.config.settings.DB_PATH", test_db)
    init_db(test_db)


@pytest.fixture
def client():
    return TestClient(app)


def test_root_endpoint(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "RepoScroller" in resp.text

    health_resp = client.get("/api/v1/health")
    assert health_resp.status_code == 200
    data = health_resp.json()
    assert data["app"] == "RepoScroller"
    assert data["alcoa_compliant"] is True


def test_documents_ledger_empty(client: TestClient):
    resp = client.get("/api/v1/documents/ledger")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_records"] == 0
    assert data["items"] == []


def test_crawler_status(client: TestClient):
    resp = client.get("/api/v1/crawler/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "configured_roots" in data
    assert "polling_observer_running" in data


def test_chat_interrogate_not_found(client: TestClient):
    resp = client.post(
        "/api/v1/chat/interrogate",
        json={"query": "Do we have decision 2024?"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status_category"] == "NOT_FOUND"


def test_preflight_check_upload(client: TestClient):
    file_bytes = b"Contract terms between party A and B for testing preflight upload."
    resp = client.post(
        "/api/v1/documents/check-duplicate",
        files={"file": ("test_doc.txt", file_bytes, "text/plain")}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "status_category" in data
    assert "answer" in data


def test_documents_ledger_filtering_and_sorting(client: TestClient):
    # Insert two test documents
    from reposcroller.ledger.repository import DocumentRepository
    repo = DocumentRepository()
    repo.upsert_document(
        sha256_hash="1111111111111111111111111111111111111111111111111111111111111111",
        simhash="12345",
        canonical_filename="b_contract.pdf",
        doc_type="legal_contract",
        lifecycle_status="final",
        completeness_score=1.0,
        maturity_score=0.9,
        page_count=2,
        text_snippet="Contract snippet"
    )
    repo.record_location(
        sha256_hash="1111111111111111111111111111111111111111111111111111111111111111",
        storage_root=r"\\SyNAS\xcloud\docs",
        relative_path="b_contract.pdf",
        absolute_path=r"\\SyNAS\xcloud\docs\b_contract.pdf",
        file_size=1024,
        mtime=1000.0,
        is_primary=True
    )
    # Add second copy (making it a duplicate)
    repo.record_location(
        sha256_hash="1111111111111111111111111111111111111111111111111111111111111111",
        storage_root=r"H:\Drive\backup",
        relative_path="b_contract.pdf",
        absolute_path=r"H:\Drive\backup\b_contract.pdf",
        file_size=1024,
        mtime=1000.0,
        is_primary=False
    )

    repo.upsert_document(
        sha256_hash="2222222222222222222222222222222222222222222222222222222222222222",
        simhash="67890",
        canonical_filename="a_tax.pdf",
        doc_type="tax_assessment",
        lifecycle_status="draft",
        completeness_score=0.5,
        maturity_score=0.3,
        page_count=1,
        text_snippet="Tax notice snippet"
    )
    repo.record_location(
        sha256_hash="2222222222222222222222222222222222222222222222222222222222222222",
        storage_root=r"\\SyNAS\xcloud\docs",
        relative_path="a_tax.pdf",
        absolute_path=r"\\SyNAS\xcloud\docs\a_tax.pdf",
        file_size=512,
        mtime=1200.0,
        is_primary=True
    )

    # 1. Test duplicate filter
    resp = client.get("/api/v1/documents/ledger?only_duplicates=true")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["canonical_filename"] == "b_contract.pdf"
    assert len(data["items"][0]["locations"]) == 2

    # 2. Test category filter
    resp_cat = client.get("/api/v1/documents/ledger?category=tax_assessment")
    assert resp_cat.status_code == 200
    data_cat = resp_cat.json()
    assert len(data_cat["items"]) == 1
    assert data_cat["items"][0]["canonical_filename"] == "a_tax.pdf"

    # 3. Test sort by canonical_filename ASC
    resp_sort_asc = client.get("/api/v1/documents/ledger?sort_by=canonical_filename&sort_order=ASC")
    assert resp_sort_asc.status_code == 200
    assert resp_sort_asc.json()["items"][0]["canonical_filename"] == "a_tax.pdf"

    # 4. Test sort by canonical_filename DESC
    resp_sort_desc = client.get("/api/v1/documents/ledger?sort_by=canonical_filename&sort_order=DESC")
    assert resp_sort_desc.status_code == 200
    assert resp_sort_desc.json()["items"][0]["canonical_filename"] == "b_contract.pdf"


def test_open_file_endpoint(client: TestClient, monkeypatch):
    # Empty path -> 400
    resp_empty = client.post("/api/v1/documents/open-file", json={"file_path": ""})
    assert resp_empty.status_code == 400

    # Mock os.startfile and subprocess.Popen
    opened_paths = []
    revealed_paths = []

    def mock_startfile(p):
        opened_paths.append(p)

    def mock_popen(cmd, *args, **kwargs):
        revealed_paths.append(cmd)

    import os
    import subprocess
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", mock_startfile)
    else:
        monkeypatch.setattr(subprocess, "Popen", mock_popen)

    unc_path = r"\\SyNAS\xcloud\docs\20200429225658_bitmap_iDéa_Possible_Interview_questions(2p).pdf"
    
    # Test open file directly
    resp = client.post("/api/v1/documents/open-file", json={"file_path": unc_path, "reveal": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["path"] == unc_path

    # Test reveal in explorer
    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    resp_reveal = client.post("/api/v1/documents/open-file", json={"file_path": unc_path, "reveal": True})
    assert resp_reveal.status_code == 200
    assert resp_reveal.json()["revealed"] is True


def test_diagnostics_health_and_telemetry(client: TestClient):
    resp = client.get("/api/v1/diagnostics/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime" in data
    assert "database" in data
    assert "storage" in data
    assert data["database"]["wal_mode"] is True
    assert data["storage"]["total_configured"] == 6


def test_diagnostics_logs_lifecycle(client: TestClient):
    # Clear buffer
    client.post("/api/v1/diagnostics/clear")

    # Trigger synthetic test issue
    resp_trigger = client.post("/api/v1/diagnostics/test-issue?level=WARNING")
    assert resp_trigger.status_code == 200

    # Fetch logs
    resp_logs = client.get("/api/v1/diagnostics/logs")
    assert resp_logs.status_code == 200
    data = resp_logs.json()
    assert data["count"] >= 1
    assert any("Synthetic test warning" in l["message"] for l in data["logs"])

    # Report frontend error
    resp_report = client.post("/api/v1/diagnostics/report", json={
        "message": "Uncaught TypeError: Cannot read properties of undefined",
        "stack": "TypeError: Cannot read properties of undefined at app.js:42",
        "level": "ERROR",
        "url": "http://localhost:8090/"
    })
    assert resp_report.status_code == 200

    # Verify frontend report in unified log
    resp_logs2 = client.get("/api/v1/diagnostics/logs?source=frontend")
    assert resp_logs2.status_code == 200
    frontend_logs = resp_logs2.json()["logs"]
    assert len(frontend_logs) >= 1
    assert "Uncaught TypeError" in frontend_logs[-1]["message"]


