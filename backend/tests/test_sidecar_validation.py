"""Tests for sidecar knowledge graph entity validation and audit activities."""

import pytest
from fastapi.testclient import TestClient
from reposcroller.api.app import app
from reposcroller.ai.sidecar_worker import KnowledgeBaseSidecarWorker


def test_sidecar_worker_validate_entities_deterministic():
    """Verify that KnowledgeBaseSidecarWorker can execute validation in dry-run mode."""
    worker = KnowledgeBaseSidecarWorker()
    res = worker.validate_entities(limit=5, dry_run=True, run_deterministic=True, run_llm=False)
    
    assert res["status"] == "completed"
    assert "deterministic" in res
    assert "timestamp" in res
    
    status = worker.get_continuous_status()
    assert "validation" in status
    assert "validator_stage" in status["pipeline"]
    assert status["validation"]["stage"] == "idle"


def test_api_sidecar_validate_entities_endpoint():
    """Verify that POST /api/v1/sidecar/validate-entities executes successfully."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/sidecar/validate-entities",
        json={"limit": 5, "dry_run": True, "deterministic_only": True}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "result" in data
    assert data["result"]["status"] == "completed"


def test_api_rag_search_endpoint():
    """Verify that GET /api/v1/rag/search responds with 200 OK and expected structure."""
    client = TestClient(app)
    response = client.get("/api/v1/rag/search?q=contrat&top_k=2")
    assert response.status_code == 200
    data = response.json()
    assert "top_candidates" in data
    assert "retrieval_signals" in data

