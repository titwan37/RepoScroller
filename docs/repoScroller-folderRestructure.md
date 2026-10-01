A clean separation between **frontend** and **backend** aligns `RepoScroller` with your established multi-tier deployment standards across AFA Studio (similar to `SwissLexiBot` and `JobAgent Apply`).

Here is the best-practice architecture tailored specifically to `RepoScroller`'s document ingestion, SQLite WAL state machine, and hybrid retrieval engine.

---

### Recommended Folder Layout

```text
C:\Dev\RepoScroller\
│
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml              # Root or backend workspace definition
├── package.json                # Root orchestration scripts (optional)
│
├── backend/                    # Python Backend (FastAPI, Crawlers, Ledger, RAG)
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── reposcroller/           # Core Python package
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI entrypoint (uvicorn)
│   │   ├── config.py           # Pydantic BaseSettings (.env loading)
│   │   │
│   │   ├── api/                # HTTP & SSE endpoints
│   │   │   ├── __init__.py
│   │   │   ├── v1/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── router.py   # Aggregates /chat, /documents, /health
│   │   │   │   ├── documents.py# Upload, search, duplicate detection
│   │   │   │   ├── chat.py     # SSE LangGraph streaming
│   │   │   │   └── health.py   # GET /api/v1/health
│   │   │
│   │   ├── core/               # Domain engines & state machine
│   │   │   ├── __init__.py
│   │   │   ├── crawler.py      # Multi-mount polling crawler (watchdog)
│   │   │   ├── hasher.py       # SHA-256 + text MinHash/SimHash engine
│   │   │   ├── maturity.py     # Completeness & draft-vs-final scorer
│   │   │   └── extractor.py    # PyMuPDF (fitz) & layout parser
│   │   │
│   │   ├── storage/            # ALCOA+ persistence layer
│   │   │   ├── __init__.py
│   │   │   ├── db.py           # SQLite connection pool (WAL mode)
│   │   │   ├── ledger.py       # document_ledger & file_locations repository
│   │   │   └── migrations/     # SQL schema setup & indexes (FTS5)
│   │   │
│   │   ├── rag/                # Hybrid Retrieval & Knowledge Graph
│   │   │   ├── __init__.py
│   │   │   ├── hybrid_store.py # ChromaDB dense vector + SQLite FTS5 BM25
│   │   │   └── neo4j_graph.py  # Lineage relationships (SUPERSEDES, COPY_OF)
│   │   │
│   │   └── agents/             # Agentic Intelligence (LangGraph)
│   │       ├── __init__.py
│   │       ├── state.py        # TypedDict agent state context
│   │       ├── graph.py        # Compiled workflow DAG
│   │       └── nodes/          # Router, DeduplicationAuditor, Synthesizer
│   │
│   ├── taxonomy/               # Domain taxonomy classifications
│   ├── tests/                  # Pytest unit & integration tests
│   └── data/                   # Server-local data directory (ignored by Git)
│       ├── reposcroller_ledger.db
│       └── chroma_db/
│
├── frontend/                   # Modern SPA UI (Angular / React / Vite)
│   ├── package.json
│   ├── vite.config.ts / angular.json
│   ├── tsconfig.json
│   ├── index.html
│   ├── public/
│   │   └── favicon.png
│   └── src/
│       ├── main.ts
│       ├── app/
│       │   ├── components/     # DocumentTable, StreamChat, LineageViewer
│       │   ├── services/       # ReposcrollerApiClient (SSE EventSource)
│       │   └── models/         # TypeScript contracts matching Pydantic
│       └── assets/
│
└── scripts/                    # Automation & Dev scripts
    ├── start_dev.bat           # Starts backend (3739) & frontend (3039)
    ├── reset_ledger.py         # DB migration / purge utility
    └── start_scanner.bat       # Standalone background crawler worker

```

---

### Key Architectural Improvements

1. **Clear Boundary for Automation & Builds (`deploy_master.yml`)**:

* The frontend can be built locally with `npm run build -- --base-href /reposcroller/` inside `RepoScroller/frontend`.

* The backend installs cleanly from `RepoScroller/backend/requirements.txt` without dragging node modules or build files.

* Rsync easily isolates the runtime data (`backend/data/` or root `*.db` exclusions) so production ledgers are never overwritten by local developer runs.

1. **Decoupled API and UI Lifecycle**:

* **Backend PM2 Service (`Port 3739`)**:

```bash
pm2 start "python3 -m uvicorn reposcroller.main:app --host 127.0.0.1 --port 3739" --name reposcroller-backend

```

* **Frontend PM2 Service (`Port 3039`)**:

```bash
pm2 start serve --name reposcroller-frontend -- -s frontend/dist -p 3039

```

* This cleanly resolves the port split between `/reposcroller/api` (port `3739`) and `/reposcroller/` (port `3039`) in your Nginx configurations (`hub.conf` and `afastudio.conf.j2`).

1. **Storage Isolation (ALCOA+ Compliance)**:

* Keep SQLite WAL files (`*.db`, `*-wal`, `*-shm`) and vector indices in a dedicated `backend/data/` directory rather than scattered at the project root.

* Ensure `backend/data/` is added to `.gitignore` and `rsync_opts` exclude rules.

1. **Self-Contained Shared Contracts**:

* Export Pydantic response models from `backend/reposcroller/api/v1/` directly to TypeScript interfaces in `frontend/src/app/models/` to keep SSE chunk frames and document metadata strictly typed across the boundary.
