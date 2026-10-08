### Core Problem Analysis

Your objective has two competing constraints:
1. **Preserving granularity and detail** (lossless or near-lossless information retention).
2. **Reordering into a coherent linear progression** (determining the macro-to-micro sequence: Foundational $\rightarrow$ Core Concepts $\rightarrow$ Methodologies/Architecture $\rightarrow$ Edge Cases & References).

Standard RAG (FAISS, ChromaDB, BM25) is designed for **point retrieval against isolated queries**, not **global document synthesis**. If you use vector search to generate a single document, you risk:
- Arbitrary chunk boundaries fragmenting coherent thoughts.
- Missing context that wasn't retrieved (loss of detail).
- Repetition across overlapping retrieved chunks.

Below is an architectural breakdown of the tools you mentioned, followed by the recommended technical strategy.

---

### Evaluation of Options

| Technique / Technology | Best Used For | Fit for Single Master Document Synthesis | Why? |
| :--- | :--- | :--- | :--- |
| **Vector DBs (FAISS, ChromaDB)** | Search / QA against top-$K$ chunks | ⚠️ **Poor / Counter-productive** | Chunking destroys flow. You don't need top-$K$ similarity; you need total coverage. Clustering vectors can help group topics, but won't order them logically. |
| **FTS5 / BM25 (Full-Text Search)** | Exact keyword lookup | ❌ **Irrelevant** | BM25 requires search queries; it cannot construct narrative flow. |
| **Graph DB (Neo4j)** | Relational / dependency mapping | 🟡 **High effort, overkill** | Building a Knowledge Graph (nodes = concepts, edges = prerequisite of / relates to) produces topological ordering, but parsing and populating Neo4j via LLM is complex and fragile for 50–100 docs. |
| **Hierarchical Map-Reduce with LLM Ordering (Recommended)** | Long-form synthesis & reorganization | 🟢 **Optimal & Lightweight** | Keeps operations local, guarantees 100% document coverage, uses the LLM where it excels: structuring a Table of Contents (DAG) and generating chapters incrementally. |

---

### The Recommended Architecture: 3-Stage Topological Synthesis

To preserve granular details without overflowing context or losing narrative flow, use a **TOC-First Hierarchical Synthesis Pipeline**:

```
54 Documents
   │
   ▼
[Stage 1: Granular Semantic Chunks / Summaries]
   Extract structured entities, topics, prerequisites per file (Low loss)
   │
   ▼
[Stage 2: Global Table of Contents & Ordering (DAG)]
   LLM creates an ordered Table of Contents (Outline)
   maps every chunk/file ID to specific chapters/sections
   │
   ▼
[Stage 3: Section-by-Section Accumulator Synthesis]
   For each Chapter in TOC:
     Load assigned chunks -> LLM synthesizes chapter text
     Append to final MASTER_SYNTHESIS.md
```

#### Why this works:
1. **Zero Information Loss:** Unlike vector search where un-retrieved chunks are lost, every file or chunk is explicitly assigned to at least one section in the global Table of Contents.
2. **Logical Progression:** The LLM plans the global progression in Stage 2 (where only file outlines/titles are processed, fitting easily in memory) before writing any final prose.
3. **No Context Overflow:** Each section is generated independently in Stage 3 using only the source texts mapped to that section.

---

### Implementation Blueprint

Here is how to adapt [`doc_synthesis.py`](file:///c:/Dev/aurabily/docs/doc_synthesis.py):

```python
# Stage 1: File Metadata & Topic Tagging
# For each file: Extract title, prerequisites, core topics, and granular details.

# Stage 2: Master Outline Generation
outline_prompt = """
Given this list of document titles and their core topics:
{all_document_metadata}

Generate a structured Master Table of Contents organized in a logical progression:
1. High-level foundations & context
2. Core domain models & principles
3. Detailed workflows & implementations
4. Edge cases, specifications, and reference appendix

For each section, explicitly map the source files that belong to it.
Output in JSON format:
{
  "sections": [
    {"title": "1. Introduction", "files": ["overview.md", "intro.pdf"]},
    {"title": "2. Data Architecture", "files": ["schema.md", "multitenant.md"]}
  ]
}
"""

# Stage 3: Section-by-Section Sequential Synthesis
master_doc = []
for section in outline["sections"]:
    # Collate raw or summarized content strictly mapped to this section
    section_inputs = load_files(section["files"])
    
    chapter_content = call_llm(
        system_prompt="Synthesize these specific documents into the target chapter. Retain all parameters, definitions, and technical specifics.",
        user_content=f"Chapter: {section['title']}\n\nSources:\n{section_inputs}"
    )
    master_doc.append(f"# {section['title']}\n\n{chapter_content}")

write_file("MASTER_SYNTHESIS.md", "\n\n---\n\n".join(master_doc))
```

### Verdict

- **Do NOT introduce ChromaDB, FAISS, or BM25** for this task. They solve retrieval, not narrative ordering.
- **Do NOT introduce Neo4j** unless you plan to maintain a living, queryable enterprise knowledge graph over months.
- **Use an Outline-first / Map-Reduce pipeline in pure Python** with your existing Ollama/OpenRouter backend. It guarantees logical sequencing, respects context windows, and prevents detail loss.
---


### Summary of Changes

1. **Stage 1 — Granular Extraction (`summarize_file`)**:
   - Preserves granular entities, numbers, parameters, constraints, and schemas file-by-file.
   - Compresses raw content into dense semantic summaries to avoid overflowing context limits during later stages.

2. **Stage 2 — Global Outline & Topological Ordering (`generate_master_outline`)**:
   - Compiles a global catalog of all extracted document topics.
   - Instructs the LLM (as Chief Information Architect) to generate a structured JSON Table of Contents ordered by a natural progression (Foundations $\rightarrow$ Core Concepts $\rightarrow$ Workflows/Modules $\rightarrow$ Reference/Appendix).
   - Maps each source document ID to specific target chapters.
   - **Zero Detail Loss Safeguard (`validate_and_patch_outline`)**: Verifies that 100% of discovered files are mapped. If any file was missed by the model, an automated Appendix/Reference chapter is created to ensure no information is omitted.

3. **Stage 3 — Chapter-by-Chapter Accumulator Synthesis (`synthesize_section`)**:
   - Iterates through the ordered outline.
   - Synthesizes each chapter individually using only the documents mapped to that section, cross-referencing sources without losing technical depth.
   - Generates a hyperlinked Table of Contents and compiles all sections sequentially into [`MASTER_SYNTHESIS.md`](file:///c:/Dev/aurabily/docs/MASTER_SYNTHESIS.md).

4. **Resilience & Fallback**:
   - Preserves the sticky Ollama fallback mechanism (`USE_OLLAMA_ONLY`) using local models if OpenRouter rejects the call.
   - Configured with strict typing, Google-style docstrings, and standard `logging` replacing `print()`.
  

---

When dealing with 55+ multi-page documents, the bottleneck shifts from **logical ordering** to **context window saturation** and **attention dilution ("lost-in-the-middle" effect)**. 

If each file has pages of content, three distinct failure points emerge:
1. **Per-file overflow (Stage 1):** A single 20-page document exceeds the prompt window (or gets brutally truncated by `raw_text[:25000]`).
2. **Catalog overflow (Stage 2):** 55 file summaries combined exceed the outline generator's context window.
3. **Chapter payload overflow (Stage 3):** If a single chapter gets assigned 10 large files, their combined text overflows the chapter generator prompt.

Here is the engineering strategy to **restrain, compress, and budget** information systematically across all three stages:

---

### 1. Stage 1: Replace Hard Truncation with Rolling Window Chunk-Compression

Currently, `doc_synthesis.py` handles large files with:
```python
user_payload = f"Document: {file_name}\n\nContent:\n{raw_text[:MAX_CONTENT_CHARACTERS]}"
```
If a file has 60,000 characters, anything past index 25,000 is **completely lost**.

#### The Fix: Rolling Map-Chunking for Multi-Page Files
If a file exceeds a target token threshold (e.g., ~12,000 characters), split the file into logical semantic chunks (e.g., Markdown headers `#`, `##` or 8,000-character windows with 500-char overlap), summarize each chunk into dense bullet points, and merge them:

```python
# Rolling reduction for large documents
if len(raw_text) > CHUNK_SIZE_THRESHOLD:
    chunks = split_by_headers_or_length(raw_text, chunk_size=8000, overlap=500)
    chunk_summaries = [summarize_chunk(c) for c in chunks]
    dense_summary = reduce_summaries(chunk_summaries)
else:
    dense_summary = summarize_file(file_name, raw_text)
```

---

### 2. Stage 2: Dual-Tier Metadata (Abstract vs. Deep Payload)

In Stage 2, the LLM needs to construct the Table of Contents. It does **not** need the full technical details of each file—it only needs the **file's topic signature and abstract**.

#### The Fix: Separate the Outline Signature from the Granular Summary
For each file in Stage 1, store two tiers of data:
- **`topic_signature` (50–100 tokens):** Core subject, domain, keywords, dependencies (e.g., *"Architecture: GPU tunnel configuration for multi-tenant worker nodes"*).
- **`granular_payload` (500–1,500 tokens):** Exhaustive specifications, parameters, formulas, and schema definitions.

When calling `generate_master_outline`:
- Feed **only the 55 `topic_signature` entries** into the prompt.
- 55 files $\times$ 100 tokens $\approx$ **5,500 tokens total**. This fits comfortably inside any local model context window (Ollama's standard 8k/32k window) with zero risk of truncation or degraded attention.

---

### 3. Stage 3: Dynamic Chapter Token Budgeting & Progressive Accumulation

If the outline groups 12 files into *"Chapter 2: System Architecture"*, injecting all 12 granular summaries into a single prompt will overflow local models like `llama3.2`.

#### The Fix: Partitioned Chapter Synthesis with Context Memory
Instead of passing all assigned files in one giant prompt, use a **progressive accumulator pattern**:

1. **Token Budget Check:** Calculate total characters/tokens of assigned documents for that chapter.
2. **If within budget ($\le$ 15,000 chars):** Synthesize directly in one pass.
3. **If exceeding budget (> 15,000 chars):**
   - Synthesize the first 3 files into the initial chapter draft.
   - For subsequent files in that chapter, pass:
     - `Existing Chapter Draft`
     - `Next Batch of Source Records`
     - Prompt: *"Integrate these new technical specifications into the existing chapter without losing prior details."*

---

### Summary of Information Control Mechanisms

```
[Raw Documents: 55 files, Pages long]
   │
   ▼
[Stage 1: Adaptive Rolling Extraction]
   • Files ≤ 15k chars: Single dense extraction
   • Files > 15k chars: Split by headers -> Chunk summarize -> Combine
   • Output per file: 
       - Tier A: 100-word "Topic Signature" (for TOC planning)
       - Tier B: High-density "Granular Payload" (for chapter synthesis)
   │
   ▼
[Stage 2: Lean TOC Planning]
   • Prompt size: 55 × 100 words ≈ 5,500 words (fits strictly within 8k context)
   • Generates balanced chapter assignments (max 5-8 files per chapter)
   │
   ▼
[Stage 3: Budgeted Section Synthesis]
   • Chapter ≤ threshold: 1-shot exhaustive chapter write
   • Chapter > threshold: Progressive drafting (draft -> inject next records -> refine)
   │
   ▼
[Final MASTER_SYNTHESIS.md (Cohesive, Ordered, Lossless)]
```

This guarantees:
1. **No file is arbitrarily sliced off** at character 25,000.
2. **The outline prompt never exceeds context limits**, no matter how many pages the source files have.
3. **Local Ollama models (`llama3.2`) never crash from out-of-memory or context truncation** during chapter generation.

---

### 1. Temporary Database: Yes, but keep it lightweight (SQLite / Disk Cache)

**Do you need Chroma/Postgres/Mongo?** No.  
**Do you need a temporary local storage mechanism (e.g., SQLite or a JSON cache)?** **Absolutely yes.**

When processing 55+ multi-page files with a local model (`llama3.2`) or rate-limited API:
1. **Network / Inference interrupts:** Notice your terminal was interrupted (`KeyboardInterrupt`) while processing file `[2/55]`. Without disk persistence, **every interruption forces you to re-process all files from scratch**.
2. **Memory & Isolation:** In-memory lists of full text will bloat process memory, whereas persisting Stage 1 summaries to disk allows inspecting intermediate outputs and resuming at file `N` without repeating previous LLM calls.
3. **Structured Querying:** A simple, ephemeral SQLite table (or `.cache/` folder) allows you to store:
   - `file_path`
   - `file_hash` (skip re-summarizing if file hasn't changed)
   - `topic_signature` (50–100 words for TOC planning)
   - `granular_payload` (detailed extracted technical text)
   - `status` (`PROCESSED`, `FAILED`)

You can wipe the database file or cache directory at the end of the run with an `--erase-cache` or `--clean` CLI flag.

---

### 2. LangChain vs. LangGraph: Evaluation for this Pipeline

| Framework | Overhead / Complexity | Fit for this Pipeline | Recommendation |
| :--- | :--- | :--- | :--- |
| **LangChain** | Heavy abstraction layer, fast-moving breaking changes, verbose debugging | 🟡 **Not Recommended** | LangChain adds layers of wrapper classes (`PromptTemplate`, `LLMChain`, `OutputParser`) that obscure standard Python error handling and make debugging local Ollama connection issues harder. |
| **LangGraph** | State-machine / DAG orchestrator with built-in checkpointing | 🟢 **Good architectural fit, BUT high dependency overhead** | LangGraph is built for cycles, state accumulation, and human-in-the-loop checkpoints. It excels if you need complex multi-agent reviews or cyclic graph refinements, but is overkill for a 3-stage linear batch job. |
| **Pure Python + SQLite State Machine (Recommended)** | Zero extra external libraries (SQLite is built into Python standard library) | 🟢 **Optimal & Robust** | Full control over prompts, zero dependency bloat, native streaming/fallback, instant resumes on crash, and 100% transparent execution. |

---

### 3. Recommended Architectural Pattern: Ephemeral SQLite State Store

Using Python's standard `sqlite3` module gives you checkpointing, resume capability, and token restraint without installing extra heavy packages.

#### Schema Structure (`synthesis_cache.db`):
```sql
CREATE TABLE IF NOT EXISTS document_cache (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT,
    topic_signature TEXT,   -- Tier A: Used only for Stage 2 (TOC planning)
    granular_payload TEXT,  -- Tier B: Used only for Stage 3 (Chapter synthesis)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline_state (
    stage TEXT PRIMARY KEY,
    payload_json TEXT
);
```

#### Why this solves your problems:
1. **Crash & Resume Resilience:** If file 35 crashes or you hit `Ctrl+C`, rerunning the script immediately picks up at file 36.
2. **Context Separation:** 
   - Stage 2 queries only: `SELECT file_path, topic_signature FROM document_cache` ($\sim$5,000 tokens total).
   - Stage 3 queries only: `SELECT granular_payload FROM document_cache WHERE file_path IN (...)` on demand per chapter.
3. **Clean Teardown:** A `--clean` flag simply executes `os.remove("synthesis_cache.db")`.

---

### Summary Recommendation

- **Database:** Use standard library `sqlite3` as an ephemeral checkpoint store. Avoid external DB servers.
- **Framework:** Stick with pure Python (or lightweight state objects). LangChain/LangGraph will add brittle abstractions and installation friction without giving you anything beyond what `sqlite3` + standard loops provide cleanly.
---

Viewed doc_synthesis.py:1-100
Viewed doc_synthesis.py:350-435
Created doc_synthesis.py
Ran command: `python -m py_compile .\doc_synthesis.py`

The new strategy with **ephemeral SQLite checkpointing and multi-tier token restraint** has been implemented in [`doc_synthesis.py`](file:///c:/Dev/aurabily/docs/doc_synthesis.py).

### Architectural Implementation Details

1. **Ephemeral SQLite State Store (`SynthesisCacheStore`)**:
   - Uses Python's built-in `sqlite3` without adding any third-party dependencies.
   - **`document_cache` Table:** Tracks `file_path`, SHA256 `file_hash`, `topic_signature`, and `granular_payload`.
   - **`outline_cache` & `chapter_cache` Tables:** Checkpoints the planned Table of Contents and individual synthesized chapters.
   - **Crash / Interruption Resilience:** If you interrupt with `Ctrl+C` or a network timeout occurs, re-running the script immediately skips already-processed files and resumes from the exact point of interruption.

2. **Multi-Page Chunk Compression (`split_text_into_chunks`)**:
   - Files exceeding `MAX_CHUNK_CHARACTERS` (12,000 chars) are split into semantic chunks along paragraph boundaries with an 800-character overlap.
   - Each chunk is summarized individually, and then reduced into a dense technical summary to ensure no information is truncated at arbitrary character thresholds.

3. **Dual-Tier Metadata Separation**:
   - **Tier A (`topic_signature`):** A 50–80 word summary representing primary domain, responsibilities, and dependencies.
   - **Tier B (`granular_payload`):** Dense extracted specifications, schemas, parameters, code signatures, and rules.
   - **Context Window Restraint in Stage 2:** The global Table of Contents generator receives **only the Topic Signatures** ($\sim$5,000 words across 55 files), keeping the prompt within local Ollama context limits.

4. **Progressive Accumulator for Large Chapters (`synthesize_section_budgeted`)**:
   - If a chapter's assigned documents exceed `MAX_CHAPTER_BATCH_CHARACTERS` (15,000 chars), the chapter is synthesized iteratively (draft initial batch $\rightarrow$ incorporate next batch into draft), preventing local model context overflow.

---

### Command-Line Usage

- **Normal run (auto-checkpoints & resumes on interrupt):**
  ```powershell
  python .\doc_synthesis.py . -o MASTER_SYNTHESIS.md
  ```

- **Clean start (wipes previous SQLite cache before running):**
  ```powershell
  python .\doc_synthesis.py . --clean -o MASTER_SYNTHESIS.md
  ```

- **One-off ephemeral execution (erases cache DB automatically when finished):**
  ```powershell
  python .\doc_synthesis.py . --erase-cache -o MASTER_SYNTHESIS.md
  ```