"""Unit tests for heuristic maturity scoring and lifecycle categorization."""

from pathlib import Path
from reposcroller.integrity.maturity import MaturityEvaluator


def test_maturity_final_signed():
    evaluator = MaturityEvaluator()
    file_path = Path("Contract_2024_signed.pdf")
    text = (
        "Official Agreement.\n"
        "Here are all terms and conditions fulfilled.\n"
        "Date: 2024-06-01\n"
        "Qualifizierte elektronische Signatur\n"
        "Unterschrift: Alice Dupont\n"
        "Conclusion: Contract is valid and finalized."
    )
    metadata = {"page_count": 5, "has_digital_signature": True}

    res = evaluator.evaluate(file_path, text, metadata)
    assert res["lifecycle_status"] == "final"
    assert res["maturity_score"] >= 0.70
    assert res["signature_score"] == 1.0
    assert res["version_tag"] == "final"
    assert not res["truncation_detected"]


def test_maturity_draft():
    evaluator = MaturityEvaluator()
    file_path = Path("Contract_2024_draft_v1.txt")
    text = "Short preliminary proposal. Incomplete discussion points."
    metadata = {"page_count": 1, "has_digital_signature": False}

    res = evaluator.evaluate(file_path, text, metadata)
    assert res["lifecycle_status"] == "draft"
    assert res["maturity_score"] < 0.55
    assert res["version_tag"] in ["draft", "v1"]


def test_maturity_truncated():
    evaluator = MaturityEvaluator()
    file_path = Path("Scanned_Decision_part1.txt")
    text = "The court decided that... [cut] [truncated]..."
    metadata = {"page_count": 1, "has_digital_signature": False}

    res = evaluator.evaluate(file_path, text, metadata)
    assert res["lifecycle_status"] == "truncated"
    assert res["truncation_detected"] is True
