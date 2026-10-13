import argparse
import sys
import logging
import warnings
from pathlib import Path

# Fix Windows console charmap encoding for emojis
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from backend.ai.taxonomy import TaxonomyRefiner

# Silence harmless third-party LangChain/LangGraph internal deprecation warnings
warnings.filterwarnings("ignore", message=".*LangChainPendingDeprecationWarning.*")
warnings.filterwarnings("ignore", message=".*allowed_objects.*")

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from backend.config import settings
from backend.ledger.db import init_db
from backend.ledger.repository import DocumentRepository
from backend.core.crawler import MultiRootCrawler
from backend.agents.duplicate_agent import DuplicateResolverAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)



def main():
    parser = argparse.ArgumentParser(
        prog="reposcroller",
        description="RepoScroller: Multi-tier Document Ingestion & Procedural Intelligence"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: serve
    serve_p = subparsers.add_parser("serve", help="Run the FastAPI backend server")
    serve_p.add_argument("--host", default=settings.HOST, help="Host to bind")
    serve_p.add_argument("--port", type=int, default=settings.PORT, help="Port to bind")
    serve_p.add_argument("--reload", action="store_true", help="Auto-reload on changes")

    # Command: scan
    scan_p = subparsers.add_parser("scan", help="Run batch scan across storage roots")
    scan_p.add_argument("--root", help="Specific root to scan (optional)")
    scan_p.add_argument("--force", action="store_true", help="Force re-processing of unchanged files")
    scan_p.add_argument("--order", choices=["antichronological", "chronological", "alphabetical", "default"], default=settings.SCAN_ORDER, help="Crawl traversal order (default: antichronological - newest first)")
    scan_p.add_argument("--workers", type=int, default=settings.SCAN_PARALLEL_WORKERS, help=f"Concurrent worker threads (default: {settings.SCAN_PARALLEL_WORKERS}, 1 per repository)")

    # Command: watch
    subparsers.add_parser("watch", help="Start continuous PollingObserver for all accessible roots")

    # Command: stats
    subparsers.add_parser("stats", help="Display ledger statistics")

    # Command: check
    check_p = subparsers.add_parser("check", help="Pre-flight check if a file has duplicates in the repository")
    check_p.add_argument("file", help="Path to file to inspect")

    # Command: interrogate
    chat_p = subparsers.add_parser("interrogate", help="Ask the chatbot about document availability")
    chat_p.add_argument("query", help="Question to ask (e.g. 'Do we have the 2024 Kantonsgericht decision?')")
    chat_p.add_argument("--node", choices=["pc1", "pc2", "localhost", "cuda"], default=None, help="Routing node for api/chat (pc1: CPU / pc2: CUDA RTX 3060)")
    chat_p.add_argument("--model", default=None, help="Target LLM model (e.g. llama3.2:3b or llama3.1:8b)")

    # Command: rag
    rag_p = subparsers.add_parser("rag", help="Query the Knowledge Base using Hybrid Multi-Signal GraphRAG")
    rag_p.add_argument("query", help="Search question or clause inquiry")
    rag_p.add_argument("--sha", default=None, help="Anchor specific document SHA-256 hash")
    rag_p.add_argument("--top-k", type=int, default=5, help="Number of context chunks to return (default: 5)")
    rag_p.add_argument("--hops", type=int, default=1, help="Knowledge graph expansion hops (default: 1)")

    # Command: sidecar
    sidecar_p = subparsers.add_parser("sidecar", help="Run the Knowledge Base Sidecar Worker to chunk and embed documents")
    sidecar_p.add_argument("--batch", action="store_true", help="Process pending items once and exit")
    sidecar_p.add_argument("--limit", type=int, default=10, help="Number of documents to process in batch")
    sidecar_p.add_argument("--poll-interval", type=float, default=3.0, help="Poll interval in seconds for continuous mode")
    # Command: reset
    reset_p = subparsers.add_parser("reset", help="Reset ledger database, FTS5 index, and queue (with optional backup)")
    reset_p.add_argument("--backup", action="store_true", default=True, help="Create a .bak backup of the existing database (default: True)")
    reset_p.add_argument("--no-backup", dest="backup", action="store_false", help="Do not create a backup file")
    reset_p.add_argument("-y", "--yes", action="store_true", help="Confirm reset non-interactively")

    # Command: reindex-banking
    subparsers.add_parser("reindex-banking", help="Re-index and resolve banking entities (Zuger Kantonalbank, PostFinance SA) and backfill document links")

    # Command: reindex-career
    subparsers.add_parser("reindex-career", help="Re-index and backfill misclassified career cover letters, application letters, and profiles")

    # Command: backfill-obligations
    subparsers.add_parser("backfill-obligations", help="Backfill reception_date, due_date, and actionable obligations using existing DB records and chunks")

    # Command: ingest-themes
    ingest_parser = subparsers.add_parser(
        "ingest-themes", 
        help="Ingest a manually reviewed foundational themes JSON file into the database"
    )
    ingest_parser.add_argument("file_path", type=str, help="Path to the foundational_themes.json file")


    # Command: embed-test
    embed_test_p = subparsers.add_parser("embed-test", help="Test local/remote Ollama embeddings endpoint, latency, and vector dimensions")
    embed_test_p.add_argument("--text", default="RepoScroller sovereign document intelligence test", help="Sample text to embed")

    args = parser.parse_args()

    if args.command == "reset":
        if not args.yes:
            confirm = input("Are you sure you want to reset the RepoScroller ledger database and index? (y/N): ")
            if confirm.lower() not in ["y", "yes"]:
                print("Reset cancelled.")
                return

        import os
        import shutil
        from backend.ledger.qdrant_plugin import QdrantVectorStorePlugin

        db_file = Path(settings.DB_PATH)
        wal_file = Path(f"{settings.DB_PATH}-wal")
        shm_file = Path(f"{settings.DB_PATH}-shm")

        if db_file.exists():
            if args.backup:
                bak_path = Path(f"{settings.DB_PATH}.bak")
                print(f"Creating database backup at '{bak_path}'...")
                shutil.copy2(db_file, bak_path)

        # 1. Truncate / Drop all tables and recreate schema cleanly
        from backend.ledger.db import get_db_connection
        from backend.ledger.schema import SCHEMA_SQL
        
        try:
            conn = get_db_connection()
            conn.execute("PRAGMA foreign_keys = OFF;")
            cur = conn.cursor()
            cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%';")
            objects = cur.fetchall()
            for obj in objects:
                obj_name = obj["name"]
                obj_type = obj["type"].upper()
                try:
                    conn.execute(f"DROP {obj_type} IF EXISTS \"{obj_name}\";")
                except Exception:
                    pass
            conn.commit()
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            conn.execute("VACUUM;")
            conn.close()
            print("Successfully truncated and recreated all SQLite tables and FTS5 indices.")
        except Exception as e:
            print(f"Error resetting database via SQL: {e}")

        # 2. Clear Qdrant collection if active
        qdrant = QdrantVectorStorePlugin()
        if qdrant.is_available:
            print("Clearing Qdrant vector collection...")
            qdrant.clear_collection()

        print("Re-initializing pristine database schema with UTF-8 encoding...")
        init_db()
        print("Database reset completed successfully! You can now start scanning.")
        return

    # Ensure DB is initialized
    init_db()

    if args.command == "serve":
        print(f"Starting RepoScroller API at http://{args.host}:{args.port}...")
        uvicorn.run("api.app:app", host=args.host, port=args.port, reload=args.reload)

    elif args.command == "ingest-themes":
        from backend.ai.taxonomy import TaxonomyRefiner
        refiner = TaxonomyRefiner()
        refiner.ingest_reviewed_themes(args.file_path)

    elif args.command == "scan":
        crawler = MultiRootCrawler(
            storage_roots=[args.root] if args.root else None,
            max_workers=args.workers
        )
        accessible = [r for r in crawler.storage_roots if crawler.is_root_accessible(r)]
        active_pool = min(args.workers, len(accessible) or 1)
        print(f"Starting parallel batch crawl across {len(crawler.storage_roots)} roots ({len(accessible)} online) using {active_pool} concurrent threads in [{args.order}] order...")

        def print_progress(filepath: Path, status: str, stats: dict):
            badge = {
                "ingested": "[NEW]",
                "exact_duplicate_recorded": "[DUPLICATE]",
                "unchanged": "[UNCHANGED]",
                "error": "[ERROR]"
            }.get(status, f"[{status}]")
            # Print brief update
            print(f" {badge:<13} {filepath.name[:45]:<45} (Total: {stats['scanned']} | New: {stats['ingested']} | Dupa: {stats['duplicates']} | Cached: {stats['unchanged']})")

        try:
            summary = crawler.scan_all_roots(
                force_reprocess=args.force,
                progress_callback=print_progress,
                order=args.order,
                max_workers=args.workers
            )
        except KeyboardInterrupt:
            print("\n\nScan paused by user (Ctrl+C). All files processed up to this point are saved and committed to the ledger.")
            return

        print("\n--- Scan Summary ---")
        print(f"Total Scanned:    {summary['total_scanned']}")
        print(f"Ingested (New):   {summary['total_ingested']}")
        print(f"Duplicates Found: {summary['total_duplicates_found']}")
        print(f"Unchanged:        {summary['total_unchanged']}")
        print(f"Errors:           {summary['total_errors']}")
        if summary['offline_roots']:
            print(f"Offline Roots:    {', '.join(summary['offline_roots'])}")

    elif args.command == "watch":
        crawler = MultiRootCrawler()
        res = crawler.start_polling_observer()
        print(f"PollingObserver started. Watched roots: {res.get('watched_roots')}")
        print("Press Ctrl+C to stop.")
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            crawler.stop_polling_observer()
            print("\nStopped.")

    elif args.command == "stats":
        repo = DocumentRepository()
        stats = repo.get_stats()
        print("\n--- RepoScroller Ledger Stats ---")
        print(f"Total Unique Documents: {stats['total_unique_documents']}")
        print(f"Physical File Locations: {stats['total_physical_locations']}")
        print(f"Deduplicated Savings:    {stats['duplicates_deduplicated']} copies")
        print(f"Version Links:           {stats['version_links_count']}")
        print("\nLifecycle Breakdown:")
        for k, v in stats['lifecycle_breakdown'].items():
            print(f"  - {k}: {v}")
        print("\nStorage Breakdown:")
        for k, v in stats['storage_root_breakdown'].items():
            print(f"  - {k}: {v}")

    elif args.command == "check":
        target = Path(args.file)
        if not target.exists():
            print(f"Error: File '{args.file}' does not exist.")
            sys.exit(1)
        agent = DuplicateResolverAgent()
        res = agent.interrogate(file_path=str(target), query=target.name)
        print(f"\nStatus: {res['status_category']}")
        print(f"\n{res['answer']}")
        print(f"\nRecommendation: {res['recommendation']}")

    elif args.command == "interrogate":
        from backend.ai.telemetry import workload_telemetry
        if args.node or args.model:
            workload_telemetry.switch_chat_routing(node=args.node or workload_telemetry.chat_active_node, model=args.model)
        agent = DuplicateResolverAgent()
        res = agent.interrogate(query=args.query)
        print(f"\n[Node: {workload_telemetry.chat_active_node.upper()} | Model: {workload_telemetry.get_active_chat_model()} | URL: {workload_telemetry.get_active_chat_url()}]")
        print(f"Status: {res['status_category']}")
        print(f"\n{res['answer']}")
        print(f"\nRecommendation: {res['recommendation']}")

    elif args.command == "rag":
        from backend.agents.graph_rag import create_graph_rag_workflow
        print(f"Executing GraphRAG LangGraph Pipeline for: '{args.query}'...\n")
        workflow = create_graph_rag_workflow()
        res = workflow.invoke({
            "raw_query": args.query,
            "chat_history": [],
            "target_sha256": args.sha
        })
        print(f"Intent: {res.get('intent', 'UNKNOWN')} | Grounded: {res.get('is_grounded', False)}")
        print(f"\n{res.get('answer')}\n")
        sources = res.get("sources", [])
        if sources:
            print("Grounded Sources:")
            for s in sources[:5]:
                print(f"  - {s.get('canonical_filename')} ({s.get('doc_date', 'No date')})")
        if res.get("recommendation"):
            print(f"\nRecommendation: {res.get('recommendation')}")

    elif args.command == "sidecar":
        from backend.ai.sidecar_worker import KnowledgeBaseSidecarWorker
        worker = KnowledgeBaseSidecarWorker()
        if args.batch:
            print(f"Running Knowledge Base Sidecar batch (limit: {args.limit})...")
            res = worker.process_pending_batch(limit=args.limit)
            print(f"Processed: {res['processed_count']} documents.")
            for r in res.get("results", []):
                print(f"  - [{r['status']}] {r.get('canonical_filename', r['sha256'])} ({r.get('chunks_count', 0)} chunks)")
        else:
            print(f"Starting Knowledge Base Sidecar daemon loop (poll interval: {args.poll_interval}s)...")
            try:
                worker.run_worker_loop(poll_interval=args.poll_interval)
            except KeyboardInterrupt:
                print("\nSidecar worker stopped.")

    elif args.command == "reindex-banking":
        from backend.ledger.reindex_banking_entities import reindex_banking_entities
        reindex_banking_entities()

    elif args.command == "reindex-career":
        from backend.ledger.reindex_career_documents import reindex_career_documents
        reindex_career_documents()

    elif args.command == "backfill-obligations":
        from backend.ledger.backfill_obligations import run_obligations_backfill
        run_obligations_backfill()

    elif args.command == "embed-test":
        import time
        from backend.ai.embeddings import EmbeddingAdapter
        print(f"Testing RepoScroller Embedding Pipeline with sample: '{args.text}'...")
        adapter = EmbeddingAdapter()
        t0 = time.time()
        vec = adapter.embed_text(args.text)
        elapsed = (time.time() - t0) * 1000
        print(f"\nEmbedding Result:")
        print(f"  - Dimension: {len(vec)}d (Expected: {adapter.dimension}d)")
        print(f"  - Latency:   {elapsed:.1f}ms")
        print(f"  - Vector sample: {vec[:4]}")
        if len(vec) == adapter.dimension and any(v != 0.0 for v in vec):
            print("\n[OK] Embedding engine is fully operational!")
        else:
            print("\n[WARN] Embedding returned zero or dimension mismatch vector.")

    else:
        parser.print_help()



if __name__ == "__main__":
    main()
