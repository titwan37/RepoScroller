---
id: docx-openxml-native-extraction
trigger: "when extracting text from docx or Word OpenXML files"
confidence: 0.92
domain: "extraction"
source: "session-observation"
scope: project
project_id: "bc9c9ca83985"
project_name: "RepoScroller"
---

# Native OpenXML Docx Extraction

## Action
Extract text from Word `.docx` documents by opening the OpenXML container with `zipfile` and parsing XML elements `<w:p>` and `<w:t>` from `word/document.xml` along with metadata from `docProps/core.xml`, rather than reading raw binary streams or compressed zip bytes.

## Evidence
- Eliminated binary zip garbage artifacts from document previews.
- Verified across multilingual test suites (French and German special characters).

---
id: utf8-database-pragma-enforcement
trigger: "when initializing sqlite database connections or serializing json"
confidence: 0.95
domain: "persistence"
source: "session-observation"
scope: project
project_id: "bc9c9ca83985"
project_name: "RepoScroller"
---

# Strict UTF-8 Database & Serialization Enforcement

## Action
Always execute `PRAGMA encoding = 'UTF-8';` on SQLite connection establishment, and pass `ensure_ascii=False` to all `json.dumps()` calls storing metadata, graph nodes, and properties to prevent escaping accented characters and emojis.

## Evidence
- Enforced clean UTF-8 handling across FTS5 and JSON columns in `reposcroller_ledger.db`.
- Tested with 60+ test cases covering French, German, and emojis.

---
id: graphrag-multi-signal-response-format
trigger: "when structuring GraphRAG explorer search responses"
confidence: 0.88
domain: "agents"
source: "session-observation"
scope: project
project_id: "bc9c9ca83985"
project_name: "RepoScroller"
---

# Multi-Signal GraphRAG Structured Output

## Action
Structure hybrid retrieval outputs with both `top_candidates` and `ranked_results` arrays, enriched with explicit scoring signals: dense vector similarity, BM25 / FTS lexical rank, graph neighborhood expansions, and connected entity links.

## Evidence
- Unified the REST API route with frontend Web Dashboard expectations.
- Enables visual inspection of multi-vector fusion and graph relationships.

---
id: qdrant-enterprise-dual-sync
trigger: "when designing vector database plugins alongside local SQLite ledgers"
confidence: 0.85
domain: "architecture"
source: "session-observation"
scope: project
project_id: "bc9c9ca83985"
project_name: "RepoScroller"
---

# Dual-Sync Architecture for Vector Storage

## Action
Preserve local SQLite WAL as the single ALCOA+ durable source of truth for chunks and embeddings, while optionally dual-syncing embeddings to an external HNSW vector database (Qdrant) for enterprise scale (>500k chunks).

## Evidence
- Created `QdrantVectorStorePlugin` with graceful fallback and fast 0ms bypass when disabled.
