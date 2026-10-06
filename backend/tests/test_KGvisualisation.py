import json
from fastapi.testclient import TestClient
from reposcroller.api.app import app
from reposcroller.ledger.graph_store import PropertyGraphStore


def test_kg_3d_visualisation():
    client = TestClient(app)
    res = client.get('/api/v1/sidecar/graph-3d?limit=50')
    assert res.status_code == 200
    data = res.json()
    g = PropertyGraphStore()
    res = g.get_3d_knowledge_universe(limit=50)

    assert len(data.get('nodes', [])) > 0
    assert len(data.get('edges', [])) > 0
    assert len(data.get('clusters', [])) > 0
    assert len(data.get('axes', {})) == 3

    print('Edges:', len(res['edges']))
    print('Clusters:', [(c['id'], c['name'], c['color']) for c in res['clusters']])
    print('Axes:', res['axes'])
    print('Sample node:', res['nodes'][0])
    assert len(res['nodes']) > 0
    assert len(res['edges']) > 0
    assert len(res['clusters']) > 0
    assert len(res['axes']) == 3
    print('Test passed!')

    print('Nodes:', len(res['nodes']))
    print('Clusters:', [(c['id'], c['name'], c['color']) for c in res['clusters']])
    print('Sample node:', res['nodes'][0])
    assert len(res['nodes']) > 0
    assert len(res['clusters']) > 0
    assert len(res['axes']) == 3
    print('Test passed!')