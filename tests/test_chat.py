"""Integration and unit tests for conversational interrogation and chat endpoints."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from reposcroller.api.app import app
from reposcroller.ledger.db import init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.integrity.maturity import MaturityEvaluator
from reposcroller.core.synchronizer import DocumentSynchronizer


@pytest.fixture(autouse=True)
def setup_api_db(tmp_path, monkeypatch):
    test_db = tmp_path / "chat_test_ledger.db"
    monkeypatch.setattr("reposcroller.config.settings.DB_PATH", test_db)
    init_db(test_db)


@pytest.fixture
def client():
    return TestClient(app)


def test_chat_interrogate_endpoint_not_found(client: TestClient):
    payload = {"query": "Non-existent contract decision 2099"}
    resp = client.post("/api/v1/chat/interrogate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status_category"] == "NOT_FOUND"
    assert "No matching copy or related document" in data["answer"]


def test_chat_interrogate_with_natural_language_query(client: TestClient, sample_files):
    # Ingest using DocumentRepository connected to the test DB
    repo = DocumentRepository()
    synchronizer = DocumentSynchronizer(repository=repo, maturity_evaluator=MaturityEvaluator())
    rec = synchronizer.process_file(sample_files["final"], sample_files["root_a"])
    filename = sample_files["final"].name

    # Ask with natural language question including quotes
    query = f'Do we have any copy or draft of "{filename}"?'
    resp = client.post("/api/v1/chat/interrogate", json={"query": query})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status_category"] in ["RELATED_DOCUMENT", "EXACT_MATCH", "MULTIPLE_MATCHES"]
    assert filename in data["answer"]


def test_conversational_question_without_mentioning_document(client: TestClient, sample_files):
    # Ingest document
    repo = DocumentRepository()
    synchronizer = DocumentSynchronizer(repository=repo, maturity_evaluator=MaturityEvaluator())
    rec = synchronizer.process_file(sample_files["final"], sample_files["root_a"])

    # Conversational question without mentioning the document name, passing active sha256_hash
    query = "Who signed this agreement?"
    resp = client.post("/api/v1/chat/interrogate", json={
        "query": query,
        "sha256_hash": rec["sha256"]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status_category"] == "DOCUMENT_QA"
    assert "Alice" in data["answer"] or "Signatory" in data["answer"]


def test_travel_destination_question_about_active_document(client: TestClient, tmp_path):
    repo = DocumentRepository()
    travel_folder = tmp_path / "Commerce" / "Voyage" / "Tenerife"
    travel_folder.mkdir(parents=True)
    pdf_file = travel_folder / "BoardingPass (1-AFA).pdf"
    pdf_file.write_text("Boarding pass passenger John Doe Flight Tenerife TFS to Zurich ZRH", encoding="utf-8")

    from reposcroller.integrity.hasher import compute_sha256
    from reposcroller.integrity.simhash import compute_simhash
    sha = compute_sha256(pdf_file)
    sim = compute_simhash("Boarding pass passenger John Doe Flight Tenerife TFS to Zurich ZRH")

    repo.upsert_document(
        sha256_hash=sha,
        simhash=sim,
        canonical_filename="BoardingPass (1-AFA).pdf",
        doc_type="pdf",
        lifecycle_status="final",
        completeness_score=0.8,
        maturity_score=0.665,
        page_count=1,
        text_snippet="Boarding pass passenger John Doe Flight Tenerife TFS to Zurich ZRH",
        doc_date="2024-05-12",
        doc_date_source="content"
    )
    repo.record_location(
        sha256_hash=sha,
        storage_root=str(tmp_path),
        relative_path="Commerce/Voyage/Tenerife/BoardingPass (1-AFA).pdf",
        absolute_path=str(pdf_file),
        file_size=pdf_file.stat().st_size,
        mtime=pdf_file.stat().st_mtime,
        is_primary=True
    )

    # Question asked without mentioning "BoardingPass (1-AFA).pdf"
    resp = client.post("/api/v1/chat/interrogate", json={
        "query": "where was this travel about ?",
        "sha256_hash": sha
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status_category"] == "DOCUMENT_QA"
    assert "Tenerife" in data["answer"]


def test_chat_stream_endpoint(client: TestClient, sample_files):
    repo = DocumentRepository()
    synchronizer = DocumentSynchronizer(repository=repo, maturity_evaluator=MaturityEvaluator())
    rec = synchronizer.process_file(sample_files["final"], sample_files["root_a"])
    filename = sample_files["final"].name

    resp = client.get(f"/api/v1/chat/stream?query={filename}&sha256_hash={rec['sha256']}")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data:" in resp.text
    assert "active_doc" in resp.text