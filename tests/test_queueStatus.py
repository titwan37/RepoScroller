import sqlite3
import os

def test_queueStatus():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'reposcroller_ledger.db')
    conn = sqlite3.connect(db_path)

    print(f"Database: {db_path}")
    queue_status = conn.execute('SELECT status, COUNT(*) FROM kb_processing_queue GROUP BY status').fetchall()
    print('Queue status:', queue_status)
    assert queue_status[0][1] > 0, 'Queue should not be empty'

    total_chunks = conn.execute('SELECT COUNT(*) FROM document_chunks').fetchone()[0]
    print('Total chunks:', total_chunks)
    assert total_chunks > 500, 'Total chunks should be greater than 1000'
    conn.close()


def test_localhost():
    import urllib.request, json
    res = urllib.request.urlopen('http://127.0.0.1:8090/api/v1/diagnostics/workload')
    print(json.dumps(json.loads(res.read()), indent=2))

def test_gpu():
    import urllib.request, json
    res = urllib.request.urlopen('http://127.0.0.1:8090/api/v1/sidecar/stats')
    print(json.dumps(json.loads(res.read()), indent=2))

def test_process_document():
    import logging; logging.basicConfig(level=logging.DEBUG); from reposcroller.ai.sidecar_worker import KnowledgeBaseSidecarWorker; w = KnowledgeBaseSidecarWorker();
    sha = 'c8b796d0edb6b2d93db7677149d81b9b35e87a471471d0a37af8d7e3190bc5c8'
    print('Testing process_document for sha:', sha)
    res = w.process_document(sha)
    print('Result:', res)

    import logging, traceback; 
    logging.basicConfig(level=logging.DEBUG); 
    from reposcroller.ai.sidecar_worker import KnowledgeBaseSidecarWorker; 
    w = KnowledgeBaseSidecarWorker();
    sha = 'c8b796d0edb6b2d93db7677149d81b9b35e87a471471d0a37af8d7e3190bc5c8'
    try:
        res = w.process_document({'sha256_hash': sha})
        print('Result:', res)
    except Exception:
        traceback.print_exc()


def test_heuristic():
    import urllib.request, json; 
    res = urllib.request.urlopen('http://127.0.0.1:8090/api/v1/diagnostics/workload?force=true'); 
    data = json.loads(res.read()); print('CUDA Chunks:', data['cuda_gpu_node']['stats']['chunks_embedded']); 
    print('Tier:', data['embedding_tier'])

def trace_telemetry():
    import traceback; 
    from reposcroller.ai.telemetry import workload_telemetry;
    from reposcroller.ledger.repository import DocumentRepository; 
    try:
        res = workload_telemetry.get_node_probes(force=True)
        print('Telemetry succeeded:', res['cuda_gpu_node']['stats'])
    except Exception:
        traceback.print_exc()

    res = workload_telemetry.get_node_probes(force=True); 
    print('Result:', res['cuda_gpu_node']['stats'])
    repo = DocumentRepository(); 
    cur = repo.conn.cursor(); 
    cur.execute('UPDATE kb_processing_queue SET status = ''pending'' WHERE status = ''processing'''); 
    repo.conn.commit(); cur.execute('SELECT status, count(1) FROM kb_processing_queue GROUP BY status'); 
    print(cur.fetchall())

test_queueStatus()
test_localhost() 
test_gpu()
test_process_document()
test_heuristic()
trace_telemetry()