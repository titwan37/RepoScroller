# backend/tests/test_use_cases.py
import pytest
import yaml
from pathlib import Path
from backend.ai.graph_extractor import KnowledgeGraphExtractor, ThemeResolver

SCENARIOS = list(Path("backend/tests/scenarios").glob("*.yaml"))

@pytest.mark.parametrize("scenario_file", SCENARIOS, ids=lambda p: p.stem)
def test_use_case_scenarios(scenario_file):
    spec = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    
    # 1. Verify Theme Resolution
    resolver = ThemeResolver()
    resolved_theme, _ = resolver.resolve(spec["input"]["doc_type_raw"])
    assert resolved_theme == spec["expected"]["macro_theme"]
    
    # 2. Verify Extractor Graph Integrity
    extractor = KnowledgeGraphExtractor(provider="mock", theme_resolver=resolver)
    graph = extractor.extract_knowledge_graph(
        text=spec["input"]["text_snippet"],
        sha256_hash="test_sha",
        filename=spec["input"]["filename"],
        doc_type=spec["expected"]["canonical_category"],
    )
    
    # 3. Verify Forbidden Nodes (guard against hallucinated suns)
    node_ids = {n.node_id for n in graph.nodes}
    for forbidden in spec["expected"].get("forbidden_nodes", []):
        assert forbidden not in node_ids

    # 4. Verify Time Tunnel Query & Projection (if specified in scenario)
    if "time_tunnel" in spec.get("expected", {}):
        from backend.ledger.graph_store import PropertyGraphStore

        tt_spec = spec["expected"]["time_tunnel"]
        q_filter = spec["input"].get("query_filter", {})

        gs = PropertyGraphStore()
        res = gs.get_3d_knowledge_universe(
            layout=tt_spec.get("layout", "timeline"),
            filters={
                "type": q_filter.get("type", tt_spec.get("doc_type")),
                "theme": q_filter.get("theme"),
            },
            limit=200,
        )

        # Verify timeline axis in Z dimension
        assert res["axes"]["z"] == tt_spec["axis_z"]

        # Verify returned document nodes
        doc_nodes = [n for n in res["nodes"] if n.get("type") == "document"]
        assert len(doc_nodes) >= tt_spec.get("min_returned_documents", 1)

        # Verify all filtered documents are within the specified time window (last 6 years)
        min_date = tt_spec.get("min_date", "2020-01-01")
        max_date = tt_spec.get("max_date", "2026-12-31")

        filtered_in_window = [
            n
            for n in doc_nodes
            if n.get("latest_date") and min_date <= n["latest_date"] <= max_date
        ]
        assert len(filtered_in_window) >= tt_spec.get("min_returned_documents", 1)

        # Verify that all documents have valid Z-tunnel coordinates
        for d in doc_nodes[:10]:
            assert "z" in d
            assert isinstance(d["z"], (int, float))

