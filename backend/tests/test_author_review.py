"""Human-in-the-loop review tests for per-document author candidates."""

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.ledger.db import init_db
from backend.ledger.graph_store import PropertyGraphStore
from backend.ledger.repository import DocumentRepository
from backend.ai.graph_schemas import EntityNode, DocumentEntityLink
from backend.api.routes import authors as authors_routes


@pytest.fixture
def review_client(tmp_path, monkeypatch):
    db_file = tmp_path / "author_review.db"
    monkeypatch.setattr("config.settings.DB_PATH", db_file)
    init_db(db_file)
    repo = DocumentRepository(db_path=db_file)
    repo.upsert_document(
        sha256_hash="author-review-doc-1",
        simhash="author-review-simhash",
        canonical_filename="paper.pdf",
        doc_type="technical_report",
        lifecycle_status="final",
        completeness_score=1.0,
        maturity_score=0.9,
        page_count=1,
        text_snippet="A report authored by Ada Lovelace.",
        full_text="A report authored by Ada Lovelace.",
    )
    graph = PropertyGraphStore(repository=repo)
    graph.upsert_node(EntityNode(node_id="person_ada_lovelace", node_type="person", name="Ada Lovelace"))
    graph.link_document_entity(DocumentEntityLink(
        sha256_hash="author-review-doc-1",
        node_id="person_ada_lovelace",
        role="signatory",
        confidence=0.8,
    ))
    repo.conn.execute("""
        INSERT INTO author_candidate_evaluations (
            sha256_hash, node_id, status, confidence, evidence_verified,
            evidence_quote, reason, model, method
        ) VALUES (?, ?, 'qualified', 0.96, 1, ?, ?, 'test-model', 'llm')
    """, (
        "author-review-doc-1",
        "person_ada_lovelace",
        "A report authored by Ada Lovelace.",
        "Exact author attribution in text.",
    ))
    repo.conn.commit()
    repo.close()
    return TestClient(app)


def test_author_candidate_queue_lists_person_signatory_as_unreviewed_candidate(review_client):
    response = review_client.get("/api/v1/authors/candidates")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    candidate = data["items"][0]
    assert candidate["name"] == "Ada Lovelace"
    assert candidate["status"] == "pending"
    assert candidate["canonical_filename"] == "paper.pdf"


def test_author_graph_reports_document_corroboration_without_auto_approval(review_client):
    response = review_client.get("/api/v1/authors/graph")

    assert response.status_code == 200
    data = response.json()
    author = next(item for item in data["authors"] if item["node_id"] == "person_ada_lovelace")
    assert author["document_count"] == 1
    assert author["threshold_met"] is False
    assert author["status"] == "pending"
    assert author["auto_approved"] is False
    assert "not authorship evidence" in author["threshold_basis"]
    assert len(data["documents"]) == 1
    assert len(data["edges"]) == 1


def test_ten_candidate_documents_raise_review_eligibility_but_do_not_approve(review_client):
    repo = DocumentRepository()
    graph = PropertyGraphStore(repository=repo)
    for index in range(2, 11):
        sha = f"author-review-doc-{index}"
        repo.upsert_document(
            sha256_hash=sha,
            simhash=f"simhash-{index}",
            canonical_filename=f"paper-{index}.pdf",
            doc_type="technical_report",
            lifecycle_status="final",
            completeness_score=1.0,
            maturity_score=0.9,
            page_count=1,
            text_snippet="Report by Ada Lovelace.",
        )
        graph.link_document_entity(DocumentEntityLink(
            sha256_hash=sha,
            node_id="person_ada_lovelace",
            role="signatory",
            confidence=0.8,
        ))

    data = review_client.get("/api/v1/authors/graph").json()
    author = next(item for item in data["authors"] if item["node_id"] == "person_ada_lovelace")
    assert author["document_count"] == 10
    assert author["threshold_met"] is True
    assert author["status"] == "pending"
    cur = repo.conn.cursor()
    cur.execute("SELECT COUNT(*) FROM document_entity_links WHERE node_id=? AND role='author'", ("person_ada_lovelace",))
    assert cur.fetchone()[0] == 0


def test_approve_candidate_adds_document_author_role_and_audit(review_client):
    response = review_client.post(
        "/api/v1/authors/candidates/author-review-doc-1/person_ada_lovelace/review",
        json={"decision": "approve", "reviewer": "reviewer@example.test", "note": "Author listed in report."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    repo = DocumentRepository()
    cur = repo.conn.cursor()
    cur.execute("SELECT role FROM document_entity_links WHERE sha256_hash=? AND node_id=?", ("author-review-doc-1", "person_ada_lovelace"))
    assert {row[0] for row in cur.fetchall()} == {"signatory", "author"}
    cur.execute("SELECT action,actor FROM audit_log WHERE sha256_hash=? ORDER BY log_id DESC LIMIT 1", ("author-review-doc-1",))
    audit = cur.fetchone()
    assert audit["action"] == "author_candidate_approved"
    assert audit["actor"] == "reviewer@example.test"


def test_decline_candidate_preserves_original_signatory_link(review_client):
    response = review_client.post(
        "/api/v1/authors/candidates/author-review-doc-1/person_ada_lovelace/review",
        json={"decision": "decline", "reviewer": "reviewer@example.test"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    repo = DocumentRepository()
    cur = repo.conn.cursor()
    cur.execute("SELECT role FROM document_entity_links WHERE sha256_hash=? AND node_id=?", ("author-review-doc-1", "person_ada_lovelace"))
    assert [row[0] for row in cur.fetchall()] == ["signatory"]
    assert review_client.get("/api/v1/authors/candidates?status=pending").json()["total"] == 0
    assert review_client.get("/api/v1/authors/candidates?status=rejected").json()["total"] == 1


def test_review_rejects_unlinked_candidate(review_client):
    response = review_client.post(
        "/api/v1/authors/candidates/author-review-doc-1/person_unknown/review",
        json={"decision": "approve", "reviewer": "reviewer@example.test"},
    )

    assert response.status_code == 404


def test_approved_candidate_can_be_declined_later(review_client):
    path = "/api/v1/authors/candidates/author-review-doc-1/person_ada_lovelace/review"
    approved = review_client.post(path, json={"decision": "approve", "reviewer": "reviewer@example.test"})
    assert approved.status_code == 200

    declined = review_client.post(path, json={"decision": "decline", "reviewer": "reviewer@example.test"})
    assert declined.status_code == 200
    repo = DocumentRepository()
    cur = repo.conn.cursor()
    cur.execute("SELECT role FROM document_entity_links WHERE sha256_hash=? AND node_id=?", ("author-review-doc-1", "person_ada_lovelace"))
    assert [row[0] for row in cur.fetchall()] == ["signatory"]
    assert review_client.get("/api/v1/authors/candidates?status=rejected").json()["total"] == 1


def test_review_requires_valid_decision_and_reviewer(review_client):
    response = review_client.post(
        "/api/v1/authors/candidates/author-review-doc-1/person_ada_lovelace/review",
        json={"decision": "maybe", "reviewer": ""},
    )

    assert response.status_code == 422


def test_unqualified_candidates_are_not_listed_or_approvable(review_client):
    repo = DocumentRepository()
    repo.conn.execute("DELETE FROM author_candidate_evaluations WHERE node_id=?", ("person_ada_lovelace",))
    repo.conn.commit()

    response = review_client.get("/api/v1/authors/candidates")
    assert response.status_code == 200
    assert response.json()["total"] == 0

    approval = review_client.post(
        "/api/v1/authors/candidates/author-review-doc-1/person_ada_lovelace/review",
        json={"decision": "approve", "reviewer": "reviewer@example.test"},
    )
    assert approval.status_code == 409


def test_prevalidation_deterministically_filters_non_name_without_llm(review_client, monkeypatch):
    repo = DocumentRepository()
    repo.conn.execute(
        "UPDATE knowledge_nodes SET name=? WHERE node_id=?",
        ("en mesure de communiquer avec votre logiciel", "person_ada_lovelace"),
    )
    repo.conn.execute("DELETE FROM author_candidate_evaluations WHERE node_id=?", ("person_ada_lovelace",))
    repo.conn.commit()

    def unexpected_llm_call(*_args, **_kwargs):
        raise AssertionError("Deterministic prefilter should block this name before an LLM call")

    monkeypatch.setattr(authors_routes.httpx, "post", unexpected_llm_call)
    response = review_client.post("/api/v1/authors/prevalidate?limit=1")

    assert response.status_code == 200
    assert response.json()["deterministically_filtered"] == 1
    assert response.json()["llm_evaluated"] == 0
    assert review_client.get("/api/v1/authors/candidates").json()["total"] == 0


def test_llm_qualification_requires_grounded_explicit_authorship_quote(review_client, monkeypatch):
    from types import SimpleNamespace

    repo = DocumentRepository()
    repo.conn.execute("DELETE FROM author_candidate_evaluations WHERE node_id=?", ("person_ada_lovelace",))
    repo.conn.execute(
        "DELETE FROM document_fts WHERE sha256_hash=?", ("author-review-doc-1",)
    )
    repo.conn.execute("""
        INSERT INTO document_fts (sha256_hash, canonical_filename, text_content)
        VALUES (?, ?, ?)
    """, (
        "author-review-doc-1", "paper.pdf", "Author: Ada Lovelace. A report authored by Ada Lovelace."
    ))
    repo.conn.commit()

    def fake_llm_post(url, *, json, timeout):
        assert url.endswith("/api/chat")
        assert timeout.connect == 1.2
        assert timeout.read == 1.2
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"message": {"content": json_response}},
        )

    json_response = (
        '{"evaluations":[{"sha256_hash":"author-review-doc-1",'
        '"node_id":"person_ada_lovelace","verdict":"author",'
        '"confidence":0.97,"evidence_quote":"Author: Ada Lovelace.",'
        '"reason":"Explicit author label."}]}'
    )
    monkeypatch.setattr(authors_routes.httpx, "post", fake_llm_post)
    response = review_client.post("/api/v1/authors/prevalidate?limit=1")

    assert response.status_code == 200
    assert response.json()["qualified"] == 1
    listed = review_client.get("/api/v1/authors/candidates").json()
    assert listed["total"] == 1
    assert listed["items"][0]["prevalidation_confidence"] == 0.97
    assert listed["items"][0]["prevalidation_evidence"] == "Author: Ada Lovelace."


def test_remote_ollama_failure_falls_back_to_local_under_ten_seconds(review_client, monkeypatch):
    from types import SimpleNamespace

    repo = DocumentRepository()
    repo.conn.execute("DELETE FROM author_candidate_evaluations WHERE node_id=?", ("person_ada_lovelace",))
    repo.conn.execute("DELETE FROM document_fts WHERE sha256_hash=?", ("author-review-doc-1",))
    repo.conn.execute("""
        INSERT INTO document_fts (sha256_hash, canonical_filename, text_content)
        VALUES (?, ?, ?)
    """, ("author-review-doc-1", "paper.pdf", "Author: Ada Lovelace."))
    repo.conn.commit()

    monkeypatch.setattr(authors_routes.settings, "OLLAMA_EMBED_BASE_URL", "http://remote-ollama:11434")
    monkeypatch.setattr(authors_routes.settings, "OLLAMA_MODEL_PC2", "remote-model")
    monkeypatch.setattr(authors_routes.settings, "OLLAMA_CHAT_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(authors_routes.settings, "OLLAMA_MODEL_PC1", "local-model")
    calls = []
    response_json = (
        '{"evaluations":[{"sha256_hash":"author-review-doc-1",'
        '"node_id":"person_ada_lovelace","verdict":"author",'
        '"confidence":0.97,"evidence_quote":"Author: Ada Lovelace.",'
        '"reason":"Explicit author label."}]}'
    )

    def remote_fails_then_local_responds(url, *, json, timeout):
        calls.append((url, json["model"], timeout))
        if "remote-ollama" in url:
            raise authors_routes.httpx.ConnectTimeout("Remote down")
        return SimpleNamespace(status_code=200, json=lambda: {"message": {"content": response_json}})

    monkeypatch.setattr(authors_routes.httpx, "post", remote_fails_then_local_responds)
    response = review_client.post("/api/v1/authors/prevalidate?limit=1")

    assert response.status_code == 200
    result = response.json()
    assert result["qualified"] == 1
    assert result["fallback_used"] is True
    assert result["llm_node"] == "local"
    assert result["llm_model"] == "local-model"
    assert [call[0] for call in calls] == [
        "http://remote-ollama:11434/api/chat",
        "http://127.0.0.1:11434/api/chat",
    ]
    assert [call[1] for call in calls] == ["remote-model", "local-model"]
    # For an unreachable remote, the connect timeout expires before local fallback.
    # The local timeout is derived from the remaining shared 9.5-second deadline.
    remote_connect_budget = calls[0][2].connect
    local_attempt_budget = sum((
        calls[1][2].connect,
        calls[1][2].read,
        calls[1][2].write,
        calls[1][2].pool,
    ))
    assert remote_connect_budget + local_attempt_budget <= 9.5
    listed = review_client.get("/api/v1/authors/candidates").json()
    assert listed["items"][0]["prevalidation_model"] == "local-model"


def test_high_model_confidence_without_author_quote_does_not_qualify(review_client, monkeypatch):
    from types import SimpleNamespace

    repo = DocumentRepository()
    repo.conn.execute("DELETE FROM author_candidate_evaluations WHERE node_id=?", ("person_ada_lovelace",))
    repo.conn.execute("DELETE FROM document_fts WHERE sha256_hash=?", ("author-review-doc-1",))
    repo.conn.execute("""
        INSERT INTO document_fts (sha256_hash, canonical_filename, text_content)
        VALUES (?, ?, ?)
    """, (
        "author-review-doc-1", "paper.pdf",
        "Author: Ada Lovelace. Tenant: Ada Lovelace signed the contract.",
    ))
    repo.conn.commit()
    response_json = (
        '{"evaluations":[{"sha256_hash":"author-review-doc-1",'
        '"node_id":"person_ada_lovelace","verdict":"author",'
        '"confidence":0.99,"evidence_quote":"Tenant: Ada Lovelace signed the contract.",'
        '"reason":"Mentioned in a contract."}]}'
    )
    monkeypatch.setattr(
        authors_routes.httpx, "post",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=200, json=lambda: {"message": {"content": response_json}}),
    )

    response = review_client.post("/api/v1/authors/prevalidate?limit=1")

    assert response.status_code == 200
    assert response.json()["qualified"] == 0
    assert review_client.get("/api/v1/authors/candidates").json()["total"] == 0


def test_confidence_below_threshold_does_not_enter_review_queue(review_client, monkeypatch):
    from types import SimpleNamespace

    repo = DocumentRepository()
    repo.conn.execute("DELETE FROM author_candidate_evaluations WHERE node_id=?", ("person_ada_lovelace",))
    repo.conn.execute("""
        INSERT INTO document_fts (sha256_hash, canonical_filename, text_content)
        VALUES (?, ?, ?)
    """, ("author-review-doc-1", "paper.pdf", "Author: Ada Lovelace."))
    repo.conn.commit()
    response_json = (
        '{"evaluations":[{"sha256_hash":"author-review-doc-1",'
        '"node_id":"person_ada_lovelace","verdict":"author",'
        '"confidence":0.89,"evidence_quote":"Author: Ada Lovelace.",'
        '"reason":"Possible explicit attribution."}]}'
    )
    monkeypatch.setattr(
        authors_routes.httpx, "post",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=200, json=lambda: {"message": {"content": response_json}}),
    )

    response = review_client.post("/api/v1/authors/prevalidate?limit=1")

    assert response.status_code == 200
    assert response.json()["qualified"] == 0
    assert review_client.get("/api/v1/authors/candidates").json()["total"] == 0


def test_local_model_failure_is_retryable_and_does_not_qualify(review_client, monkeypatch):
    import httpx

    repo = DocumentRepository()
    repo.conn.execute("DELETE FROM author_candidate_evaluations WHERE node_id=?", ("person_ada_lovelace",))
    repo.conn.commit()

    def unavailable(*_args, **_kwargs):
        raise httpx.ConnectTimeout("Ollama unavailable")

    monkeypatch.setattr(authors_routes.httpx, "post", unavailable)
    response = review_client.post("/api/v1/authors/prevalidate?limit=1")

    assert response.status_code == 200
    assert response.json()["status"] == "llm_unavailable"
    assert "Check both Ollama services" in response.json()["message"]
    assert response.json()["llm_evaluated"] == 0
    assert review_client.get("/api/v1/authors/candidates").json()["total"] == 0
    cur = repo.conn.cursor()
    cur.execute("SELECT COUNT(*) FROM author_candidate_evaluations WHERE node_id=?", ("person_ada_lovelace",))
    assert cur.fetchone()[0] == 0


def test_remote_failure_local_fallback_defers_excess_candidates_without_rejecting_them(review_client, monkeypatch):
    from types import SimpleNamespace

    repo = DocumentRepository()
    repo.conn.execute("DELETE FROM author_candidate_evaluations WHERE node_id=?", ("person_ada_lovelace",))
    repo.conn.execute("DELETE FROM document_fts WHERE sha256_hash=?", ("author-review-doc-1",))
    repo.conn.execute("""
        INSERT INTO document_fts (sha256_hash, canonical_filename, text_content)
        VALUES (?, ?, ?)
    """, ("author-review-doc-1", "paper.pdf", "Author: Ada Lovelace."))
    repo.conn.commit()
    for index in range(2, 6):
        sha = f"author-review-doc-{index}"
        repo.upsert_document(
            sha256_hash=sha,
            simhash=f"fallback-{index}",
            canonical_filename=f"paper-{index}.pdf",
            doc_type="technical_report",
            lifecycle_status="final",
            completeness_score=1.0,
            maturity_score=0.9,
            page_count=1,
            text_snippet="Author: Ada Lovelace.",
            full_text="Author: Ada Lovelace.",
        )
        PropertyGraphStore(repository=repo).link_document_entity(DocumentEntityLink(
            sha256_hash=sha,
            node_id="person_ada_lovelace",
            role="signatory",
            confidence=0.8,
        ))

    monkeypatch.setattr(authors_routes.settings, "OLLAMA_EMBED_BASE_URL", "http://remote-ollama:11434")
    monkeypatch.setattr(authors_routes.settings, "OLLAMA_MODEL_PC2", "remote-model")
    monkeypatch.setattr(authors_routes.settings, "OLLAMA_CHAT_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(authors_routes.settings, "OLLAMA_MODEL_PC1", "local-model")
    response_json = '{"evaluations":[]}'

    def remote_fails(url, *, json, timeout):
        if "remote-ollama" in url:
            raise authors_routes.httpx.ConnectTimeout("Remote down")
        assert json["model"] == "local-model"
        assert len(json["messages"][0]["content"]) < 12000
        return SimpleNamespace(status_code=200, json=lambda: {"message": {"content": response_json}})

    monkeypatch.setattr(authors_routes.httpx, "post", remote_fails)
    response = review_client.post("/api/v1/authors/prevalidate?limit=5")

    assert response.status_code == 200
    data = response.json()
    assert data["fallback_used"] is True
    assert data["llm_node"] == "local"
    assert data["llm_evaluated"] == 3
    assert data["deferred_for_next_batch"] == 2
    cur = repo.conn.cursor()
    cur.execute("SELECT COUNT(*) FROM author_candidate_evaluations WHERE method='llm_local'")
    assert cur.fetchone()[0] == 3
