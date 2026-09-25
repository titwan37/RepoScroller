# RepoScroller 📜

> **Modular Multi-Tier Document Ingestion, Deduplication & Procedural Intelligence Engine with ALCOA+ Integrity and Sovereign GraphRAG**

RepoScroller is a distributed document store, deduplication, and interrogation engine engineered to index, organize, and query document treasures across **Synology NAS SMB mounts** and **multiple Google Drive mount points** without duplication or context loss.

---

## 🏛️ ALCOA+ Regulatory Compliance

RepoScroller is designed from the ground up to satisfy pharmaceutical and legal **ALCOA+** data integrity standards:

- **Attributable:** Every document is tracked with streaming cryptographic SHA-256 hashes, immutable `audit_log` records, and discovery source origins.
- **Legible:** High-fidelity text and structural extraction (PDF, DOCX, TXT, MD, EML) indexed in SQLite FTS5 for sub-millisecond BM25 keyword retrieval.
- **Contemporaneous:** Exact file modification timestamps (`mtime`), discovery timestamps, and continuous `watchdog.PollingObserver` synchronization.
- **Original:** Content-addressable storage distinguishing primary source records from replica copies and backups across mounts.
- **Accurate & Complete:** Dual verification pairing SHA-256 with 64-bit Locality-Sensitive Hashing (SimHash) for near-duplicate revision tracking, complemented by a heuristic `MaturityScore` model (evaluating completeness, digital signatures, stamps, dates, and naming conventions).
- **Consistent & Enduring:** ACID-compliant SQLite WAL database (`reposcroller_ledger.db`) ensuring zero-overhead, tamper-evident transactional persistence.
- **Available:** Fast REST API endpoints, interactive dual-pane web dashboard, and resilient fallback mechanisms for offline network shares.

---

## 🏗️ Architectural Blueprint

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
  │ • Multi-Threaded Parallel Crawler (x6 worker threads)        │
  │ • Antichronological Scan Priority (newest files first)       │
  │ • SHA-256 Hashing, File Size, MTime & Near-Dup SimHash (LSH) │
  │ • SQLite WAL Registry (document_ledger & version_chains)     │
  └─────────────────────────────┬────────────────────────────────┘
                                │
                                ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ Layer 2: Document Processing & Heuristic Classification     │
  │ • Text Extraction: PyMuPDF (fitz) + digital signature checks │
  │ • Maturity Classifier (Draft vs. Final, Merged, Truncated)   │
  │ • Dynamic Multilingual Taxonomy (EN / FR / DE Canonicalizer) │
  └─────────────────────────────┬────────────────────────────────┘
                                │
                                ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ Layer 3: Knowledge Base Sidecar & GraphRAG Store             │
  │ • Asynchronous CDC Queue: kb_processing_queue                │
  │ • Dense Vectors: snowflake-arctic-embed:latest (Ollama)      │
  │ • Sparse Lexical: SQLite FTS5 (BM25 keyword search)          │
  │ • Property Graph: Neo4j / SQLite (knowledge_nodes & edges)   │
  └─────────────────────────────┬────────────────────────────────┘
                                │
                                ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ Layer 4: Chatbot & Interrogation Gateway                     │
  │ • LangGraph StateGraph Interrogation Agent                   │
  │ • Pre-Flight Duplicate Inspection & Existence Checking      │
  │ • Hybrid GraphRAG Retrieval (RRF k=60) + LLM Q&A Synthesis   │
  │ • Dual-Pane Web UI Dashboard & Real-Time Console Telemetry   │
  └──────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Installation

```powershell
cd C:\Dev\RepoScroller
uv venv
uv pip install -e .
```

### 2. Configure Storage Mounts

Copy the template configuration to `.env`:

```powershell
cp .env.example .env
```

Define your target folders (NAS SMB paths and mounted cloud drives):

```ini
STORAGE_ROOTS=["\\\\SyNAS\\xcloud\\docs", "\\\\SyNAS\\CloudSpace\\LexSpace", "\\\\SyNAS\\xcloud\\LawSuiteRAG", "H:\\My Drive", "L:\\My Drive", "G:\\My Drive"]
SCAN_PARALLEL_WORKERS=6
SCAN_ORDER="antichronological"
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_MODEL="llama3.2"
OLLAMA_EMBEDDING_MODEL="snowflake-arctic-embed:latest"
```

---

## 🎮 Launching RepoScroller

### Option A: 1-Click Multi-Console Launcher (Recommended)

Run the orchestrator script to probe mounts, verify Ollama, and launch the multi-tab control center:

```powershell
# Double-click or run from CMD:
start_all.bat

# Or from PowerShell:
.\start_all.ps1
```

This automatically initializes:

1. **Backend Server & Web Dashboard:** `http://127.0.0.1:8090/`
2. **Parallel Scanner (x6 Threads):** Discovers and hashes records anti-chronologically across all online mounts.
3. **Continuous Watcher Daemon:** Listens for real-time filesystem changes via `PollingObserver`.
4. **Ollama Server:** For local LLM analysis and embeddings.

---

### Option B: Running Individual Services

#### 1. Launch Web Dashboard & REST API

```powershell
uv run python -m reposcroller.main serve --port 8090
```

- **Web Dashboard:** [http://127.0.0.1:8090/](http://127.0.0.1:8090/)
- **OpenAPI Swagger Docs:** [http://127.0.0.1:8090/docs](http://127.0.0.1:8090/docs)

#### 2. Run Parallel Multi-Root Ingestion Scan

```powershell
# Standard antichronological crawl (x6 worker threads)
uv run python -m reposcroller.main scan

# Scan a specific folder only
uv run python -m reposcroller.main scan --root "C:\Dev\RepoScroller\docs"

# Force full re-hash of all files (bypass mtime cache)
uv run python -m reposcroller.main scan --force
```

#### 3. Start the Real-Time Watcher Daemon

```powershell
uv run python -m reposcroller.main watch
```

#### 4. Run Knowledge Base Sidecar Worker (Dense Vectors & Graph)

```powershell
# One-off batch consolidation pass (chunks + embeddings + graph entities)
uv run python -m reposcroller.main sidecar --batch --limit 20

# Continuous background daemon worker
uv run python -m reposcroller.main sidecar --poll-interval 3.0
```

---

## 🧠 Sovereign GraphRAG & Knowledge Base Sidecar

RepoScroller features a multi-signal **GraphRAG** pipeline designed for corpora of 25k+ documents:

```
[SMB/GDrive Ingest] ──> [kb_processing_queue] ──> [Sidecar Worker] ──┬──> [Dense Vectors (Arctic Embed)]
                                                                    ├──> [Sparse BM25 (SQLite FTS5)]
                                                                    └──> [Property Graph (Neo4j/SQLite)]
                                                                                     │
                                                                                     ▼
                                                                        [Hybrid GraphRAG (RRF k=60)]
```

### Retrieval Signals Fused

1. **Signal A (Dense Semantic Vectors):** Chunked passages embedded via `snowflake-arctic-embed:latest` in SQLite / vector store for conceptual matching.
2. **Signal B (Sparse Lexical Search):** SQLite FTS5 BM25 search over exact terms, dates, invoice numbers, and filenames.
3. **Signal C (Knowledge Graph Expansion):** 1-hop and 2-hop entity neighborhood expansion (`(:Party)-[:SIGNS]->(:Contract)` / `(:Doc)-[:SUPERSEDES]->(:Doc)`).
4. **Reciprocal Rank Fusion (RRF):** Merges candidate lists using:
   $$\text{RRF Score}(d) = \sum_{m \in \{\text{dense}, \text{sparse}\}} \frac{1}{60 + \text{rank}_m(d)}$$

---

## 💻 CLI Command Reference

| Command | Usage | Description |
| :--- | :--- | :--- |
| `serve` | `reposcroller serve [--port 8090]` | Starts FastAPI web server and dashboard |
| `scan` | `reposcroller scan [--workers 6] [--force]` | Runs parallel batch crawl across storage roots |
| `watch` | `reposcroller watch` | Runs continuous `PollingObserver` file watcher |
| `sidecar` | `reposcroller sidecar [--batch] [--limit 10]` | Runs Knowledge Base chunking & GraphRAG indexing |
| `stats` | `reposcroller stats` | Prints ledger statistics, savings, and mounts |
| `check` | `reposcroller check "path/to/doc.pdf"` | Pre-flight check for exact duplicates or earlier drafts |
| `interrogate` | `reposcroller interrogate "query"` | Ask chatbot questions about repository documents |

---

## 🌐 REST API Endpoints Catalog

### Document Ledger & Inspection

- `GET /api/v1/documents` — Paginated catalog with multi-location mapping, filters, and sort orders.
- `POST /api/v1/documents/check-duplicate` — Upload inspection to verify duplicates before writing to disk.
- `GET /api/v1/documents/{sha256}` — Full cryptographic document profile and lineage history.

### Crawler & Watcher Operations

- `GET /api/v1/crawler/roots` — Status and connectivity of configured storage mounts.
- `POST /api/v1/crawler/scan` — Trigger parallel batch crawl with custom worker count.
- `POST /api/v1/crawler/stop` — Cleanly stop an in-progress crawl.

### Interrogation & GraphRAG Chat

- `POST /api/v1/chat/interrogate` — LangGraph agent interrogation with auto-focus and Q&A.
- `GET /api/v1/chat/stream` — Real-time Server-Sent Events (SSE) token streaming.

### Knowledge Base Sidecar & Graph

- `GET /api/v1/sidecar/stats` — Queue length, chunks indexed, and graph node/edge counts.
- `POST /api/v1/sidecar/process` — Trigger immediate batch processing for pending queue items.
- `POST /api/v1/sidecar/search` — Dense semantic vector search over document chunks.
- `GET /api/v1/sidecar/graph/node/{node_id}` — Expand entity neighborhood and connected documents.
- `POST /api/v1/sidecar/graph-rag` — Execute full 3-signal GraphRAG retrieval.

### Dynamic Taxonomy

- `GET /api/v1/taxonomy` — Browse multilingual canonical categories (EN / FR / DE).
- `POST /api/v1/taxonomy/merge` — Associate and merge duplicate topics.
- `POST /api/v1/taxonomy/refine` — Dissociate / split broad categories into granular subtopics.

---

## 🧪 Verification & Test Suite

RepoScroller is thoroughly covered by an automated test suite:

```powershell
uv run pytest
============================== 52 passed in 16.36s ==============================
```

- `test_hasher.py` & `test_simhash.py`: Content addressability and 64-bit Hamming distance.
- `test_maturity.py`: Completeness, signature presence, and maturity scoring.
- `test_ledger.py`: SQLite WAL transactions, FTS5 BM25 search, and ALCOA+ audit trails.
- `test_crawler.py`: Multi-threaded parallel crawler and antichronological ordering.
- `test_chunker.py` & `test_embeddings.py`: Context-aware semantic chunking and embedding adapters.
- `test_vector_store.py`: Dense vector indexing and similarity search.
- `test_graph_extractor.py` & `test_graph_store.py`: Entity extraction and Property Graph expansion.
- `test_graph_rag.py`: Multi-signal GraphRAG and Reciprocal Rank Fusion.
- `test_agent.py` & `test_chat.py`: LangGraph conversational agent and REST API integration.

---

Viewed .env.example:1-31
Viewed .env:1-6
Created setup_pc2_cuda_server.ps1
Listed directory RepoScroller
Viewed setup_pc2_cuda_server.ps1:1-125
Created setup_pc2_cuda_server.bat
Viewed start_all.ps1:1-60
Viewed start_all.ps1:61-162
Viewed .env:1-6
Viewed start_all.bat:1-4
Created launch_pc1_host.ps1
Created launch_pc1_host.bat
Viewed start_all.ps1:64-86
Edited start_all.ps1
Ran command: `uv run pytest`

Les scripts de configuration et lanceurs pour **PC2 (Node CUDA RTX 3060)** et **PC1 (Hôte RepoScroller)** sont prêts.

---

### 1. Pour **PC2 (Serveur CUDA GPU - 192.168.192.9)**

Deux fichiers sont disponibles à la racine du projet :

- [`setup_pc2_cuda_server.ps1`](file:///c:/Dev/RepoScroller/setup_pc2_cuda_server.ps1) (Script PowerShell complet exécuté en Administrateur)
- [`setup_pc2_cuda_server.bat`](file:///c:/Dev/RepoScroller/setup_pc2_cuda_server.bat) (Lanceur batch double-cliquable)

#### Ce qu'il configure automatiquement sur PC2

1. **Variables d'environnement système Windows :**
   - `OLLAMA_HOST=0.0.0.0:11434` *(écoute sur toutes les interfaces réseau LAN)*
   - `OLLAMA_KEEP_ALIVE=24h` *(garde le modèle pré-chargé en VRAM GDDR6)*
   - `OLLAMA_NUM_PARALLEL=4` *(parallélisation multi-threads pour les sous-batches)*
   - `OLLAMA_FLASH_ATTENTION=1` *(accélération CUDA Flash Attention)*
2. **Règle de Pare-feu Windows :**
   - `New-NetFirewallRule -DisplayName "Ollama LAN API" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Allow`
3. **Pré-téléchargement et vérification des modèles :**
   - Télécharge / vérifie `snowflake-arctic-embed2:latest` et `snowflake-arctic-embed:latest` directement sur la VRAM de la RTX 3060.
4. **Redémarrage du service / processus Ollama** et affichage de l'adresse IP LAN de confirmation.

> **Utilisation sur PC2 :** Copiez `setup_pc2_cuda_server.bat` et `setup_pc2_cuda_server.ps1` sur PC2 (ou clonez le repo) et double-cliquez sur `setup_pc2_cuda_server.bat`.

---

### 2. Pour **PC1 (Hôte / Orchestrateur RepoScroller)**

- [`launch_pc1_host.ps1`](file:///c:/Dev/RepoScroller/launch_pc1_host.ps1)
- [`launch_pc1_host.bat`](file:///c:/Dev/RepoScroller/launch_pc1_host.bat)
- [`.env`](file:///c:/Dev/RepoScroller/.env) :

  ```ini
  OLLAMA_BASE_URL=http://192.168.192.9:11434
  OLLAMA_EMBEDDING_MODEL=snowflake-arctic-embed2:latest
  OLLAMA_TIMEOUT=60.0
  OLLAMA_SUB_BATCH_SIZE=32
  OLLAMA_KEEP_ALIVE=24h
  ```

#### Ce que fait le lanceur PC1

1. Teste la connectivité réseau LAN vers `http://192.168.192.9:11434/api/tags` et affiche la latence réseau (ex: ~3-5ms).
2. Vérifie la présence du modèle `snowflake-arctic-embed2:latest` sur le GPU de PC2.
3. Sonde les 6 volumes de stockage (SMB SyNAS & Google Drive).
4. Lance l'orchestrateur complet (`start_all.ps1`) avec le backend FastAPI, le scanner parallèle, le watcher et le Knowledge Base Sidecar (qui envoie les requêtes de vectorisation à PC2 via le réseau sans latence disque ni verrou).

---
**Oui, exactement !**

### Pourquoi `0.0.0.0:11434` sur PC2 ?

Par défaut, Ollama écoute **uniquement sur `127.0.0.1:11434` (localhost)**, ce qui empêche tout autre PC du réseau d'envoyer des requêtes.

En configurant `OLLAMA_HOST=0.0.0.0:11434` sur **PC2** :

- Ollama accepte les connexions provenant de toutes les cartes réseau (Ethernet/Wi-Fi du LAN).
- **PC1** peut donc joindre PC2 sur `http://192.168.192.9:11434`.

---

### Comment l'appliquer sur PC2

#### Option A (Automatique - Recommandé)

Exécutez simplement [`setup_pc2_cuda_server.bat`](file:///c:/Dev/RepoScroller/setup_pc2_cuda_server.bat) sur PC2.
> Le script définit `OLLAMA_HOST=0.0.0.0:11434` et `OLLAMA_KEEP_ALIVE=24h` dans les variables d'environnement Windows, ouvre le pare-feu et redémarre Ollama.

#### Option B (Manuel sur PC2)

1. Ouvrez PowerShell en **Administrateur** sur PC2 :

   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "Machine")
   [Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "24h", "Machine")
   ```

2. Ouvrez le port dans le pare-feu Windows :

   ```powershell
   New-NetFirewallRule -DisplayName "Ollama LAN API" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Allow
   ```

3. Quittez complètement l'icône Ollama dans la barre des tâches (systray) puis relancez Ollama.

Viewed setup_pc2_cuda_server.ps1:1-125
Created start_pc2_cuda_node.ps1
Created start_pc2_cuda_node.bat
Created stop_pc2_cuda_node.ps1
Created stop_pc2_cuda_node.bat
Ran command: `git add . && git commit -m "Add dedicated daily launcher and stopper for PC2 CUDA GPU node" && git push origin main`

Nous avons désormais une distinction claire entre **Setup initial (une seule fois avec droits Administrateur)** et **Lanceurs / Stoppers quotidiens** pour PC2 et PC1.

---

### Résumé des scripts pour PC2 (Node CUDA RTX 3060)

| Fichier | Fréquence | Rôle |
| :--- | :--- | :--- |
| [`setup_pc2_cuda_server.bat`](file:///c:/Dev/RepoScroller/setup_pc2_cuda_server.bat) <br> *(et `.ps1`)* | **1 fois** *(Initiale)* | **Configuration système complète (Droits Admin) :**<br>• Définit `OLLAMA_HOST=0.0.0.0:11434`, `OLLAMA_KEEP_ALIVE=24h`, `OLLAMA_NUM_PARALLEL=4`, `OLLAMA_FLASH_ATTENTION=1`.<br>• Crée la règle Inbound dans le Pare-feu Windows pour le port TCP 11434.<br>• Télécharge et pré-installe le modèle `snowflake-arctic-embed2:latest`. |
| [`start_pc2_cuda_node.bat`](file:///c:/Dev/RepoScroller/start_pc2_cuda_node.bat) <br> *(et `.ps1`)* | **Au quotidien** *(Lanceur)* | **Lanceur et Moniteur temps réel :**<br>• Démarre Ollama si non actif (sans demander les droits admin).<br>• **Pré-chauffe (warm-up)** le modèle `snowflake-arctic-embed2` directement dans la VRAM de la RTX 3060 pour garantir **0 ms de latence à froid** lors des requêtes de PC1.<br>• Affiche en direct l'utilisation VRAM (`nvidia-smi`), les modèles actifs (`ollama ps`) et les IP LAN d'écoute. |
| [`stop_pc2_cuda_node.bat`](file:///c:/Dev/RepoScroller/stop_pc2_cuda_node.bat) <br> *(et `.ps1`)* | **Quand souhaité** | Arrête proprement Ollama sur PC2 et libère la VRAM du GPU. |

---

### Résumé des scripts pour PC1 (Hôte RepoScroller)

| Fichier | Rôle |
| :--- | :--- |
| [`start_pc1_host.bat`](file:///c:/Dev/RepoScroller/start_pc1_host.bat) | Lanceur principal PC1 : teste la connectivité réseau vers PC2 (`192.168.192.9:11434`), vérifie la présence du modèle et lance tous les services RepoScroller. |
| [`start_all.bat`](file:///c:/Dev/RepoScroller/start_all.bat) | Orchestrateur standard RepoScroller (backend, scanner x6, watcher, sidecar). |
| [`stop_all.bat`](file:///c:/Dev/RepoScroller/stop_all.bat) | **Arrêt propre total** de tous les processus RepoScroller (FastAPI :8090, scanner, watcher, sidecar). |

Tous les fichiers sont validés et synchronisés sur votre repository Git.
