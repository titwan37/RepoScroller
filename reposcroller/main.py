"""CLI Entrypoint for RepoScroller command center."""

import argparse
import sys
import uvicorn
from pathlib import Path
from reposcroller.config import settings
from reposcroller.ledger.db import init_db
from reposcroller.ledger.repository import DocumentRepository
from reposcroller.core.crawler import MultiRootCrawler
from reposcroller.agents.duplicate_agent import DuplicateResolverAgent


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

    # Command: sidecar
    sidecar_p = subparsers.add_parser("sidecar", help="Run the Knowledge Base Sidecar Worker to chunk and embed documents")
    sidecar_p.add_argument("--batch", action="store_true", help="Process pending items once and exit")
    sidecar_p.add_argument("--limit", type=int, default=10, help="Number of documents to process in batch")
    sidecar_p.add_argument("--poll-interval", type=float, default=3.0, help="Poll interval in seconds for continuous mode")

    args = parser.parse_args()


    # Ensure DB is initialized
    init_db()

    if args.command == "serve":
        print(f"Starting RepoScroller API at http://{args.host}:{args.port}...")
        uvicorn.run("reposcroller.api.app:app", host=args.host, port=args.port, reload=args.reload)

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
        agent = DuplicateResolverAgent()
        res = agent.interrogate(query=args.query)
        print(f"\nStatus: {res['status_category']}")
        print(f"\n{res['answer']}")
        print(f"\nRecommendation: {res['recommendation']}")

    elif args.command == "sidecar":
        from reposcroller.ai.sidecar_worker import KnowledgeBaseSidecarWorker
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

    else:
        parser.print_help()



if __name__ == "__main__":
    main()
