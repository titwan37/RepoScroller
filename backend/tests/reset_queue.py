from reposcroller.ledger.repository import DocumentRepository

repo = DocumentRepository()
cur = repo.conn.cursor()
cur.execute("SELECT status, count(1) FROM kb_processing_queue GROUP BY status")
print("Queue status breakdown:", [dict(r) for r in cur.fetchall()])
