"""Unit tests for LangGraph DuplicateResolverAgent."""

from pathlib import Path
from reposcroller.agents.duplicate_agent import DuplicateResolverAgent
from reposcroller.core.synchronizer import DocumentSynchronizer
from reposcroller.ledger.repository import DocumentRepository


def test_agent_exact_match(synchronizer: DocumentSynchronizer, sample_files, repo: DocumentRepository):
    # Ingest file into ledger
    synchronizer.process_file(sample_files["final"], sample_files["root_a"])

    agent = DuplicateResolverAgent(repo=repo)
    # Interrogate with exact file
    res = agent.interrogate(file_path=str(sample_files["final"]))

    assert res["status_category"] == "EXACT_MATCH"
    assert "Exact Copy Available" in res["answer"]
    assert sample_files["final"].name in res["answer"]
    assert res["canonical_document"] is not None


def test_agent_near_duplicate_draft_detection(synchronizer: DocumentSynchronizer, sample_files, repo: DocumentRepository):
    # Ingest final contract
    synchronizer.process_file(sample_files["final"], sample_files["root_a"])

    agent = DuplicateResolverAgent(repo=repo)
    # Interrogate with draft copy
    res = agent.interrogate(file_path=str(sample_files["draft"]))

    assert res["status_category"] in ["EVOLVED_VERSION", "DRAFT_EXISTS"]
    assert "Existing Version Found" in res["answer"]
    assert res["canonical_document"]["canonical_filename"] == sample_files["final"].name


def test_agent_not_found(repo: DocumentRepository):
    agent = DuplicateResolverAgent(repo=repo)
    res = agent.interrogate(query="Non-existent tax decree 1999")

    assert res["status_category"] == "NOT_FOUND"
    assert "No matching copy or related document" in res["answer"]
    assert "safe to ingest" in res["recommendation"]
