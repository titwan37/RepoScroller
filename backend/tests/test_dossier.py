"""Unit and integration tests for Entity Portrait & Risk Dossier generation."""

import pytest
from fastapi.testclient import TestClient
from backend.api.app import create_app
from backend.ledger.repository import DocumentRepository
from backend.api.routes.dossier import _generate_deterministic_dossier


@pytest.fixture(scope="module")
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture(scope="module")
def repo():
    return DocumentRepository()


def test_repository_get_entity_portrait_context(repo):
    """Test repository context extraction for a known entity."""
    ctx = repo.get_entity_portrait_context("PostFinance SA", depth=2)
    assert "focus_node" in ctx
    assert "edges" in ctx
    assert "action_items" in ctx
    assert "documents" in ctx
    assert ctx["focus_node"]["name"] is not None


def test_deterministic_dossier_generator():
    """Verify that the deterministic fallback produces valid Markdown with Mermaid blocks."""
    dummy_ctx = {
        "focus_node": {"name": "Acme Corp", "node_type": "organization"},
        "edges": [
            {
                "source_name": "Acme Corp",
                "relation_type": "GOVERNED_BY",
                "target_name": "Regulatory Board",
                "source_id": "org_acme",
                "target_id": "org_board"
            }
        ],
        "action_items": [
            {
                "action_type": "payment",
                "description": "Annual audit fee",
                "amount": "1500",
                "currency": "CHF",
                "due_date": "2026-11-01",
                "status": "pending",
                "canonical_filename": "Audit_Agreement.pdf"
            }
        ],
        "documents": [
            {
                "canonical_filename": "Audit_Agreement.pdf",
                "doc_date": "2026-01-15",
                "doc_type": "contract"
            }
        ]
    }
    md = _generate_deterministic_dossier(dummy_ctx)
    assert "# Portrait & Relational Dynamics: Acme Corp" in md
    assert "```mermaid" in md
    assert "graph TD" in md
    assert "sequenceDiagram" in md
    assert "## 3. Structural Concerns & Friction Points" in md
    assert "## 4. Operational & Legal Risks" in md


def test_dossier_generate_json_endpoint(client):
    """Verify that POST /api/v1/dossier/generate returns a structured JSON payload when stream=False."""
    resp = client.post("/api/v1/dossier/generate", json={
        "node_id": "PostFinance SA",
        "stream": False
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert "markdown" in data
    assert len(data["markdown"]) > 50
    assert "portrait" in data["markdown"].lower()
    assert "mermaid" in data["markdown"].lower()


def test_dossier_generate_sse_stream_endpoint(client):
    """Verify that SSE streaming mode delivers data events ending in [DONE]."""
    resp = client.get("/api/v1/dossier/generate?node_id=PostFinance%20SA&stream=true")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data: " in resp.text
    assert "[DONE]" in resp.text


def test_dossier_stream_alias_endpoint(client):
    """Verify convenience route /api/v1/dossier/stream."""
    resp = client.get("/api/v1/dossier/stream?node_id=PostFinance%20SA")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data: " in resp.text


def test_dossier_nonexistent_entity(client):
    """Verify 404 response when querying a completely nonexistent entity."""
    resp = client.post("/api/v1/dossier/generate", json={
        "node_id": "nonexistent_entity_xyz_12345_nowhere",
        "stream": False
    })
    assert resp.status_code == 404
