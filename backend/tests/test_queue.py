from reposcroller.ledger.repository import DocumentRepository
r = DocumentRepository()
print('Queue stats:', r.get_kb_queue_stats())