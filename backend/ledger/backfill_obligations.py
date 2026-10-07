"""In-DB Backfill and Enrichment Engine for reception_date, due_date, and Actionable Obligations.

Reuses existing database records, text snippets, and document chunks without re-indexing
or re-computing vector embeddings from scratch. Includes real-time progress monitoring.
"""

import time
import logging
import threading
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.config import settings
from backend.ai.analyzer import DocumentAnalyzer
from backend.ledger.repository import DocumentRepository

logger = logging.getLogger("backfill_obligations")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class ObligationsProgressTracker:
    """Thread-safe real-time telemetry tracker for in-DB backfill passes."""

    def __init__(self):
        self._lock = threading.RLock()
        self.status = "idle"  # idle, running, completed, error
        self.phase = "idle"   # idle, scanning, updating_ledger, cross_matching, completed
        self.total_documents = 0
        self.processed_documents = 0
        self.percent = 0.0
        self.reception_dates_updated = 0
        self.due_dates_updated = 0
        self.doc_dates_updated = 0
        self.action_items_created = 0
        self.action_items_struck_out = 0
        self.action_types = {"payment": 0, "signature": 0, "reply": 0, "other": 0}
        self.total_obligations = 0
        self.pending_obligations = 0
        self.overdue_obligations = 0
        self.completed_obligations = 0
        self.start_time: Optional[float] = None
        self.elapsed_seconds = 0.0
        self.docs_per_second = 0.0
        self.last_message = ""

    def start(self, total_docs: int):
        with self._lock:
            self.status = "running"
            self.phase = "scanning"
            self.total_documents = total_docs
            self.processed_documents = 0
            self.percent = 0.0
            self.reception_dates_updated = 0
            self.due_dates_updated = 0
            self.doc_dates_updated = 0
            self.action_items_created = 0
            self.action_items_struck_out = 0
            self.action_types = {"payment": 0, "signature": 0, "reply": 0, "other": 0}
            self.start_time = time.time()
            self.elapsed_seconds = 0.0
            self.docs_per_second = 0.0
            self.last_message = f"Starting scan of {total_docs:,} documents..."

    def update_progress(self, processed: int, msg: Optional[str] = None):
        with self._lock:
            self.processed_documents = processed
            if self.total_documents > 0:
                self.percent = round((processed / self.total_documents) * 100.0, 1)
            if self.start_time:
                self.elapsed_seconds = round(time.time() - self.start_time, 1)
                if self.elapsed_seconds > 0:
                    self.docs_per_second = round(processed / self.elapsed_seconds, 1)
            if msg:
                self.last_message = msg

    def finish(self, stats: Dict[str, Any]):
        with self._lock:
            self.status = "completed"
            self.phase = "completed"
            self.percent = 100.0
            self.processed_documents = self.total_documents
            if self.start_time:
                self.elapsed_seconds = round(time.time() - self.start_time, 2)
            self.reception_dates_updated = stats.get("reception_dates_updated", 0)
            self.due_dates_updated = stats.get("due_dates_updated", 0)
            self.doc_dates_updated = stats.get("doc_dates_updated", 0)
            self.action_items_created = stats.get("action_items_created", 0)
            self.action_items_struck_out = stats.get("action_items_struck_out", 0)
            self.action_types = stats.get("action_types", {})
            self.total_obligations = stats.get("total_obligations", 0)
            self.pending_obligations = stats.get("pending_obligations", 0)
            self.overdue_obligations = stats.get("overdue_obligations", 0)
            self.completed_obligations = stats.get("completed_obligations", 0)
            self.last_message = f"Completed in {self.elapsed_seconds}s. {self.action_items_created:,} obligations created."

    def fail(self, error: str):
        with self._lock:
            self.status = "error"
            self.phase = "error"
            self.last_message = f"Error: {error}"

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            now_elapsed = round(time.time() - self.start_time, 1) if (self.status == "running" and self.start_time) else self.elapsed_seconds
            return {
                "status": self.status,
                "phase": self.phase,
                "total_documents": self.total_documents,
                "processed_documents": self.processed_documents,
                "percent": self.percent,
                "elapsed_seconds": now_elapsed,
                "docs_per_second": self.docs_per_second,
                "last_message": self.last_message,
                "reception_dates_updated": self.reception_dates_updated,
                "due_dates_updated": self.due_dates_updated,
                "doc_dates_updated": self.doc_dates_updated,
                "action_items_created": self.action_items_created,
                "action_items_struck_out": self.action_items_struck_out,
                "action_types": self.action_types,
                "total_obligations": self.total_obligations,
                "pending_obligations": self.pending_obligations,
                "overdue_obligations": self.overdue_obligations,
                "completed_obligations": self.completed_obligations
            }


# Global singleton progress tracker
obligations_tracker = ObligationsProgressTracker()


def get_db_path() -> Path:
    return getattr(settings, "DB_PATH", Path(__file__).resolve().parent.parent / "data" / "reposcroller_ledger.db")


def run_obligations_backfill(db_path: Optional[Path] = None, verbose: bool = True) -> Dict[str, Any]:
    """
    Backfill reception_date, due_date, and action_items across all documents in the ledger.
    Leverages cached text snippets and document chunks to enrich the database in seconds.
    """
    if db_path is None:
        db_path = get_db_path()

    t0 = time.time()
    repo = DocumentRepository(db_path=db_path)
    repo._ensure_schema()
    analyzer = DocumentAnalyzer(provider="heuristic")

    conn = repo.conn
    cur = conn.cursor()

    stats = {
        "scanned_documents": 0,
        "reception_dates_updated": 0,
        "due_dates_updated": 0,
        "doc_dates_updated": 0,
        "action_items_created": 0,
        "action_items_struck_out": 0,
        "action_types": {"payment": 0, "signature": 0, "reply": 0, "other": 0},
        "overdue_obligations": 0,
        "pending_obligations": 0,
        "total_obligations": 0,
        "completed_obligations": 0,
    }

    try:
        # 1. Fetch all documents from the ledger with location mtime
        cur.execute("""
            SELECT dl.sha256_hash, dl.canonical_filename, dl.doc_type, dl.doc_date,
                   dl.reception_date, dl.due_date, dl.text_snippet,
                   MAX(fl.mtime) as mtime,
                   COALESCE(fl.relative_path, '') as relative_path,
                   COALESCE(fl.storage_root, '') as storage_root
            FROM document_ledger dl
            LEFT JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash
            GROUP BY dl.sha256_hash;
        """)
        documents = cur.fetchall()
        total_docs = len(documents)
        stats["scanned_documents"] = total_docs
        obligations_tracker.start(total_docs)

        start_msg = f"Starting Obligations & Date Backfill on '{db_path.name}' ({total_docs:,} documents)"
        if verbose:
            logger.info(f"=== {start_msg} ===")

        # Pre-fetch existing action item fingerprints to avoid duplicates
        cur.execute("SELECT sha256_hash, action_type, due_date, amount FROM action_items")
        existing_actions = set()
        for row in cur.fetchall():
            key = (row["sha256_hash"], row["action_type"], str(row["due_date"]), str(row["amount"]))
            existing_actions.add(key)

        # 2. Iterate documents and run deterministic enrichment
        updates_to_ledger = []
        doc_records_for_crossmatch = []
        last_log_time = time.time()

        for idx, doc in enumerate(documents, start=1):
            sha = doc["sha256_hash"]
            fname = doc["canonical_filename"] or "document.pdf"
            doc_type = doc["doc_type"] or "other"
            doc_date = doc["doc_date"]
            rec_date = doc["reception_date"]
            due_date = doc["due_date"]
            snippet = doc["text_snippet"] or ""
            mtime = doc["mtime"]
            rel_path = doc["relative_path"]
            storage_root = doc["storage_root"]

            # Use snippet directly for high throughput (fallback to chunk if empty)
            combined_text = snippet
            if not combined_text:
                cur.execute("""
                    SELECT chunk_text FROM document_chunks
                    WHERE sha256_hash = ?
                    ORDER BY chunk_index ASC
                    LIMIT 2;
                """, (sha,))
                chunk_rows = cur.fetchall()
                if chunk_rows:
                    combined_text = "\n".join(r["chunk_text"] for r in chunk_rows if r["chunk_text"])

            metadata = {
                "path": rel_path,
                "relative_path": rel_path,
                "storage_root": storage_root,
                "mtime": mtime
            }

            # Heuristic extraction
            analysis = analyzer._heuristic_analyze(
                text=combined_text,
                filename=fname,
                metadata=metadata
            )

            new_doc_date = doc_date or analysis.governing_date
            new_rec_date = rec_date or analysis.reception_date
            new_due_date = due_date or analysis.due_date

            needs_ledger_update = False
            if new_doc_date and new_doc_date != doc_date:
                needs_ledger_update = True
                stats["doc_dates_updated"] += 1
            if new_rec_date and new_rec_date != rec_date:
                needs_ledger_update = True
                stats["reception_dates_updated"] += 1
            if new_due_date and new_due_date != due_date:
                needs_ledger_update = True
                stats["due_dates_updated"] += 1

            if needs_ledger_update:
                updates_to_ledger.append((new_doc_date, new_rec_date, new_due_date, sha))

            # Action items / Obligations
            theme_node_id = f"theme_{doc_type}" if doc_type else None
            for item in (analysis.action_items or []):
                item_due = item.due_date or new_due_date
                item_amt = item.amount
                act_key = (sha, item.action_type, str(item_due), str(item_amt))

                if act_key not in existing_actions:
                    existing_actions.add(act_key)
                    try:
                        repo.create_action_item(
                            sha256_hash=sha,
                            description=item.description,
                            action_type=item.action_type,
                            theme_id=theme_node_id,
                            counterparty=item.counterparty,
                            amount=item.amount,
                            currency=item.currency or "CHF",
                            due_date=item_due,
                            status="pending"
                        )
                        stats["action_items_created"] += 1
                        a_type = item.action_type if item.action_type in stats["action_types"] else "other"
                        stats["action_types"][a_type] = stats["action_types"].get(a_type, 0) + 1
                    except Exception as e_act:
                        logger.debug(f"Action item insert error {sha}: {e_act}")

            # Keep doc records for crossmatching
            doc_records_for_crossmatch.append({
                "record": {
                    "sha256_hash": sha,
                    "canonical_filename": fname,
                    "doc_type": doc_type,
                    "doc_date": new_doc_date,
                    "reception_date": new_rec_date,
                    "due_date": new_due_date,
                },
                "text": combined_text
            })

            # Real-time progress update every 1,000 documents or 2 seconds
            if idx % 1000 == 0 or (time.time() - last_log_time >= 2.0) or idx == total_docs:
                pct = round((idx / total_docs) * 100.0, 1)
                prog_msg = f"Progress: {idx:,} / {total_docs:,} docs ({pct}%) | {stats['action_items_created']:,} obligations found"
                obligations_tracker.update_progress(idx, prog_msg)
                if verbose and (idx % 2500 == 0 or idx == total_docs):
                    logger.info(f"  [Progress {pct}%] {idx:,}/{total_docs:,} documents scanned ({stats['action_items_created']} obligations)")
                last_log_time = time.time()

        # 3. Batch apply ledger updates
        if updates_to_ledger:
            obligations_tracker.phase = "updating_ledger"
            if verbose:
                logger.info(f"Applying {len(updates_to_ledger):,} document date updates to SQLite...")
            cur.executemany("""
                UPDATE document_ledger
                SET doc_date = COALESCE(?, doc_date),
                    reception_date = COALESCE(?, reception_date),
                    due_date = COALESCE(?, due_date)
                WHERE sha256_hash = ?;
            """, updates_to_ledger)
            conn.commit()

        # 4. Fast in-memory Cross-match and auto-strikeout
        obligations_tracker.phase = "cross_matching"
        if verbose:
            logger.info("Running ALCOA+ cross-matching and auto-strikeout fulfillment pass...")

        # Fetch all pending items once for fast in-memory matching
        cur.execute("""
            SELECT action_id, sha256_hash, theme_id, action_type, description, counterparty, amount, currency, due_date
            FROM action_items
            WHERE status = 'pending';
        """)
        pending_items = [dict(r) for r in cur.fetchall()]

        total_struck = 0
        if pending_items:
            for item_doc in doc_records_for_crossmatch:
                new_sha = item_doc["record"]["sha256_hash"]
                text_lower = (item_doc["text"] or "").lower()
                if not text_lower:
                    continue

                for p_item in list(pending_items):
                    if p_item["sha256_hash"] == new_sha:
                        continue
                    
                    act_id = p_item["action_id"]
                    orig_sha = p_item["sha256_hash"]
                    a_type = p_item["action_type"]
                    counterparty = (p_item["counterparty"] or "").strip()
                    amount = p_item["amount"]
                    curr = p_item["currency"] or "CHF"
                    desc = p_item["description"] or ""

                    matched = False
                    evidence = ""

                    # Rule 1: Payment fulfillment
                    if a_type == "payment" and amount is not None and amount > 0:
                        amt_str_full = f"{amount:.2f}"
                        amt_str_int = str(int(amount)) if amount == int(amount) else amt_str_full
                        has_amt = (amt_str_full in text_lower or amt_str_int in text_lower)
                        has_party = counterparty and (counterparty.lower() in text_lower)
                        is_pay_doc = any(k in text_lower for k in [
                            "zahlung", "überweisung", "virement", "paiement", "receipt", "quittung",
                            "gutschrift", "belastung", "debit", "credit", "auszug", "relevé", "paid"
                        ])
                        if has_amt and (has_party or is_pay_doc):
                            matched = True
                            evidence = f"Cross-matched payment: amount {amount} {curr}" + (f" with counterparty '{counterparty}'" if has_party else "")

                    # Rule 2: Signature fulfillment
                    elif a_type in ["signature", "sign"]:
                        is_signed_text = any(k in text_lower for k in [
                            "signé", "unterzeichnet", "unterschrieben", "executed", "countersigned", "duly signed"
                        ])
                        has_party = counterparty and (counterparty.lower() in text_lower)
                        if is_signed_text and (has_party or orig_sha[:8] in text_lower):
                            matched = True
                            evidence = f"Cross-matched signature fulfillment for '{counterparty or orig_sha[:12]}'"

                    if matched:
                        repo.resolve_action_item(
                            action_id=act_id,
                            status="completed",
                            fulfilled_by_sha256=new_sha,
                            fulfillment_evidence=evidence
                        )
                        pending_items.remove(p_item)
                        total_struck += 1

        stats["action_items_struck_out"] = total_struck

        # 5. Query final action item telemetry
        cur.execute("SELECT COUNT(*) FROM action_items")
        stats["total_obligations"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM action_items WHERE status = 'pending'")
        stats["pending_obligations"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM action_items WHERE status = 'pending' AND due_date IS NOT NULL AND due_date < date('now')")
        stats["overdue_obligations"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM action_items WHERE status = 'completed'")
        stats["completed_obligations"] = cur.fetchone()[0]

        elapsed = time.time() - t0
        stats["duration_seconds"] = round(elapsed, 2)
        obligations_tracker.finish(stats)

        completion_msg = f"Obligations backfill finished in {elapsed:.2f}s: {stats['total_obligations']:,} total obligations ({stats['pending_obligations']:,} pending, {stats['overdue_obligations']:,} overdue, {stats['completed_obligations']:,} auto-struck)."
        if verbose:
            logger.info(f"=== {completion_msg} ===")

        return stats

    except Exception as e:
        obligations_tracker.fail(str(e))
        logger.error(f"Obligations backfill error: {e}")
        raise


if __name__ == "__main__":
    run_obligations_backfill()
