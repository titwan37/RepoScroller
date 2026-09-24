"""Crawler management and manual scan trigger endpoints."""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel
from reposcroller.config import settings
from reposcroller.core.crawler import MultiRootCrawler

router = APIRouter(prefix="/crawler", tags=["Crawler"])

# Shared global crawler instance for lifecycle management
_crawler_instance: Optional[MultiRootCrawler] = None


def get_crawler() -> MultiRootCrawler:
    global _crawler_instance
    if _crawler_instance is None:
        _crawler_instance = MultiRootCrawler()
    return _crawler_instance


class ScanRequest(BaseModel):
    storage_roots: Optional[List[str]] = None
    force_reprocess: bool = False
    order: Optional[str] = "antichronological"
    workers: Optional[int] = None


@router.get("/status")
def get_crawler_status() -> Dict[str, Any]:
    """Inspect accessibility of storage roots and observer status."""
    crawler = get_crawler()
    roots_status = []
    for r in crawler.storage_roots:
        roots_status.append({
            "root": r,
            "accessible": crawler.is_root_accessible(r),
        })

    is_watching = crawler.observer is not None and crawler.observer.is_alive()
    return {
        "polling_observer_running": is_watching,
        "poll_interval_seconds": settings.POLL_INTERVAL_SECONDS,
        "watched_roots": list(crawler.active_watches.keys()),
        "configured_roots": roots_status,
    }


@router.post("/scan")
def trigger_batch_scan(req: ScanRequest) -> Dict[str, Any]:
    """Execute parallel batch crawl across storage roots."""
    crawler = MultiRootCrawler(
        storage_roots=req.storage_roots,
        max_workers=req.workers
    ) if req.storage_roots else get_crawler()
    summary = crawler.scan_all_roots(
        force_reprocess=req.force_reprocess,
        order=req.order,
        max_workers=req.workers
    )
    return summary


@router.post("/watch/start")
def start_watcher() -> Dict[str, Any]:
    """Start continuous PollingObserver across accessible mounts."""
    crawler = get_crawler()
    return crawler.start_polling_observer()


@router.post("/watch/stop")
def stop_watcher() -> Dict[str, Any]:
    """Stop continuous PollingObserver."""
    crawler = get_crawler()
    return crawler.stop_polling_observer()
