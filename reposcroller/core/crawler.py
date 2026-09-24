"""Multi-root crawler supporting fast batch scans and watchdog PollingObserver for SMB/GDrive."""

import os
import logging
import threading
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from reposcroller.config import settings
from reposcroller.core.synchronizer import DocumentSynchronizer
from reposcroller.ledger.repository import DocumentRepository

logger = logging.getLogger("reposcroller.crawler")


class DocumentEventHandler(FileSystemEventHandler):
    """Handles real-time file system events using PollingObserver."""

    def __init__(self, synchronizer: DocumentSynchronizer, storage_root: str):
        super().__init__()
        self.synchronizer = synchronizer
        self.storage_root = storage_root

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle_file(Path(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle_file(Path(event.src_path))

    def _handle_file(self, file_path: Path) -> None:
        if file_path.suffix.lower() in settings.SUPPORTED_EXTENSIONS:
            try:
                res = self.synchronizer.process_file(file_path, self.storage_root)
                logger.info(f"Observer processed {file_path.name}: {res.get('status')}")
            except Exception as e:
                logger.error(f"Observer failed for {file_path}: {e}")


def _safe_mtime(p: Path) -> float:
    """Safely get modification time without throwing if file/dir has permission issues."""
    try:
        return p.stat().st_mtime
    except (OSError, PermissionError):
        return 0.0


class MultiRootCrawler:
    """Manages multi-root document discovery across SMB shares, Google Drives, and local paths."""

    def __init__(self,
                 storage_roots: Optional[List[str]] = None,
                 synchronizer: Optional[DocumentSynchronizer] = None,
                 max_workers: Optional[int] = None):
        self.storage_roots = storage_roots or settings.STORAGE_ROOTS
        self.synchronizer = synchronizer or DocumentSynchronizer()
        self.max_workers = max_workers or settings.SCAN_PARALLEL_WORKERS or len(self.storage_roots)
        self.observer: Optional[PollingObserver] = None
        self.active_watches: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stop_requested = threading.Event()

    def is_root_accessible(self, root_path: str) -> bool:
        """Verify whether an SMB share, cloud mount, or local directory is online and reachable."""
        try:
            return os.path.exists(root_path) and os.path.isdir(root_path)
        except (OSError, PermissionError):
            return False

    def stop_crawl(self) -> None:
        """Signal all active worker threads to halt crawl."""
        self._stop_requested.set()

    def _get_thread_synchronizer(self) -> DocumentSynchronizer:
        """Provide a thread-safe DocumentSynchronizer instance for a crawler thread."""
        if self.synchronizer and not self.synchronizer.repo._owns_conn:
            return self.synchronizer
        db_path = self.synchronizer.repo.db_path if self.synchronizer and hasattr(self.synchronizer.repo, "db_path") else None
        repo = DocumentRepository(db_path=db_path) if db_path else DocumentRepository()
        return DocumentSynchronizer(repository=repo)

    def scan_all_roots(self,
                       force_reprocess: bool = False,
                       progress_callback=None,
                       order: Optional[str] = None,
                       max_workers: Optional[int] = None) -> Dict[str, Any]:
        """Perform a parallel batch crawl across all configured roots using a worker thread pool.
        
        Spawns up to `max_workers` concurrent scanner threads (1 per storage root),
        allowing Synology SMB shares and Google Drive mounts to be discovered simultaneously.
        """
        traversal_order = order or settings.SCAN_ORDER
        workers_count = max_workers if max_workers is not None else self.max_workers
        self._stop_requested.clear()

        summary: Dict[str, Any] = {
            "total_scanned": 0,
            "total_ingested": 0,
            "total_duplicates_found": 0,
            "total_unchanged": 0,
            "total_errors": 0,
            "offline_roots": [],
            "processed_roots": [],
            "details": [],
            "parallel_workers": 1,
        }

        accessible_roots = []
        for root in self.storage_roots:
            if not self.is_root_accessible(root):
                summary["offline_roots"].append(root)
                logger.warning(f"Storage root inaccessible or offline: {root}")
            else:
                accessible_roots.append(root)
                summary["processed_roots"].append(root)

        if not accessible_roots:
            return summary

        actual_workers = max(1, min(workers_count, len(accessible_roots)))
        summary["parallel_workers"] = actual_workers

        lock = threading.Lock()

        def _thread_progress(filepath: Path, status: str, stats: dict):
            if progress_callback:
                with lock:
                    progress_callback(filepath, status, stats)

        def _worker_scan(root_path: str) -> Dict[str, Any]:
            thread_sync = self._get_thread_synchronizer()
            try:
                root_stats = self.scan_root(
                    root_path,
                    force_reprocess=force_reprocess,
                    progress_callback=_thread_progress,
                    order=traversal_order,
                    synchronizer=thread_sync
                )
                return {"root": root_path, "stats": root_stats}
            finally:
                if thread_sync != self.synchronizer:
                    thread_sync.repo.close()

        if actual_workers == 1:
            for root in accessible_roots:
                if self._stop_requested.is_set():
                    break
                res = _worker_scan(root)
                root_stats = res["stats"]
                summary["total_scanned"] += root_stats["scanned"]
                summary["total_ingested"] += root_stats["ingested"]
                summary["total_duplicates_found"] += root_stats["duplicates"]
                summary["total_unchanged"] += root_stats["unchanged"]
                summary["total_errors"] += root_stats["errors"]
                summary["details"].append(res)
        else:
            logger.info(f"Starting parallel crawl with {actual_workers} workers for {len(accessible_roots)} roots")
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=actual_workers,
                thread_name_prefix="RepoCrawler"
            ) as executor:
                future_to_root = {
                    executor.submit(_worker_scan, root): root
                    for root in accessible_roots
                }
                for future in concurrent.futures.as_completed(future_to_root):
                    root = future_to_root[future]
                    try:
                        res = future.result()
                        root_stats = res["stats"]
                        with lock:
                            summary["total_scanned"] += root_stats["scanned"]
                            summary["total_ingested"] += root_stats["ingested"]
                            summary["total_duplicates_found"] += root_stats["duplicates"]
                            summary["total_unchanged"] += root_stats["unchanged"]
                            summary["total_errors"] += root_stats["errors"]
                            summary["details"].append(res)
                    except Exception as e:
                        logger.error(f"Root scan thread failed for {root}: {e}")
                        with lock:
                            summary["total_errors"] += 1
                            summary["details"].append({"root": root, "error": str(e)})

        return summary

    def scan_root(self,
                  root_path: str,
                  force_reprocess: bool = False,
                  progress_callback=None,
                  order: str = "antichronological",
                  synchronizer: Optional[DocumentSynchronizer] = None) -> Dict[str, int]:
        """Recursively crawl a single directory root in anti-chronological order (newest first)."""
        stats = {"scanned": 0, "ingested": 0, "duplicates": 0, "unchanged": 0, "errors": 0}
        root_p = Path(root_path)
        sync = synchronizer or self.synchronizer

        for dirpath, dirnames, filenames in os.walk(root_p):
            if self._stop_requested.is_set():
                break

            # 1. Prune ignored directory trees
            dirnames[:] = [
                d for d in dirnames
                if d not in settings.IGNORE_DIRS and not d.startswith(".")
            ]

            # 2. Sort subdirectories: antichronological visits newest folders first
            if order == "antichronological":
                dirnames.sort(key=lambda d: _safe_mtime(Path(dirpath) / d), reverse=True)
            elif order == "chronological":
                dirnames.sort(key=lambda d: _safe_mtime(Path(dirpath) / d))
            elif order == "alphabetical":
                dirnames.sort()

            # 3. Filter supported document files
            candidate_files = [
                fname for fname in filenames
                if Path(fname).suffix.lower() in settings.SUPPORTED_EXTENSIONS
            ]

            # 4. Sort files inside this folder: newest files scanned first
            if order == "antichronological":
                candidate_files.sort(key=lambda f: _safe_mtime(Path(dirpath) / f), reverse=True)
            elif order == "chronological":
                candidate_files.sort(key=lambda f: _safe_mtime(Path(dirpath) / f))
            elif order == "alphabetical":
                candidate_files.sort()

            for fname in candidate_files:
                if self._stop_requested.is_set():
                    break

                stats["scanned"] += 1
                full_path = Path(dirpath) / fname

                try:
                    res = sync.process_file(
                        file_path=full_path,
                        storage_root=root_path,
                        force_reprocess=force_reprocess
                    )
                    status = res.get("status")
                    if status == "ingested":
                        stats["ingested"] += 1
                    elif status == "exact_duplicate_recorded":
                        stats["duplicates"] += 1
                    elif status == "unchanged":
                        stats["unchanged"] += 1
                    else:
                        stats["errors"] += 1

                    if progress_callback:
                        progress_callback(full_path, status, stats)
                except Exception as e:
                    logger.error(f"Error crawling {full_path}: {e}")
                    stats["errors"] += 1
                    if progress_callback:
                        progress_callback(full_path, "error", stats)

        return stats

    def start_polling_observer(self) -> Dict[str, Any]:
        """Start watchdog.observers.polling.PollingObserver over all reachable roots."""
        if self.observer and self.observer.is_alive():
            return {"status": "already_running", "watched_roots": list(self.active_watches.keys())}

        self.observer = PollingObserver(timeout=settings.POLL_INTERVAL_SECONDS)
        watched = []

        for root in self.storage_roots:
            if self.is_root_accessible(root):
                handler = DocumentEventHandler(self.synchronizer, root)
                watch = self.observer.schedule(handler, root, recursive=True)
                self.active_watches[root] = watch
                watched.append(root)

        self.observer.start()
        return {"status": "started", "watched_roots": watched}

    def stop_polling_observer(self) -> Dict[str, str]:
        """Stop running PollingObserver."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            self.active_watches.clear()
            return {"status": "stopped"}
        return {"status": "not_running"}
