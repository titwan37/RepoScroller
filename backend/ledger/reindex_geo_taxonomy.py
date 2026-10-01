"""CLI script to backfill and synchronize the hierarchical geo-taxonomy and document links."""

import logging
import sqlite3
from pathlib import Path
from backend.ledger.db import resolve_ledger_db_path, init_db
from backend.ledger.geo_taxonomy import init_geo_taxonomy, backfill_document_geo_links

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("reposcroller.reindex_geo")


def run_reindex(db_path: Path = None):
    target = resolve_ledger_db_path(db_path)
    logger.info(f"Synchronizing Geo-Taxonomy on database: {target}")
    
    init_db(target)
    conn = sqlite3.connect(target)
    try:
        init_geo_taxonomy(conn)
        stats = backfill_document_geo_links(conn)
        logger.info(f"✅ Geo-Taxonomy synchronization finished: {stats}")
    finally:
        conn.close()


if __name__ == "__main__":
    run_reindex()
