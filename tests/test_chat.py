"""Integration and unit tests for conversational interrogation and chat endpoints."""

import pytest
from fastapi.testclient import TestClient
from reposcroller.api.app import app
from reposcroller.ledger.db import init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.agents.duplicate_agent import DuplicateResolverAgent
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


def test_chat_interrogate_with_natural_language_query(client: TestClient, sample_files, synchronizer: DocumentSynchronizer):
    # Ingest a sample document
    synchronizer.process_file(sample_files["final"], sample_files["root_a"])
    filename = sample_files["final"].name

    # Ask with natural language question including quotes and .pdf extension
    query = f'Do we have any copy or draft of "{filename}"?'
    resp = client.post("/api/v1/chat/interrogate", json={"query": query})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status_category"] in ["RELATED_DOCUMENT", "EXACT_MATCH", "MULTIPLE_MATCHES"]
    assert filename in data["answer"]


def test_chat_stream_endpoint(client: TestClient, sample_files, synchronizer: DocumentSynchronizer):
    synchronizer.process_file(sample_files["final"], sample_files["root_a"])
    filename = sample_files["final"].name

    resp = client.get(f"/api/v1/chat/stream?query={filename}")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data:" in resp.text
