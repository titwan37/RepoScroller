import backend.config as cfg
from pathlib import Path

def test_dsada():
    cfg.settings.DB_PATH = Path('backend/data/nonexistent_ledger.db')
    from backend.api.routes.documents import get_ledger_stats, list_documents
    from backend.api.routes.taxonomy import list_taxonomy
    from backend.api.routes.sidecar import get_sidecar_stats
    from backend.api.routes.crawler import get_crawler_status

    print('Documents stats:', get_ledger_stats())
    print('Taxonomy count:', list_taxonomy()['count'])
    print('Crawler roots count:', len(get_crawler_status()['configured_roots']))
    print('Sidecar queue stats:', get_sidecar_stats()['queue'])