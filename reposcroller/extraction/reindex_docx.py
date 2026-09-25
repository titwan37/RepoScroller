from pathlib import Path
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.extraction.text_extractor import extract_document_data
from reposcroller.ai.sidecar_worker import KnowledgeBaseSidecarWorker

repo = DocumentRepository()
worker = KnowledgeBaseSidecarWorker(repository=repo)
count = 0

docs = repo.get_all_documents(limit=500)
for doc in docs:
    fname = doc.get("canonical_filename", "")
    sha = doc["sha256_hash"]
    if fname.lower().endswith(".docx") and not Path(fname).name.startswith("~$"):
        doc_details = repo.get_document_by_sha256(sha)
        locs = (doc_details.get("locations") if doc_details else []) or []
        for loc in locs:
            p = Path(loc["absolute_path"])
            if p.exists() and p.is_file():
                text, meta = extract_document_data(p)
                if text:
                    with repo._lock:
                        cur = repo.conn.cursor()
                        cur.execute(
                            "UPDATE document_ledger SET text_snippet = ? WHERE sha256_hash = ?",
                            (text[:500], sha)
                        )
                        repo.conn.commit()
                    worker.process_document(doc)
                    count += 1
                    print(f"Cleaned & re-indexed DOCX: {fname}")
                    break

print(f"Done. Total reprocessed: {count}")
