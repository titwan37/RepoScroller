# High-Level RAG System Design – repoScroller

At **24,511 documents**, the corpus typically yields **500,000 to 2,000,000 text chunks** (assuming average document lengths of 10–30 pages). At this scale, naïve vector-only retrieval breaks down: high-frequency terms blur semantic vector spaces, keyword references (e.g., invoice numbers, statute codes, exact names) get lost, and multi-turn chat suffers from context drift.

The end-to-end production architecture below implements **Hybrid Retrieval (Dense + Sparse) + Cross-Encoder Reranking**, accompanied by an **Agentic State Graph** for multi-turn conversational memory.

---

## 1. System Architecture

```
                                 [ User Web UI / Chat Client ]
                                               │
                                               ▼
                              [ FastAPI Gateway (Auth / Rate Limit) ]
                                               │
                                               ▼
                       ┌────────────────────────────────────────────────┐
                       │  LangGraph Conversational State Machine        │
                       │  • PostgreSQL Checkpointer (Turn State)        │
                       │  • Memory Layer (Recent Turns + Summary/Mem0)  │
                       │  • Query Decontextualizer / Condenser          │
                       │  • Retrieval Intent Router                     │
                       └──────────────┬───────────────────▲─────────────┘
                                      │                   │
                     ┌────────────────┴──────────────┐    │ Evaluates &
       [Direct Chat / Chit-chat]        [Retrieval Path]  │ Synthesizes
                     │                               │    │
                     └─────────────────┐             ▼    │
                                       │    ┌───────────────────┐
                                       │    │ Hybrid Retrieval  │
                                       │    │ Engine            │
                                       │    └─────────┬─────────┘
                                       │              │
                                       ▼              ▼
                               [ LLM Generation with Grounded Context ]
                                               │
                                               ▼
                                 [ SSE / Streaming Token Output ]

```

---

## 2. Ingestion & Indexing Pipeline (24,511 Documents)

Running 24k+ documents sequentially through an LLM or embedding endpoint causes timeouts. The ingestion needs a batch worker pool:

```
[Raw Files] ──> [Docling / PyMuPDF] ──> [Chunking & Enrichment] ──┬──> [Dense Vector Embeddings]
(PDF, DOCX,     (Extract text, tables,   (Semantic chunking        │    (e.g., text-embedding-3,
 EML, Markdown)  digital signatures)      500-800 tokens + headers)│     bge-large, arctic-embed)
                                                                   │            │
                                                                   │            ▼
                                                                   │    [Qdrant / Milvus / pgvector]
                                                                   │
                                                                   └──> [Sparse Lexical Tokens]
                                                                        (BM25 / SPLADE)
                                                                                │
                                                                                ▼
                                                                        [Elasticsearch / SQLite FTS5]

```

* **Chunking Strategy:** Chunk between **500–800 tokens** with a 10–15% overlap. Prepend top-level metadata (document title, relative folder path, date) directly to the chunk text so isolated chunks retain global context.
* **Document Ledger (Source of Truth):** Store canonical document metadata, chunk text, and cryptographic SHA-256 hashes in a transactional database (PostgreSQL or SQLite WAL) to ensure duplicate detection and lineage tracking.
* **Dual Indexing:**
* **Dense Store:** Qdrant, Milvus, or PostgreSQL with `pgvector` (HNSW index, Cosine distance).
* **Sparse Store:** Elasticsearch, OpenSearch, or SQLite FTS5 (BM25) to index technical terms, IDs, and dates without embedding degradation.

---

## 3. Hybrid Retrieval & Reranking Engine

Pure semantic search often fails on corpus-specific identifiers. The dual-retrieval pipeline combines dense and sparse signals:

```
                      [ Decontextualized Query ]
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
     [ Dense Search (Top 40) ]       [ BM25 Search (Top 40) ]
     (Semantic / conceptual fit)     (Exact tokens, codes, dates)
                  │                               │
                  └───────────────┬───────────────┘
                                  ▼
                [ Reciprocal Rank Fusion (RRF, k=60) ]
                                  │
                                  ▼
                          [ Top 30 Candidates ]
                                  │
                                  ▼
               [ Cross-Encoder Reranker (bge-reranker-v2 / Cohere) ]
                                  │
                                  ▼
                     [ Top 5-8 Relevant Context Chunks ]

```

1. **Parallel Execution:** Fetch Top 40 from the dense index and Top 40 from BM25.
2. **Reciprocal Rank Fusion (RRF):** Merge candidate lists via:

$$\text{RRF Score}(d) = \sum_{m \in \{\text{dense}, \text{sparse}\}} \frac{1}{60 + \text{rank}_m(d)}$$

This avoids score-calibration mismatches between cosine similarity and BM25 curves.
3. **Cross-Encoder Reranking:** Evaluate query-chunk interaction at token level for the top 30 candidates to select the final 5–8 chunks. This cuts context noise before LLM prompting.

---

## 4. Multi-Turn Conversational Memory & Agent Workflow

In a discussion over 24k documents, conversational queries like *"What were the key stipulations in the second contract?"* or *"Who signed it?"* fail if sent directly to vector search because pronouns lack search terms.

Use **LangGraph** with a **StateGraph** to govern the conversational lifecycle:

```
           [ Start ]
               │
               ▼
      [ Load Context & History ]
               │
               ▼
     [ Rewrite Query Node ]  ── (Resolves anaphora: "Who signed it?" ➔ "Who signed Contract #402?")
               │
               ▼
     [ Intent Router Node ]
        ├─ General chit-chat / clarification ──> [ Direct LLM Response ]
        └─ Requires corpus retrieval ──────────> [ Hybrid Retrieval Node ]
                                                        │
                                                        ▼
                                             [ Context Evaluator Node ]
                                                ├─ Relevant chunks found ─> [ Synthesize Answer ]
                                                └─ Insufficient info ────> [ Fallback / Ask Clarification ]

```

### Memory Architecture

* **Working Session Memory (Short-Term):** Retain the last 6–10 turns in PostgreSQL via `PostgresSaver` checkpointers (keyed by `session_id` / `thread_id`).
* **Long-Term Memory:** Summarize older message turns into an rolling background state or use a memory entity store (such as Mem0) to retain user preferences, referenced entities, and active topics across long sessions.
* **Query Re-writer Prompt:** Instruct a fast model (e.g., `llama-3.2-3b`, `gpt-4o-mini`, or `gemini-flash`) to generate a standalone query:

```text
Given the conversation history and the latest user turn, rewrite the user input 
into a standalone, unambiguous search query containing all implicit entities, 
names, and dates. If the user input is greeting/chit-chat, leave it unchanged.

```

---

## 5. Production Tech Stack Setup

| Component | Recommended Tooling | Purpose at 24k Scale |
| --- | --- | --- |
| **API Framework** | **FastAPI** (Python 3.11+) | Async endpoint handling, SSE streaming responses, file ingestion endpoints. |
| **Agent / Memory Flow** | **LangGraph** + `PostgresSaver` | Stateful graph execution, conditional routing, multi-turn checkpointing. |
| **Vector Index** | **Qdrant** or **PostgreSQL (`pgvector` / HNSW)** | Fast cosine/inner-product search with metadata filtering. |
| **Lexical Index** | **Elasticsearch** or **SQLite FTS5** | Deterministic keyword and exact reference search. |
| **Embedding Model** | `text-embedding-3-large`, `bge-large-en-v1.5`, or `snowflake-arctic-embed` | Dense semantic representation. |
| **Reranker** | `bge-reranker-large` / `cohere-rerank-v3` | High-precision candidate pruning. |
| **Worker / Queue** | **Celery** + **Redis** (or ARQ) | Async document parsing, OCR jobs, and embedding generation. |

---

## 6. Implementation Blueprint

### LangGraph Conversational Flow (`agent_graph.py`)

```python
from typing import TypedDict, List, Annotated
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

class RagConversationState(TypedDict):
    messages: List[BaseMessage]
    standalone_query: str
    needs_retrieval: bool
    retrieved_chunks: List[dict]
    answer: str

def rewrite_query_node(state: RagConversationState):
    history = state["messages"][:-1]
    current = state["messages"][-1].content
    
    if not history:
        return {"standalone_query": current, "needs_retrieval": True}
        
    prompt = f"Rewrite to standalone query based on history:\n{history}\nUser: {current}"
    # Invoke fast routing LLM here
    rewritten = llm_fast.invoke(prompt).content
    return {"standalone_query": rewritten, "needs_retrieval": True}

def retrieve_node(state: RagConversationState):
    query = state["standalone_query"]
    # 1. Fetch dense (Qdrant/pgvector) & sparse (BM25)
    dense_hits = vector_db.search(query, limit=40)
    sparse_hits = fts_db.search(query, limit=40)
    
    # 2. Reciprocal Rank Fusion
    fused_candidates = rrf_merge(dense_hits, sparse_hits, k=60)
    
    # 3. Rerank to top 6
    top_chunks = reranker.rank(query, fused_candidates, top_n=6)
    return {"retrieved_chunks": top_chunks}

def generate_node(state: RagConversationState):
    context = "\n\n".join([f"[{c['source']}]: {c['text']}" for c in state["retrieved_chunks"]])
    system_msg = SystemMessage(content=f"Answer using only this context:\n{context}")
    
    response = llm_main.invoke([system_msg] + state["messages"])
    return {"answer": response.content}

# Graph Wiring
workflow = StateGraph(RagConversationState)
workflow.add_node("rewrite", rewrite_query_node)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("generate", generate_node)

workflow.set_entry_point("rewrite")
workflow.add_edge("rewrite", "retrieve")
workflow.add_edge("retrieve", "generate")
workflow.add_edge("generate", END)

# Compile with persistent checkpointing
checkpointer = PostgresSaver.from_conn_string("postgresql://user:pass@localhost:5432/rag_db")
app = workflow.compile(checkpointer=checkpointer)

```

To see an end-to-end walkthrough covering query rephrasing, memory management, and evaluation in LangGraph, watch this guide on [Conversational Agentic RAG](https://www.youtube.com/watch?v=Fc0qYL6Divg&utm_source=gemini).

This video walk-through is directly relevant because it demonstrates building multi-turn conversational memory, rephrasing follow-up questions, and routing retrieval inside a LangGraph architecture.

---

### Role of `snowflake-arctic-embed:latest` with a Vector DB

`snowflake-arctic-embed:latest` is a dense embedding model optimized for retrieval-augmented generation (RAG) and semantic search tasks:

* **Dense Semantic Mapping:** It converts textual passages (chunks) into dense, high-dimensional floating-point vectors (e.g., 1024 dimensions) capturing semantic meaning rather than literal keyword matches.
* **Vector DB Indexing & Nearest Neighbor Retrieval:** In a vector database (e.g., ChromaDB, FAISS, Qdrant, Milvus), it enables approximate nearest neighbor (ANN) searches (cosine similarity / inner product) so queries like *"employment terms"* retrieve passages discussing *"notice periods"* or *"salary stipulations"* even without exact keyword overlap.
* **Context vs. Determinism:** While effective for thematic discovery and semantic clustering, dense vector models are probabilistic and chunk-dependent. They are not suited for bit-exact deduplication (where SHA-256 is needed) or draft revision tracking (where 64-bit Locality-Sensitive Hashing like SimHash is preferred).

---

### Adding a Knowledge Graph Sidecar Agent (Neo4j + LangGraph)

**Yes, a sidecar agent consolidating data into a Knowledge Graph (e.g., Neo4j orchestrated via LangGraph) fits naturally as an asynchronous or post-ingestion worker.**

While vector databases excel at finding *unstructured semantic similarity*, a knowledge graph captures *structured, multi-hop entity relationships and provenance chains*.

```
   [Ingestion Stream / Ledger]
               │
               ├────────────────────────────────────────┐
               ▼                                        ▼
    [Dense Vector DB]                        [Sidecar Consolidation Agent]
  (e.g., Chroma + Arctic Embed)                (LangGraph StateGraph Worker)
  • Text chunk similarity                               │
  • Thematic discovery                                  ▼
                                                [Entity & Relation Extraction]
                                                • NER: Person, Org, Date, Contract
                                                • Lineage: REPLACES, DERIVED_FROM
                                                        │
                                                        ▼
                                                [Neo4j Property Graph]
                                                • Multi-hop entity navigation
                                                • GraphRAG hybrid retrieval

```

---

### How the Sidecar Architecture Works

#### 1. Decoupled Processing via a Change-Data-Capture / Job Queue

* When a document or record is ingested into the primary ledger/vector store, an event is posted to a lightweight queue (e.g., Redis, SQLite job table, or background worker thread).
* The **LangGraph sidecar agent** consumes the job out-of-band so it does not block the primary file crawler or API endpoints.

#### 2. LangGraph StateGraph Consolidation Workflow

A dedicated `StateGraph` in LangGraph can coordinate the consolidation steps:

1. **Entity & Relation Extraction (`extract_entities`):**

* Uses an LLM (local Ollama or cloud) with structured output (Pydantic schema) to extract:
* **Entities:** Parties/Signatories (`Person`, `Organization`), Jurisdictions (`Location`), Legal statutes, Effective dates, Case numbers.
* **Relationships:** `(:Person)-[:SIGNS]->(:Contract)`, `(:Contract)-[:GOVERNED_BY]->(:Law)`, `(:Document)-[:SUPERSEDES]->(:Document)`.

1. **Entity Resolution / Deduplication (`resolve_nodes`):**

* Normalizes variants before writing (e.g., mapping `"UBS AG"`, `"UBS Switzerland"`, and `"UBS"` to a single canonical entity node).

1. **Graph Ingestion (`sync_to_neo4j`):**

* Writes nodes and directed edges using idempotent Cypher queries (`MERGE` instead of `CREATE`).

```cypher
// Example Cypher written by the sidecar
MERGE (doc:Document {sha256: $doc_hash})
  ON CREATE SET doc.title = \(title, doc.category =\)category

MERGE (party:Party {name: $canonical_party_name})
MERGE (party)-[:PARTY_TO {role: $role}]->(doc)

WITH doc
UNWIND $superseded_hashes AS prev_hash
MATCH (prev:Document {sha256: prev_hash})
MERGE (doc)-[:SUPERSEDES {detected_at: datetime()}]->(prev)

```

---

### GraphRAG: Combining the Vector DB and the Knowledge Graph

Once both the Vector DB and Neo4j are populated, the querying agent can perform **Hybrid GraphRAG**:

1. **Vector Search:** `snowflake-arctic-embed` retrieves top-k relevant text chunks matching the user's intent.
2. **Graph Expansion:** For the entities found in those chunks, query Neo4j for 1-hop or 2-hop connected nodes (e.g., *"What other contracts or court decisions involve this counterparty?"* or *"Which document supersedes this draft?"*).
3. **Context Fusion:** Inject both the semantic chunks and the structured graph relationships into the LLM context window for a complete, grounded response.
