# RepoScroller

> **Modular Multi-Tier Document Ingestion & Procedural Intelligence Engine with ALCOA+ Integrity**

RepoScroller is a distributed document store, deduplication, and interrogation engine designed to index and maintain document treasures across **Synology NAS SMB mounts** and **multiple Google Drive mount points** without duplication or context loss.

---

## 🏛️ ALCOA+ Principles

- **Attributable:** Every document is tracked via streaming SHA-256 content hashes, audit logs, and discovery sources.
- **Legible:** High-fidelity text and structural extraction (PDF, DOCX, TXT, MD, EML) with SQLite FTS5 (BM25 keyword search).
- **Contemporaneous:** Exact file modification times (`mtime`), discovery timestamps, and real-time `watchdog.PollingObserver` sync.
- **Original:** Content-addressable storage (bit-for-bit exact copy detection across storage roots).
- **Accurate & Complete:** 64-bit Locality-Sensitive Hashing (SimHash) with Hamming distance near-duplicate detection, coupled with a heuristic `MaturityScore` model (evaluating completeness, digital signatures, stamps, dates, and naming conventions).

---

## 🏗️ Architecture

```
                 Distributed Storage Mounts
    ┌────────────────────────────────────────────────────────┐
    │  \\SyNAS\xcloud\docs  │  \\SyNAS\CloudSpace\LexSpace   │
    │  \\SyNAS\xcloud\LawSuiteRAG  │  H:\, L:\, G:\ Drives   │
    └───────────────────────────┬────────────────────────────┘
                                │
                                ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ Layer 1: Ingestion, Content Addressability & Registry        │
  │ • SMB/GDrive Polling Crawler (watchdog / PollingObserver)    │
  │ • SHA-256 Hashing, File Size, MTime & Near-Dup SimHash       │
  │ • SQLite WAL Registry (document_ledger & version_chains)     │
  └─────────────────────────────┬────────────────────────────────┘
                                │
                                ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ Layer 2: Document Processing & Heuristic Classification     │
  │ • Text Extraction: PyMuPDF (fitz) + metadata extraction      │
  │ • Maturity Classifier (Draft vs. Final, Merged, Truncated)   │
  └─────────────────────────────┬────────────────────────────────┘
                                │
                                ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ Layer 3: Knowledge, Lineage & Dual Hashing Indexing          │
  │ • Bit Identity: SHA-256                                      │
  │ • Sparse Lexical: SQLite FTS5 (BM25 keyword search)          │
  │ • Relational Lineage: version_chains (supersedes, derived)   │
  └─────────────────────────────┬────────────────────────────────┘
                                │
                                ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ Layer 4: Chatbot & Interrogation Gateway                     │
  │ • LangGraph StateGraph Interrogation Agent                   │
  │ • FastAPI SSE endpoint + Pre-Flight Duplicate Inspection     │
  │ • Natural Language Interrogation ("Is copy available?")      │
  └──────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Installation

```powershell
uv venv
uv pip install -e .
```

### 2. Run Tests

```powershell
uv run pytest
```

### 3. Run Batch Scan

```powershell
python -m reposcroller.main scan
```

### 4. Start Real-time Watcher

```powershell
python -m reposcroller.main watch
```

### 5. Start API Server

```powershell
python -m reposcroller.main serve --port 8090
```

Browse interactive OpenAPI docs at `http://127.0.0.1:8090/docs`.

### 6. Pre-flight Duplicate Inspection

Check if a document exists before writing it to a folder:

```powershell
python -m reposcroller.main check "path/to/document.pdf"
```

### 7. Interrogate with the Chatbot

```powershell
python -m reposcroller.main interrogate "Do we have the 2024 Kantonsgericht decision?"
```

---

Here is how to **initiate and use** RepoScroller right now?

---

### How to Initiate & Use RepoScroller

#### 1. Configure Your Real Storage Mounts

Copy the template configuration to `.env`:

```powershell
cp .env.example .env
```

Edit `.env` to define your target folders (NAS shares and Google Drive mounts), for example:

```ini
STORAGE_ROOTS=["\\\\SyNAS\\xcloud\\docs", "\\\\SyNAS\\CloudSpace\\LexSpace", "H:\\My Drive", "L:\\My Drive", "G:\\My Drive"]
```

*(Note: If any share is currently offline, RepoScroller detects it gracefully and skips it without crashing).*

---

#### 2. Run the Initial Ingestion Scan

To perform a fast initial batch crawl (which calculates SHA-256, SimHash, text extraction, and records metadata in the SQLite WAL ledger):

```powershell
# Scan all accessible configured roots:
uv run python -m reposcroller.main scan

# Or scan a single specific folder:
uv run python -m reposcroller.main scan --root "C:\Dev\RepoScroller\docs"
```

---

#### 3. View Ledger Statistics & Deduplication Savings

Check how many unique documents, duplicate physical locations, and version relationships have been cataloged:

```powershell
uv run python -m reposcroller.main stats
```

---

#### 4. Run Pre-Flight Duplicate Inspection (CLI)

Before uploading or saving a document to any folder, check whether an exact copy or prior draft already exists:

```powershell
uv run python -m reposcroller.main check "C:\Dev\RepoScroller\docs\repoScroller-POC.md"
```

---

#### 5. Launch the Web UI Dashboard & REST API

Start the server:

```powershell
uv run python -m reposcroller.main serve --port 8090
```

Open your browser to:

- **Web UI Dashboard:** [http://127.0.0.1:8090/](http://127.0.0.1:8090/) – interactive single-page dashboard with drag-and-drop duplicate dropzone, live mounts status, ledger browser, and streaming interrogation chatbot.
- **OpenAPI Swagger Explorer:** [http://127.0.0.1:8090/docs](http://127.0.0.1:8090/docs) – interactive API explorer.

---

#### 6. Start the Continuous Background Watcher

To continuously watch your folders for newly created, modified, or deleted files using `PollingObserver` (robust over SMB and virtual drives):

```powershell
uv run python -m reposcroller.main watch
```

---

Viewed crawler.py:65-135
Edited crawler.py
Edited main.py
Ran command: `uv run python -m reposcroller.main scan --root "c:\Dev\RepoScroller\docs"`

I have initiated the scan with live checkpointing and progress output to demonstrate resumability. I will summarize how it works as soon as it completes.

Ran command: `uv run pytest`

I will confirm the test suite status and provide an explanation of the resumability architecture.

### Yes, RepoScroller is 100% Resumable by Design

You can interrupt a scan at any time (e.g. `Ctrl+C`, network disconnection, machine reboot), and restarting `scan` will resume immediately without re-doing work.

---

### How Resumability Works (ALCOA+ ACID Checkpointing)

1. **Immediate Per-File Commit (No In-Memory Staging):**
   - Every file is processed and committed immediately to the SQLite WAL database within its own ACID transaction.
   - Nothing is buffered in memory. If 4,500 files out of 10,000 have been scanned when interrupted, **all 4,500 files and their hashes/lineage are permanently saved**.

2. **Sub-Millisecond Fast Path (`mtime` + `file_size` Check):**
   - Before reading raw bytes, computing streaming SHA-256, extracting text, or running SimHash, RepoScroller queries `file_locations` for the file's path.
   - If the file's modification time (`mtime`) and `file_size` match what is already recorded in the ledger, it is marked **`[UNCHANGED]`** and skipped in microseconds.
   - This avoids saturating your network/SMB connection to `\\SyNAS\...` or Google Drive virtual mounts.

3. **Handles Network Drops & Missing Drives Gracefully:**
   - If a NAS share or GDrive mount drops during a scan, the crawler logs it and continues with the accessible paths. It **never** purges or deletes existing records when a drive goes temporarily offline.

---

### Live Checkpoint Output

We added real-time progress logging to the CLI. When scanning, you will see exactly what is being skipped versus what is new:

```powershell
PS C:\dev\RepoScroller> uv run python -m reposcroller.main scan --root "c:\Dev\RepoScroller\docs"
Starting batch crawl (fully resumable, commits to SQLite WAL on every file)...
 [NEW]         repoScroller-implementation_summary.md        (Total: 1 | New: 1 | Dupa: 0 | Cached: 0)
 [UNCHANGED]   repoScroller-POC.md                           (Total: 2 | New: 1 | Dupa: 0 | Cached: 1)
 [UNCHANGED]   repoScroller-TechnicalArchitecture.md         (Total: 3 | New: 1 | Dupa: 0 | Cached: 2)

--- Scan Summary ---
Total Scanned:    3
Ingested (New):   1
Duplicates Found: 0
Unchanged:        2
Errors:           0
```

- **Interrupt anytime:** Press `Ctrl+C` safely whenever you want to pause.
- **Resume anytime:** Run `uv run python -m reposcroller.main scan` to pick up right where it left off.
- **Force full re-read:** If you ever want to bypass the fast cache and re-verify every file byte-for-byte, add `--force`:

  ```powershell
  uv run python -m reposcroller.main scan --force
  ```

### 3. Usage

#### CLI Execution

By default, `scan` now runs with **6 concurrent worker threads** and **anti-chronological ordering** (newest files first):

```powershell
# Run with default 6 parallel threads (1 per repo entry)
uv run python -m reposcroller.main scan

# Explicitly override thread count if needed (e.g., 3 threads or 12 threads)
uv run python -m reposcroller.main scan --workers 6 --order antichronological
```

#### REST API & Web Dashboard

The `POST /api/v1/crawler/scan` endpoint accepts an optional `workers` parameter:

```json
POST /api/v1/crawler/scan
{
  "force_reprocess": false,
  "order": "antichronological",
  "workers": 6
}
```

The response returns summary metrics including `"parallel_workers": 6`, which displays directly in the UI dashboard toast notification.

---

### 4. Verification

- Added `test_parallel_multi_root_crawl` to [`tests/test_crawler.py`](file:///c:/Dev/RepoScroller/tests/test_crawler.py#L83-L100).
- Ran the full test suite (`uv run pytest`): **33 tests passed** with 100% green status.

### Multi-Service Orchestrator Launcher for RepoScroller

The launcher [`start_all.ps1`](file:///c:/Dev/RepoScroller/start_all.ps1) (and its double-clickable companion [`start_all.bat`](file:///c:/Dev/RepoScroller/start_all.bat)) has been created on the model of [`AuraBily/start_all.ps1`](file:///c:/Dev/AuraBily/start_all.ps1).

---

### 1. Launcher Architecture & Features

```
                                  [start_all.ps1]
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  [Pre-flight Probing]           [Multi-Console Mode]           [Browser Auto-Open]
  • uv environment check         • Windows Terminal (wt.exe)    • http://127.0.0.1:8090/
  • 6 Storage Roots probe          Multi-Tab layout (-w 0)        (FastAPI Dashboard)
    (\\SyNAS\..., H:\, L:\, G:\) • Fallback: Separate PS
  • Local Ollama check             windows if wt not installed
        │
        ├──────────────────────┬──────────────────────┬──────────────────────┐
        ▼                      ▼                      ▼                      ▼
  [Tab 1: Backend]      [Tab 2: Scanner]       [Tab 3: Watcher]      [Tab 4: Ollama]
  FastAPI Uvicorn       Parallel Crawl Pool    PollingObserver       Local LLM Server
  Port 8090             6 worker threads       SMB/GDrive continuous (if installed)
                        Antichronological      daemon
```

---

### 2. Available Options & Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `-UseWindowsTerminal` | `$true` | Opens services as named tabs inside a single **Windows Terminal** window (`wt.exe`). Falls back gracefully to individual PowerShell consoles if not installed. |
| `-Workers` | `6` | Number of concurrent threads in the parallel scanner pool (1 per storage root). |
| `-Order` | `"antichronological"` | Traversal scan order (`"antichronological"` for newest files first, `"chronological"`, or `"alphabetical"`). |
| `-Port` | `8090` | Web Dashboard and FastAPI server port. |
| `-StartScanner` | `$true` | Automatically starts the initial batch parallel crawl in its own console/tab. |
| `-StartWatcher` | `$true` | Automatically starts the continuous `PollingObserver` daemon for real-time change detection. |
| `-OpenBrowser` | `$true` | Automatically opens `http://127.0.0.1:8090/` in the default browser 2 seconds after initialization. |

---

### 3. Usage Examples

#### From PowerShell

```powershell
# Standard launch with all defaults (Windows Terminal tabs, 6 workers, browser auto-open)
.\start_all.ps1

# Custom port or override worker count
.\start_all.ps1 -Port 8095 -Workers 4

# Backend only (skip auto-scan and watcher)
.\start_all.ps1 -StartScanner:$false -StartWatcher:$false

# Run in separate independent console windows instead of Windows Terminal tabs
.\start_all.ps1 -UseWindowsTerminal:$false
```

#### From CMD or File Explorer

Double-click or run:

```cmd
start_all.bat
```

---

### 4. Startup Verification Run Output

```
================================================================
   RepoScroller Sovereign Studio - Orchestrateur de Services
================================================================
 Repertoire projet : C:\Dev\RepoScroller
 Mode execution    : Windows Terminal (Multi-Onglets)
 Pool scanner      : 6 threads en parallele (antichronological)

[DETECTE] Environnement uv Python disponible

Sondage des 6 referentiels de stockage (SMB & Google Drive) :
  [CONNECTE]  [OK] \\SyNAS\xcloud\docs
  [CONNECTE]  [OK] \\SyNAS\xcloud\LawSuiteRAG
  [CONNECTE]  [OK] \\SyNAS\CloudSpace\LexSpace
  [CONNECTE]  [OK] H:\My Drive
  [CONNECTE]  [OK] L:\My Drive
  [CONNECTE]  [OK] G:\My Drive
  -> 6 sur 6 referentiels en ligne et prets pour le pool.

[DETECTE] Ollama trouve localement pour l'inference LLM locale.
[Lancement] Initialisation de Windows Terminal Multi-Onglets...
[Navigateur] Ouverture du Dashboard RepoScroller (http://127.0.0.1:8090)...

================================================================
  Services RepoScroller initialises avec succes !
   1. Dashboard Web & API         : http://127.0.0.1:8090/
   2. Explorateur OpenAPI (docs)  : http://127.0.0.1:8090/docs
   3. Diagnostics & Telemetrie    : http://127.0.0.1:8090/api/v1/diagnostics/health
   4. Console Diagnostic Flottante: Integree au Dashboard Web
================================================================
```
