My strongest recommendation is: **do not concatenate the 55 files directly, and do not use vector search as the primary synthesis engine**. Instead, use an **outline-first, hierarchical map-reduce / topological synthesis pipeline** with **dual-tier extraction**, **SQLite checkpointing**, and **budgeted chapter synthesis**.

In one sentence:

> Build a **global table of contents first**, assign every document to a chapter deterministically, then synthesize each chapter independently using compressed but high-detail payloads, with progressive accumulation for large chapters.

This is the best balance between:

- **Knowledge structuring**: logical pedagogical order instead of arbitrary file order.
- **Concatenation**: coherent chapters instead of raw merged text.
- **Detail retrieval**: no lost documents, no lost chunks, and optional indices for later lookup.

---

## 1. Recommended Architecture: 3-Stage Topological Synthesis

Your uploaded `doc_synthesis.py` and `knowledge-synthesis.md` already point to the right pattern. The ideal pipeline is:

```text
55 source documents
        │
        ▼
Stage 1: Dual-tier extraction
        │
        ├─ Topic Signature: 50–100 words, used for planning the outline
        └─ Granular Payload: dense technical facts, schemas, rules, parameters
        │
        ▼
Stage 2: Global outline generation
        │
        ├─ LLM sees only topic signatures
        ├─ Produces ordered chapters
        └─ Maps every source file to at least one chapter
        │
        ▼
Stage 3: Budgeted chapter synthesis
        │
        ├─ Small chapter: synthesize in one pass
        └─ Large chapter: progressive accumulation
        │
        ▼
MASTER_SYNTHESIS.md
```

This is better than naive RAG because RAG optimizes for **retrieving relevant fragments**, not for producing a **complete, ordered, non-redundant master document**.

---

## 2. Why Not Just Use FAISS, ChromaDB, BM25, or Neo4j?

For this specific task, most retrieval systems are not the primary answer.

| Technique | Good For | Good For Master Document? | Verdict |
|---|---|---:|---|
| Raw concatenation | Simple export | No | Loses structure, duplicates content, poor readability |
| BM25 / keyword search | Query lookup | No | Cannot create narrative order |
| FAISS / ChromaDB / vector search | Semantic QA retrieval | Weak | Top-K retrieval can omit important material and fragment context |
| Neo4j / knowledge graph | Long-lived enterprise knowledge graph | Possible but overkill | High setup cost for 55 documents |
| Outline-first map-reduce synthesis | Full document synthesis | Yes | Best fit |

Use vector search only if your later goal is **interactive question answering** over the corpus. For generating one coherent master document, deterministic outline-based synthesis is better.

---

## 3. Core Technique: Dual-Tier Extraction

The biggest mistake in multi-document synthesis is putting all raw content into one prompt. With 55 documents, that causes:

- Context overflow.
- Attention dilution.
- Lost-in-the-middle degradation.
- Truncation.
- Repetition.
- Weak global structure.

Instead, extract two separate representations from each file.

### Tier A: Topic Signature

This is a compact planning representation.

Example:

```text
Primary subject: Multi-tenant authentication architecture.
Key responsibilities: Tenant isolation, token validation, role mapping.
Dependencies: PostgreSQL, Redis session cache, OAuth2 provider.
```

Use this only for **Stage 2 outline generation**.

Target length:

```text
50–100 words per document
```

For 55 documents:

```text
55 × 80 words ≈ 4,400 words
```

That is small enough for outline planning.

### Tier B: Granular Payload

This is the dense technical representation.

It should preserve:

- Definitions.
- Parameters.
- Schemas.
- APIs.
- Constraints.
- Workflows.
- Rules.
- Edge cases.
- Configuration values.
- Code signatures.
- File-specific terminology.

Use this only for **Stage 3 chapter synthesis**.

Example:

```text
- Tenant isolation enforced via `tenant_id` column on all domain tables.
- JWT claims must include `tenant_id`, `role`, `exp`, `iss`.
- Token TTL: 15 minutes.
- Refresh token TTL: 30 days.
- Role mapping table: `tenant_roles(role_id, tenant_id, role_name, permissions jsonb)`.
```

This two-tier approach is the key optimization.

---

## 4. Stage 1: Better Chunking for Long Documents

Your current `doc_synthesis.py` already uses chunking:

```python
MAX_CHUNK_CHARACTERS = 12_000
CHUNK_OVERLAP_CHARACTERS = 800
```

That is a reasonable starting point, but I would refine it.

### Recommended chunking rules

For long documents:

1. Split by structural boundaries first:
   - Markdown headings: `#`, `##`, `###`
   - ReStructuredText headings
   - Code functions/classes
   - JSON/YAML top-level keys
   - CSV logical sections if applicable

2. Fall back to length-based chunking only when needed.

3. Avoid splitting:
   - Tables.
   - Code blocks.
   - JSON objects.
   - YAML lists.
   - CSV header + rows.

4. Preserve breadcrumb context in every chunk.

Example chunk header:

```text
Source: docs/authentication.md
Section: Authentication > Token Validation > Tenant Scoping
```

This helps the LLM keep provenance.

### Suggested parameters

For local models:

```text
Chunk size: 6,000–10,000 characters
Overlap: 300–800 characters
```

For larger cloud context windows:

```text
Chunk size: 10,000–15,000 characters
Overlap: 500–1,000 characters
```

Character count is okay, but token estimation is better. If you use a local model, I would measure approximate tokens rather than characters.

---

## 5. Stage 2: Generate the Table of Contents from Signatures Only

Stage 2 should not see the full granular payloads. It should see only the topic signatures.

The prompt should ask the model to act as a **Chief Information Architect**.

The output should be strict JSON:

```json
{
  "sections": [
    {
      "title": "1. Foundations and Domain Overview",
      "objective": "Introduce the problem space, terminology, and system goals.",
      "assigned_files": [
        "overview.md",
        "glossary.md"
      ]
    },
    {
      "title": "2. Core Architecture",
      "objective": "Explain major components, data flow, and runtime boundaries.",
      "assigned_files": [
        "architecture.md",
        "services.md"
      ]
    },
    {
      "title": "3. Detailed Workflows",
      "objective": "Describe operational procedures, state transitions, and integration logic.",
      "assigned_files": [
        "workflow.md",
        "integration.md"
      ]
    },
    {
      "title": "4. Configuration and Edge Cases",
      "objective": "Capture configuration constraints, failure modes, and special rules.",
      "assigned_files": [
        "config.yaml",
        "edge-cases.md"
      ]
    },
    {
      "title": "5. Reference Appendix",
      "objective": "Preserve remaining specialized material without loss.",
      "assigned_files": [
        "legacy-notes.txt"
      ]
    }
  ]
}
```

### Important rule

Every file must be assigned to at least one chapter.

Your existing code has the right safeguard:

```python
validate_and_patch_outline(...)
```

This is essential. If the model forgets files, append them to an appendix chapter automatically.

This guarantees **zero document loss**.

---

## 6. Stage 3: Budgeted Chapter Synthesis

Once the outline exists, synthesize each chapter independently.

Do not try to generate the entire master document in one LLM call.

Instead:

```text
For each chapter:
    Load assigned granular payloads
    Estimate payload size
    If small:
        synthesize in one pass
    If large:
        synthesize first batch
        then progressively integrate remaining batches
```

This is the **progressive accumulator pattern**.

### Small chapter path

If the assigned payloads are below a budget, synthesize directly.

Example budget:

```text
MAX_CHAPTER_BATCH_CHARACTERS = 15_000
```

For smaller local models, reduce this:

```text
6,000–10,000 characters
```

### Large chapter path

If a chapter has too many assigned documents:

1. Synthesize batch 1 into an initial draft.
2. Pass:
   - current draft,
   - next batch of source payloads,
   - instruction to integrate without deleting prior detail.
3. Repeat until all assigned sources are incorporated.

Example refinement instruction:

```text
You are refining an existing chapter draft.
Integrate the new source specifications completely.
Do not remove previously written technical details.
Remove duplication.
Preserve exact names, parameters, constraints, formulas, and configuration values.
```

This prevents context overflow while preserving detail.

---

## 7. Optimizing Knowledge Structuring

To make the final master document structurally strong, enforce a chapter progression like this:

```text
1. Executive Overview
2. Glossary and Core Concepts
3. System Architecture
4. Domain Models
5. Core Workflows
6. Integrations
7. Configuration
8. Edge Cases and Failure Modes
9. Security and Compliance
10. Operational Runbooks
11. Reference Appendix
12. Source Map
```

You can ask the LLM to generate this structure, but you should constrain it.

### Good outline constraints

Tell the model:

```text
Order sections pedagogically:
Foundations → Core Concepts → Architecture → Workflows → Configuration → Edge Cases → Reference.
Avoid overlapping chapters.
Every file must be assigned.
Prefer 4–10 files per chapter.
If uncertain, place specialized files in an appendix.
Output valid JSON only.
```

### Optional improvement: prerequisite graph

For even better ordering, extract lightweight relationships in Stage 1:

```json
{
  "file": "authentication.md",
  "topic_signature": "...",
  "depends_on": [
    "glossary.md",
    "user-model.md"
  ],
  "mentions": [
    "JWT",
    "tenant isolation",
    "OAuth2"
  ]
}
```

Then order chapters so prerequisite concepts appear before dependent concepts.

You do not need Neo4j for this. For 55 documents, a simple Python dictionary or `networkx` graph is enough.

---

## 8. Optimizing Concatenation

Do not concatenate raw files. Instead, synthesize with a stable document skeleton.

Recommended skeleton:

```markdown
# Master Knowledge Base Synthesis

## Table of Contents

- [1. Foundations](#1-foundations)
- [2. Core Architecture](#2-core-architecture)
- [3. Workflows](#3-workflows)
- [4. Configuration](#4-configuration)
- [5. Reference Appendix](#5-reference-appendix)

---

# 1. Foundations

...

---

# 2. Core Architecture

...
```

### Better concatenation rules

1. Use one top-level title.
2. Generate a clickable table of contents.
3. Use stable heading anchors.
4. Separate chapters with horizontal rules.
5. Add provenance markers inside chapters.
6. Merge duplicate concepts.
7. Preserve exact technical values.
8. Do not summarize away numbers, constraints, or schemas.

Example provenance line:

```markdown
> Sources: `docs/authentication.md`, `docs/authorization.md`
```

Or more granular:

```markdown
> Derived from: `docs/authentication.md` — Section: Token Validation
```

This improves trust and traceability.

---

## 9. Optimizing Detail Retrieval

There are two different retrieval problems:

### A. Retrieval during synthesis

For synthesis, the best retrieval method is deterministic assignment:

```text
file → chapter → granular payload
```

No embedding search is required.

This guarantees full coverage.

### B. Retrieval after synthesis

If users later need to find details inside the master document, add structured appendices.

High-value appendices:

```text
1. Source Map
2. Glossary
3. Parameter Index
4. Schema Index
5. Rule Index
6. Decision Log
7. Edge Case Index
8. File-to-Chapter Mapping
```

Example source map:

```markdown
| Source File | Assigned Chapter | Main Topics |
|---|---|---|
| docs/authentication.md | 2. Core Architecture | JWT, tenant isolation, OAuth2 |
| docs/schema.sql | 5. Reference Appendix | PostgreSQL tables, constraints |
```

Example parameter index:

```markdown
| Parameter | Value | Source |
|---|---:|---|
| Token TTL | 15 minutes | docs/authentication.md |
| Refresh token TTL | 30 days | docs/authentication.md |
| Max batch size | 250 | docs/worker-config.yaml |
```

This makes the final document much more useful.

---

## 10. Advanced Upgrade: Atomic Fact Ledger

If detail preservation is extremely important, add a third extraction tier:

```text
Tier A: Topic Signature
Tier B: Granular Payload
Tier C: Atomic Fact Ledger
```

The atomic fact ledger extracts discrete facts:

```json
[
  {
    "id": "FACT-0001",
    "source": "docs/authentication.md",
    "type": "constraint",
    "statement": "JWT must contain tenant_id claim.",
    "entities": ["JWT", "tenant_id"]
  },
  {
    "id": "FACT-0002",
    "source": "docs/config.yaml",
    "type": "configuration",
    "statement": "session_ttl_seconds is 900.",
    "entities": ["session", "TTL"]
  }
]
```

Then the master document can cite facts:

```markdown
All tokens must include a tenant identifier [FACT-0001].
```

This is more expensive, but it gives you:

- Better auditability.
- Better detail validation.
- Better deduplication.
- Better future retrieval.
- Easier detection of missing information.

For 55 documents, this is feasible if you cache aggressively.

---

## 11. Use SQLite as an Ephemeral State Store

Your existing SQLite cache design is correct. Keep it.

Recommended tables:

```sql
document_cache(
    file_path TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    topic_signature TEXT NOT NULL,
    granular_payload TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

outline_cache(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    outline_json TEXT NOT NULL
);

chapter_cache(
    chapter_index INTEGER PRIMARY KEY,
    chapter_title TEXT NOT NULL,
    chapter_content TEXT NOT NULL
);
```

I would add one more table for provenance and validation:

```sql
chapter_source_map(
    chapter_index INTEGER,
    file_path TEXT,
    PRIMARY KEY (chapter_index, file_path)
);
```

And possibly:

```sql
fact_ledger(
    fact_id TEXT PRIMARY KEY,
    source_path TEXT,
    fact_type TEXT,
    statement TEXT,
    entities_json TEXT
);
```

### Why SQLite is ideal

It gives you:

- Crash recovery.
- Resume after interruption.
- Avoided reprocessing unchanged files.
- Cheap inspection of intermediate outputs.
- Clean teardown with `--clean` or `--erase-cache`.
- No external database server.
- No heavy framework dependency.

For this use case, SQLite is better than ChromaDB, Postgres, MongoDB, or Neo4j.

---

## 12. Suggested Execution Budgets

For 55 documents, I would use conservative budgets.

### Stage 1

```text
Chunk size: 8,000–12,000 characters
Overlap: 500–800 characters
Topic signature: 50–100 words
Granular payload: 500–2,000 words per file, depending on density
```

### Stage 2

```text
Input: topic signatures only
Expected input size: 4,000–7,000 words
Output: JSON outline
Validation: all files assigned, JSON schema checked
```

### Stage 3

For large cloud models:

```text
Chapter source payload budget: 12,000–18,000 characters
```

For small local models:

```text
Chapter source payload budget: 5,000–9,000 characters
```

If using a model with 8K context, be much more conservative:

```text
3,000–6,000 characters per synthesis batch
```

---

## 13. Improvements I Would Make to Your Existing `doc_synthesis.py`

Your script is already close to the right design. I would improve it in these ways.

### 1. Fix supported extensions

The current set appears to contain trailing spaces:

```python
SUPPORTED_EXTENSIONS: set[str] = {
    ".txt ", ".md ", ".py ", ...
}
```

That may prevent matching. Use:

```python
SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".pdf",
    ".rst",
    ".csv",
}
```

### 2. Remove hardcoded API credentials

Do not hardcode API keys in source code. If the key was committed or shared, rotate it.

Use:

```python
API_KEY = os.getenv("OPENROUTER_API_KEY")
```

Fail early if missing.

### 3. Add retry logic

LLM calls can fail due to rate limits or network issues.

Use exponential backoff:

```text
Attempt 1: immediate
Attempt 2: after 2 seconds
Attempt 3: after 5 seconds
Attempt 4: after 10 seconds
```

### 4. Add JSON repair for outline generation

LLMs sometimes wrap JSON in prose or markdown fences.

Handle:

```text
```json
{...}
```
```

Also attempt to extract the first `{...}` block, as your code already does. If parsing fails, retry once with:

```text
Return only valid JSON. No markdown. No commentary.
```

### 5. Add chapter provenance mapping

Store which files were used for each chapter:

```python
cache_store.save_chapter_source_map(index, assigned_file_paths)
```

Then append a source map at the end of the master document.

### 6. Add token estimation instead of character budgeting

Character count is a rough proxy. If possible, estimate tokens using a tokenizer appropriate for the model.

For local Ollama models, approximate:

```text
1 token ≈ 4 characters for English text
```

But code, JSON, and YAML can differ.

### 7. Add stage-level resumability

Your cache already supports file-level and chapter-level resumability. You could also store pipeline stage state:

```sql
pipeline_state(
    stage TEXT PRIMARY KEY,
    payload_json TEXT
);
```

This allows commands like:

```bash
python doc_synthesis.py . --stage outline
python doc_synthesis.py . --stage chapters
python doc_synthesis.py . --stage assemble
```

### 8. Add validation pass

After outline generation, check:

```text
Are all files assigned?
Are any files assigned twice?
Are any chapter titles duplicated?
Are any chapters empty?
Are any assigned paths invalid?
```

After chapter synthesis, check:

```text
Is chapter content non-empty?
Does chapter mention at least some expected keywords?
Is chapter length reasonable?
```

This does not need to be perfect, but it catches obvious failures.

---

## 14. Best Prompt Strategy

### Stage 1: Granular extraction prompt

```text
You are an expert technical analyst.
Extract all crucial information from the document with high density and zero filler.

Preserve:
- core concepts
- prerequisites
- specifications
- schemas
- formulas
- workflows
- rules
- configuration values
- edge cases
- terminology
- exact names, numbers, parameters, and signatures

Do not invent information.
Do not omit technical constraints.
Output dense markdown bullet points.
```

### Stage 1: Topic signature prompt

```text
You are an information architect.
Generate a concise 50–80 word topic signature for this document.

State:
1. Primary subject/domain.
2. Key responsibilities or purpose.
3. Important prerequisites or dependencies.

Do not write conversational filler.
Output only the topic signature.
```

### Stage 2: Outline prompt

```text
You are a chief information architect.
Create a master table of contents from the provided document signatures.

Rules:
1. Every document ID must be assigned to at least one section.
2. Order sections pedagogically:
   Foundations → Core Concepts → Architecture → Workflows → Configuration → Edge Cases → Reference.
3. Avoid assigning too many documents to one chapter.
4. Use an appendix for rare or specialized material if needed.
5. Respond only with valid JSON.

JSON schema:
{
  "sections": [
    {
      "title": "1. Section Title",
      "objective": "What this chapter covers",
      "assigned_files": ["path/to/file.md"]
    }
  ]
}
```

### Stage 3: Chapter synthesis prompt

```text
You are an expert technical author.
Synthesize the assigned sources into a comprehensive chapter.

Rules:
1. Use clear subheadings.
2. Preserve all granular technical details.
3. Merge duplicate information.
4. Cross-reference related concepts.
5. Do not omit numbers, constraints, schemas, parameters, or configuration values.
6. Do not invent facts not present in the sources.
7. Write in clean markdown.
```

### Stage 3: Progressive refinement prompt

```text
You are refining an existing chapter draft.
Integrate the new source specifications without deleting previously written details.

Rules:
1. Preserve all existing technical specifics.
2. Add new details, constraints, schemas, parameters, and workflows.
3. Remove duplication.
4. Maintain coherent structure.
5. Output the complete refined chapter.
```

---

## 15. Optional Retrieval Layer After Synthesis

If you also want to query the result later, add a lightweight retrieval layer **after** the master document is generated.

Best option for keyword/exact lookup:

```text
SQLite FTS5
```

Index:

```text
final chapters
source documents
granular payloads
fact ledger
```

Example use:

```sql
SELECT *
FROM master_document_fts
WHERE master_document_fts MATCH 'tenant isolation';
```

Use vector search only if you need semantic question answering.

Recommended split:

```text
Synthesis: outline-first deterministic pipeline
Search: SQLite FTS5 or optional vector index
```

Do not let retrieval drive synthesis unless you are okay with partial coverage.

---

## 16. Final Recommended Pipeline

Here is the version I would use.

```text
Input: 55 textual documents
        │
        ▼
Normalize and extract text
        │
        ▼
Split long files into structure-aware chunks
        │
        ▼
For each file:
    Generate topic signature
    Generate granular payload
    Store in SQLite with file hash
        │
        ▼
Generate global outline from topic signatures only
        │
        ▼
Validate outline:
    all files assigned
    no invalid paths
    reasonable chapter sizes
        │
        ▼
For each chapter:
    Fetch assigned granular payloads
    If within budget:
        synthesize directly
    Else:
        synthesize batch 1
        integrate batch 2
        integrate batch 3
        ...
    Cache chapter result
        │
        ▼
Assemble MASTER_SYNTHESIS.md
        │
        ▼
Append:
    Table of contents
    Source map
    Glossary
    Parameter index
    Edge case index
        │
        ▼
Optional:
    Build SQLite FTS5 index over final output
```

---

## 17. My Best Suggestion in Practice

If I were implementing this for a folder of 55 documents, I would use:

```text
Pure Python + SQLite + outline-first map-reduce synthesis
```

I would not add:

```text
LangChain
ChromaDB
FAISS
Neo4j
Postgres
MongoDB
```

unless there was a separate long-term requirement.

I would keep the system simple, deterministic, and resumable.

The highest-value techniques are:

1. **Dual-tier extraction**
2. **Outline-first chapter planning**
3. **Deterministic file-to-chapter assignment**
4. **Progressive chapter accumulation**
5. **SQLite caching**
6. **Validation that all files are included**
7. **Appendices for retrieval and provenance**

---

## Final Verdict

The best technique is:

> **Outline-first hierarchical synthesis with dual-tier extraction and budgeted progressive chapter generation.**

This gives you:

- Better structure than raw concatenation.
- Better coverage than RAG.
- Better detail preservation than simple summarization.
- Better resumability than in-memory processing.
- Lower complexity than a graph database.
- Better final retrieval through indices and source maps.

For your specific case, the ideal target is not merely a concatenated file, but a **synthesized master reference document** with:

```text
logical chapters
dense technical content
source provenance
complete file coverage
searchable appendices
resumable processing
```

That is the strongest architecture for producing a single high-quality master document from 55 source documents.

---

The best approach for your case is **not** classic RAG with vector search.  
For 55 textual documents that must become **one coherent master document**, the strongest technique is:

> **Outline-first hierarchical map-reduce synthesis**  
> also called **3-stage topological synthesis**:
> 1. extract dense per-document knowledge,  
> 2. generate a global table of contents / ordering,  
> 3. synthesize each chapter independently with budgeted context.

Your current `doc_synthesis.py` and `knowledge-synthesis.md` are already aligned with this pattern, and that is the right direction.

---

# 1. Recommended technique: 3-Stage Topological Synthesis

## High-level pipeline

```text
55 documents
   │
   ▼
Stage 1: Dual-tier extraction
   - Topic Signature: short description for planning
   - Granular Payload: dense technical details for synthesis
   - Optional: entities, headings, source anchors
   │
   ▼
Stage 2: Global outline generation
   - Use only Topic Signatures
   - LLM creates a logical Table of Contents
   - Every file is mapped to at least one chapter
   - Validate that nothing is missing
   │
   ▼
Stage 3: Budgeted chapter synthesis
   - For each chapter:
       - collect assigned Granular Payloads
       - if small: synthesize in one pass
       - if large: synthesize progressively
   - Append chapters into MASTER_SYNTHESIS.md
   │
   ▼
Optional Stage 4: Post-processing
   - TOC
   - glossary
   - cross-reference index
   - source appendix
   - search index
```

This solves the three main problems:

| Problem | Solution |
|---|---|
| Detail loss | Every file is extracted and explicitly assigned to a chapter |
| Bad ordering | LLM creates a global outline before writing chapters |
| Context overflow | Each chapter is synthesized separately with token/character budgeting |
| Crash/restart | SQLite cache stores intermediate results |
| Repetition | Cross-source synthesis prompt deduplicates overlapping content |
| Retrieval inside final doc | Add TOC, anchors, glossary, appendix, optional FTS index |

---

# 2. Why this is better than vector DB RAG for your goal

For a single master synthesis document, tools like FAISS, ChromaDB, BM25, or Neo4j are usually not the best primary solution.

| Approach | Good for | Fit for your task |
|---|---|---|
| Vector DB RAG | answering specific questions from retrieved chunks | Poor for full-document synthesis |
| BM25 / FTS5 | keyword search | Not enough for narrative ordering |
| Neo4j knowledge graph | complex entity relationships | Overkill for 55 docs unless you need a persistent enterprise knowledge graph |
| Outline-first map-reduce | transforming many documents into one structured master document | Best fit |
| Pure Python + SQLite checkpointing | resumable batch synthesis | Excellent |

Vector search is excellent for **retrieval**, but your problem is **global restructuring and synthesis**.

You need:

- complete coverage,
- logical progression,
- chapter-level organization,
- preservation of technical detail,
- no missing files,
- no arbitrary chunk fragmentation.

That is an **editorial/planning problem**, not just a retrieval problem.

---

# 3. The ideal structure for the master document

For 55 documents, I would structure the final output like this:

```markdown
# Master Knowledge Base Synthesis

## Table of Contents
- [1. Executive Overview](#1-executive-overview)
- [2. Foundations and Core Concepts](#2-foundations-and-core-concepts)
- [3. Architecture and System Design](#3-architecture-and-system-design)
- [4. Workflows and Implementation Details](#4-workflows-and-implementation-details)
- [5. Configuration, Schemas, and Reference Material](#5-configuration-schemas-and-reference-material)
- [6. Edge Cases, Constraints, and Failure Modes](#6-edge-cases-constraints-and-failure-modes)
- [7. Glossary](#7-glossary)
- [8. Source Appendix](#8-source-appendix)

---

# 1. Executive Overview
...

# 2. Foundations and Core Concepts
...

# 3. Architecture and System Design
...

# 4. Workflows and Implementation Details
...

# 5. Configuration, Schemas, and Reference Material
...

# 6. Edge Cases, Constraints, and Failure Modes
...

# 7. Glossary
...

# 8. Source Appendix
...
```

The most important addition is the **Source Appendix**.

Example:

```markdown
# 8. Source Appendix

| Source File | Mapped Chapter | Topic Signature |
|---|---|---|
| docs/intro.md | 1. Executive Overview | Project purpose, scope, main concepts |
| docs/schema.md | 5. Configuration, Schemas | Database schema, tables, constraints |
| src/main.py | 4. Workflows | Entry point, pipeline execution, CLI handling |
```

This gives you traceability and improves detail retrieval later.

---

# 4. Stage 1 optimization: extract two tiers per document

Your current implementation already does this:

- `topic_signature`
- `granular_payload`

That is correct.

But for better quality, I would extend Stage 1 into a more structured extraction.

## Recommended Stage 1 output per file

Instead of only two text fields, extract something like:

```json
{
  "file_path": "docs/architecture.md",
  "file_hash": "...",
  "topic_signature": "Architecture document describing multi-tenant worker orchestration and GPU tunnel routing.",
  "granular_payload": "Detailed technical content...",
  "entities": [
    "worker node",
    "GPU tunnel",
    "tenant isolation",
    "routing table"
  ],
  "headings": [
    "Overview",
    "Tenant Model",
    "Worker Lifecycle"
  ],
  "document_type": "architecture",
  "dependencies": [
    "docs/overview.md",
    "docs/networking.md"
  ],
  "risks_or_edge_cases": [
    "Tenant isolation failure",
    "GPU tunnel timeout"
  ]
}
```

This improves:

- outline generation,
- chapter assignment,
- glossary generation,
- cross-referencing,
- duplicate detection.

## Chunking strategy

Your current logic uses:

```python
MAX_CHUNK_CHARACTERS = 12_000
CHUNK_OVERLAP_CHARACTERS = 800
```

That is reasonable.

But for better semantic preservation, use **heading-aware chunking** first:

```text
1. Try splitting by Markdown headings:
   #, ##, ###

2. If a section is still too long:
   split by paragraphs with overlap.

3. For code files:
   split by class/function boundaries if possible.

4. For JSON/YAML:
   preserve schema structure.

5. For CSV:
   preserve header + sample rows + inferred schema.
```

Better chunking means better detail retention.

---

# 5. Stage 2 optimization: generate a lean global outline

Stage 2 should only use the **Topic Signatures**, not the full granular payloads.

Why?

Because if you have 55 documents:

```text
55 files × 80 words ≈ 4,400 words
```

That is manageable.

But:

```text
55 files × 2,000 words of detailed payload ≈ 110,000 words
```

That can overflow local models or degrade quality.

So Stage 2 should receive only compact signatures.

## Recommended Stage 2 prompt

```text
You are a Chief Information Architect.

You are given 55 source documents and their short topic signatures.

Create a master table of contents for a single authoritative knowledge document.

Rules:
1. Every source file must be assigned to at least one section.
2. Sections must follow a pedagogical and reference-friendly order:
   Overview -> Foundations -> Core Concepts -> Architecture ->
   Workflows -> Configuration -> Edge Cases -> Appendix.
3. Prefer balanced chapters.
4. Avoid assigning too many files to one chapter.
5. If uncertain, place the file in a reference appendix.
6. Return only valid JSON.

Output schema:
{
  "sections": [
    {
      "title": "1. Executive Overview",
      "objective": "...",
      "assigned_files": ["docs/overview.md"]
    }
  ]
}
```

## Important validation

After the LLM returns the outline, always validate:

```python
all_files = {record["relative_path"] for record in file_records}
assigned_files = set()

for section in sections:
    assigned_files.update(section.get("assigned_files", []))

missing_files = all_files - assigned_files
```

If any files are missing, append them to an appendix.

This is critical for **zero detail loss**.

Your current `validate_and_patch_outline()` function already does this, which is excellent.

---

# 6. Stage 3 optimization: budgeted chapter synthesis

Your current code already uses:

```python
MAX_CHAPTER_BATCH_CHARACTERS = 15_000
```

That is a good safety budget.

The key idea is:

> Do not feed an entire chapter’s worth of dense source summaries into one prompt if it may exceed context or attention quality.

Instead, use two paths.

---

## Path A: Small chapter

If:

```text
total granular payload <= 15,000 characters
```

or:

```text
assigned files <= 3
```

then synthesize directly.

Prompt:

```text
You are an expert technical author.

Write a comprehensive chapter using the assigned source documents.

Requirements:
1. Preserve all concrete details:
   - names
   - numbers
   - parameters
   - schemas
   - rules
   - constraints
   - configurations
2. Remove duplication across sources.
3. Use clear subheadings.
4. Use tables where useful.
5. Do not summarize vaguely.
6. Write a complete, detailed chapter.
```

---

## Path B: Large chapter

If the chapter is too large, use **progressive accumulation**.

### Step 1

Synthesize first batch:

```text
Write the initial version of this chapter using these sources.
```

### Step 2

For the next batch:

```text
You are refining an existing chapter.

Integrate the new source material into the current draft.

Requirements:
1. Keep all existing important details.
2. Add new details from the new sources.
3. Remove duplication.
4. Improve coherence.
5. Do not reduce technical depth.
```

This is exactly what your `synthesize_section_budgeted()` function is doing.

That is the right approach.

---

# 7. Best enhancement: add a “chapter contract”

Before writing each chapter, generate a small **chapter contract**.

Example:

```json
{
  "chapter_title": "3. Architecture and System Design",
  "objective": "Explain the overall system structure, components, and communication flow.",
  "must_cover": [
    "worker nodes",
    "GPU tunnels",
    "tenant isolation",
    "request routing"
  ],
  "assigned_files": [
    "docs/architecture.md",
    "docs/networking.md",
    "docs/workers.md"
  ]
}
```

Then pass this contract to the synthesis prompt:

```text
Chapter Title: 3. Architecture and System Design
Chapter Objective: Explain the overall system structure, components, and communication flow.

The chapter must cover:
- worker nodes
- GPU tunnels
- tenant isolation
- request routing
```

This improves focus and reduces missing details.

---

# 8. Best enhancement: preserve provenance with source citations

For detail retrieval, every important statement should be traceable.

You can ask the LLM to add lightweight source references:

```markdown
The worker lifecycle includes initialization, heartbeat monitoring, and graceful shutdown [docs/workers.md].
```

Or:

```markdown
The routing table uses tenant_id as the primary partition key [docs/schema.md].
```

This makes the final master document much more useful.

However, with local small models, citation quality can be unstable.  
So a safer approach is to append a **Sources Used** block at the end of each chapter.

Example:

```markdown
## Sources Used in This Chapter

- docs/architecture.md
- docs/networking.md
- docs/workers.md
```

This is deterministic and reliable.

---

# 9. Best enhancement: generate a glossary and entity index

After all chapters are generated, run a final pass:

```text
Read the chapter titles and section summaries.
Generate a glossary of important domain terms.
```

Or better, use the entities extracted in Stage 1.

Example:

```markdown
# Glossary

## Tenant
A logical isolation boundary for resources, workers, and routing.

## GPU Tunnel
A communication channel used to route workloads to GPU workers.

## Worker Node
A compute node responsible for executing assigned tasks.
```

This significantly improves retrieval inside the master document.

---

# 10. Best enhancement: generate a companion index

If you want better “detail retrieval” after the master document is created, generate sidecar files:

```text
MASTER_SYNTHESIS.md
MASTER_INDEX.json
GLOSSARY.md
SOURCE_APPENDIX.md
```

## Example `MASTER_INDEX.json`

```json
{
  "sections": [
    {
      "title": "3. Architecture and System Design",
      "anchor": "3-architecture-and-system-design",
      "assigned_files": [
        "docs/architecture.md",
        "docs/networking.md"
      ],
      "entities": [
        "worker node",
        "GPU tunnel",
        "tenant isolation"
      ]
    }
  ]
}
```

Then you can search the index without using a vector DB.

If you want local search, SQLite FTS5 is a great lightweight option:

```sql
CREATE VIRTUAL TABLE master_doc_search USING fts5(
    section_title,
    section_content,
    source_files
);
```

This gives you keyword retrieval inside the final document.

Important distinction:

> Use LLM outline synthesis to **create** the master document.  
> Use FTS5/vector search only to **query** the final document later.

---

# 11. Suggested final architecture

For your 55-document folder, I would use this architecture:

```text
Input Folder
   │
   ▼
File Discovery
   - .md, .txt, .py, .json, .yaml, .csv, .pdf, .rst
   - compute SHA256 hash
   │
   ▼
Stage 1: Extraction
   - heading-aware chunking
   - extract topic_signature
   - extract granular_payload
   - extract entities/headings/document_type
   - store in SQLite
   │
   ▼
Stage 2: Outline Planning
   - use only topic_signatures
   - generate JSON outline
   - validate every file is mapped
   - add missing files to appendix
   - optionally balance chapters
   │
   ▼
Stage 3: Chapter Synthesis
   - load assigned granular payloads
   - if under budget: one-pass synthesis
   - if over budget: progressive accumulation
   - store chapter in SQLite cache
   │
   ▼
Stage 4: Final Assembly
   - generate TOC
   - assemble chapters
   - add glossary
   - add source appendix
   - add master index
   │
   ▼
Output
   - MASTER_SYNTHESIS.md
   - MASTER_INDEX.json
   - GLOSSARY.md
   - SOURCE_APPENDIX.md
```

---

# 12. Concrete improvements to your current `doc_synthesis.py`

Your script already implements the right core architecture.  
But I would improve these areas.

---

## 12.1 Remove hardcoded API key

Your current file contains:

```python
OPENROUTER_API_KEY: str = "sk-or-v1-..."
```

That is a security risk.

Use only environment variables:

```python
API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
```

And if missing:

```text
Error: OPENROUTER_API_KEY environment variable is not configured.
```

If the key has already been committed or shared, rotate it.

---

## 12.2 Fix supported extensions

Your current code appears to have extensions with spaces:

```python
SUPPORTED_EXTENSIONS: set[str] = {
    ".txt ", ".md ", ".py ", ...
}
```

That may prevent matching files.

Use:

```python
SUPPORTED_EXTENSIONS: set[str] = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".pdf",
    ".rst",
    ".csv",
}
```

---

## 12.3 Improve chunking

Current chunking is paragraph-based:

```python
split_text_into_chunks()
```

Improve it with heading awareness:

```python
def split_markdown_by_headings(text: str) -> List[str]:
    ...
```

Suggested logic:

```text
If file is Markdown or RST:
    split by headings first.
Else:
    split by paragraphs.
If any chunk > MAX_CHUNK_CHARACTERS:
    split further with overlap.
```

This preserves semantic boundaries better.

---

## 12.4 Add structured Stage 1 extraction

Instead of only:

```text
topic_signature
granular_payload
```

extract:

```text
topic_signature
granular_payload
entities
document_type
headings
dependencies
key_sections
```

This improves outline quality.

---

## 12.5 Add outline balancing

A common LLM mistake is putting too many files into one chapter.

Add a rule:

```text
Prefer no more than 6–8 files per chapter.
If more files are assigned, split the section.
```

You can also validate programmatically:

```python
MAX_FILES_PER_SECTION = 8

for section in sections:
    if len(section["assigned_files"]) > MAX_FILES_PER_SECTION:
        split_section(section)
```

---

## 12.6 Add retry logic

LLM calls can fail due to network issues or rate limits.

Add simple retry with backoff:

```python
import time

def call_llm_with_retry(system_prompt, user_content, retries=3):
    for attempt in range(retries):
        try:
            return call_llm(system_prompt, user_content)
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
```

This improves reliability.

---

## 12.7 Add JSON mode or stricter JSON parsing

Stage 2 returns JSON.  
If your model supports structured output, use it.

If not, keep your regex fallback:

```python
json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
```

But also add:

- JSON schema validation,
- missing-file validation,
- duplicate-file validation,
- invalid-path validation.

---

## 12.8 Add chapter quality checks

After synthesizing a chapter, check:

```text
- Is it too short?
- Does it mention assigned source files?
- Does it contain headings?
- Does it include expected entities?
- Is it suspiciously generic?
```

If quality is low, regenerate with a stronger prompt:

```text
The previous draft was too generic.
Rewrite with more concrete detail from the sources.
```

---

# 13. Best prompt design for detail preservation

The biggest risk with LLM synthesis is that it “smooths over” details.

Use prompts that explicitly forbid vague summarization.

## Good Stage 3 system prompt

```text
You are an expert Technical Author and Principal Knowledge Engineer.

Your task is to synthesize assigned source documents into one detailed chapter.

Requirements:
1. Preserve all concrete technical details:
   - names
   - numbers
   - parameters
   - schemas
   - formulas
   - constraints
   - configuration options
   - API signatures
   - rules
   - edge cases
2. Do not replace specifics with vague phrases like:
   - "various options"
   - "several configurations"
   - "appropriate values"
3. Remove duplication, but do not delete unique facts.
4. Cross-reference related ideas from different sources.
5. Use clear subheadings.
6. Use tables for structured comparisons.
7. Use numbered steps for workflows.
8. If sources conflict, preserve both interpretations and label the conflict.
9. Write for a technical reader who needs implementation-level understanding.
```

This is stronger than a generic “summarize” prompt.

---

# 14. If detail retrieval is the priority, add a “fact ledger”

This is a powerful advanced idea.

During Stage 1, extract atomic facts:

```json
[
  {
    "fact": "The worker heartbeat interval is 30 seconds.",
    "source": "docs/workers.md",
    "type": "configuration"
  },
  {
    "fact": "Tenant isolation is enforced using routing metadata.",
    "source": "docs/architecture.md",
    "type": "architecture"
  }
]
```

Then during Stage 3, the chapter synthesis can use the fact ledger to avoid losing details.

This gives you stronger traceability:

```markdown
| Fact | Source |
|---|---|
| Worker heartbeat interval is 30 seconds | docs/workers.md |
| Tenant isolation uses routing metadata | docs/architecture.md |
```

This is especially useful if the final master document will be used for audits, onboarding, or downstream RAG.

---

# 15. Should you use LangChain or LangGraph?

For this specific task, I would avoid heavy frameworks.

| Tool | Recommendation |
|---|---|
| LangChain | Not necessary; adds abstraction and debugging overhead |
| LangGraph | Good for complex stateful agent graphs, but overkill here |
| Pure Python + SQLite | Best for this pipeline |
| Vector DB | Not needed for synthesis; optional for later retrieval |
| Neo4j | Overkill unless building a persistent knowledge graph |

Your current pure Python + SQLite approach is appropriate.

---

# 16. Should you use a vector database at all?

Only optionally, and **after** synthesis.

For example:

1. Generate `MASTER_SYNTHESIS.md`.
2. Split the final master document into sections.
3. Embed those sections.
4. Store embeddings in FAISS/ChromaDB.
5. Use that for later question answering.

But do **not** use vector search as the main way to build the master document.

Why?

Because vector search does not guarantee:

- full coverage,
- logical ordering,
- chapter progression,
- no duplication,
- no missing source files.

So:

> Use topological synthesis for document creation.  
> Use vector search for document querying.

---

# 17. Recommended final deliverables

Instead of only one file, produce:

```text
MASTER_SYNTHESIS.md        # main document
MASTER_INDEX.json          # machine-readable section/entity index
SOURCE_APPENDIX.md         # source mapping and traceability
GLOSSARY.md                # term definitions
synthesis_cache.db         # temporary cache, can be erased
```

This gives you both human-readable and machine-readable knowledge.

---

# 18. Best practical workflow for your 55 documents

I would run the pipeline like this:

```bash
python doc_synthesis.py . --clean -o MASTER_SYNTHESIS.md
```

But I would also generate:

```bash
MASTER_INDEX.json
SOURCE_APPENDIX.md
GLOSSARY.md
```

If the run is interrupted, rerun without `--clean`:

```bash
python doc_synthesis.py . -o MASTER_SYNTHESIS.md
```

It should resume from SQLite cache.

When fully finished and verified:

```bash
python doc_synthesis.py . --erase-cache -o MASTER_SYNTHESIS.md
```

---

# 19. My strongest recommendation

If I had to summarize the best technique in one sentence:

> Use a **resumable, SQLite-backed, outline-first map-reduce pipeline** with **dual-tier extraction**, **global TOC planning**, and **budgeted progressive chapter synthesis**, then add a **source appendix, glossary, and index** for retrieval.

That is the most reliable way to convert 55 documents into one master document without losing detail.

---

# 20. Suggested upgraded version of your pipeline

Your current pipeline:

```text
Stage 1: Extract topic_signature + granular_payload
Stage 2: Generate outline
Stage 3: Synthesize chapters
```

Upgrade it to:

```text
Stage 0: Inventory and normalize files
Stage 1: Extract dual-tier metadata + entities + headings
Stage 2: Generate and validate balanced outline
Stage 3: Synthesize chapters with budget and provenance
Stage 4: Generate glossary, source appendix, and index
Stage 5: Optional FTS5/vector index for later retrieval
```

This gives you the best balance of:

- detail preservation,
- logical structure,
- context safety,
- crash resilience,
- retrieval quality,
- implementation simplicity.

---

# Final answer

For your use case, the best technique is:

> **3-Stage Topological Synthesis / Outline-first Hierarchical Map-Reduce with SQLite checkpointing.**

Do not make vector search the core of the solution.  
Use it only later if you need to query the final master document.

Your current `doc_synthesis.py` is already close to the right architecture.  
The biggest improvements would be:

1. heading-aware chunking,
2. structured entity extraction,
3. outline balancing,
4. provenance/source citations,
5. glossary and source appendix,
6. companion JSON/FTS index,
7. retry logic,
8. removal of the hardcoded API key.

---

Yes — you can accelerate ingestion, especially **Stage 1: Dual-Tier Extraction**, by using a **bounded worker pool**.

But the important detail is:

> Use a **bounded concurrency pool**, not unlimited threads.  
> For LLM ingestion, the bottleneck is usually API rate limits, local GPU/CPU inference capacity, SQLite writes, and memory — not Python’s GIL.

For your existing `doc_synthesis.py`, the easiest and safest acceleration method is:

> **`ThreadPoolExecutor` + semaphore-limited LLM calls + SQLite WAL mode + thread-safe cache writes.**

If by “event pool” you mean an asynchronous event loop, then yes, `asyncio` can also work, but it requires converting the OpenAI client to `AsyncOpenAI`. For your current synchronous code, threads are the lower-risk improvement.

---

# 1. What can be parallelized?

Your pipeline has three main stages:

```text
Stage 1: Extract topic_signature + granular_payload from each file
Stage 2: Generate global outline from all topic signatures
Stage 3: Synthesize chapters from assigned granular payloads
```

Parallelization potential:

| Stage | Can parallelize? | Recommendation |
|---|---:|---|
| Stage 1 file ingestion | Yes | Best place to parallelize |
| Stage 1 chunk summaries inside large files | Yes, carefully | Useful for long documents |
| Stage 2 outline generation | No | Single global planning call |
| Stage 3 chapter synthesis | Partially | Chapters are independent, but rate limits and style consistency matter |
| Final assembly | No | Simple sequential write |

The biggest win is parallelizing Stage 1.

---

# 2. Recommended concurrency model

Use this pattern:

```text
File scanner
   │
   ▼
Bounded work queue
   │
   ▼
N ingestion workers
   │
   ├─ read file
   ├─ compute hash
   ├─ check SQLite cache
   ├─ call LLM if needed
   └─ write cache
   │
   ▼
Collector
   │
   ▼
Sorted extracted_records
```

For your current code, implement it with:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
```

Why threads?

Your LLM calls are mostly **I/O-bound**:

- HTTP requests to OpenRouter,
- HTTP requests to Ollama,
- disk reads,
- SQLite writes.

Python threads are fine for I/O-bound workloads. The GIL is not the main problem here.

---

# 3. Recommended worker counts

Do not use 55 threads for 55 files.

Use bounded concurrency.

Suggested defaults:

```python
CLOUD_MAX_WORKERS = max(1, int(os.getenv("SYNTHESIS_CLOUD_WORKERS", "4")))
LOCAL_MAX_WORKERS = max(1, int(os.getenv("SYNTHESIS_LOCAL_WORKERS", "1")))
```

Recommended values:

| Backend | Suggested workers |
|---|---:|
| OpenRouter paid/fast model | 4–8 |
| OpenRouter free model | 1–3 |
| Local Ollama on GPU | 1–2 |
| Local Ollama on CPU only | 1 |
| Heavy PDF corpus | 2–4 for extraction, still bounded LLM calls |

For local Ollama, parallel requests often do not help much because the local model can usually only infer efficiently with limited parallelism. Too many concurrent requests can increase VRAM pressure and queueing latency.

---

# 4. Important safety changes before parallelizing

Your current script has a few global mutable states:

```python
USE_OLLAMA_ONLY: bool = False
ollama_client: Optional[OpenAI] = None
```

With threads, these need protection.

Also, SQLite should be configured for better concurrency.

---

## 4.1 Add thread-safe fallback state

Replace:

```python
USE_OLLAMA_ONLY: bool = False
```

with something safer:

```python
USE_OLLAMA_ONLY: bool = False
FALLBACK_EVENT = threading.Event()
OLLAMA_CLIENT_LOCK = threading.Lock()
```

Then treat fallback as:

```python
if FALLBACK_EVENT.is_set() or USE_OLLAMA_ONLY:
    # use Ollama
```

When OpenRouter fails:

```python
FALLBACK_EVENT.set()
```

This avoids race conditions between threads.

---

## 4.2 Add semaphores for LLM calls

Add:

```python
CLOUD_MAX_WORKERS = max(1, int(os.getenv("SYNTHESIS_CLOUD_WORKERS", "4")))
LOCAL_MAX_WORKERS = max(1, int(os.getenv("SYNTHESIS_LOCAL_WORKERS", "1")))

CLOUD_SEMAPHORE = threading.BoundedSemaphore(CLOUD_MAX_WORKERS)
LOCAL_SEMAPHORE = threading.BoundedSemaphore(LOCAL_MAX_WORKERS)
```

Then protect LLM calls:

```python
def call_llm(
    system_prompt: str,
    user_content: str,
    model_identifier: str = MODEL_NAME
) -> str:
    if FALLBACK_EVENT.is_set() or USE_OLLAMA_ONLY:
        with LOCAL_SEMAPHORE:
            return call_ollama(system_prompt, user_content)

    with CLOUD_SEMAPHORE:
        try:
            completion = client.chat.completions.create(
                model=model_identifier,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=DEFAULT_TEMPERATURE,
            )
            return completion.choices[0].message.content or ""
        except Exception as api_exception:
            logger.warning("\n  [Error] OpenRouter call failed: %s", api_exception)
            logger.info("  [Fallback] Switching to local Ollama for remaining steps...")
            FALLBACK_EVENT.set()

            with LOCAL_SEMAPHORE:
                return call_ollama(system_prompt, user_content)
```

This prevents 55 simultaneous LLM requests from flooding OpenRouter or Ollama.

---

## 4.3 Make Ollama client initialization thread-safe

Your current `call_ollama()` creates `ollama_client` globally.

Protect it:

```python
def call_ollama(system_prompt: str, user_content: str) -> str:
    global ollama_client

    selected_model = get_ollama_model()
    if not selected_model:
        raise RuntimeError(
            "No Ollama models available for fallback. Ensure Ollama is running and has models pulled."
        )

    with OLLAMA_CLIENT_LOCK:
        if ollama_client is None:
            ollama_client = OpenAI(
                base_url=OLLAMA_BASE_URL,
                api_key=OPENROUTER_FALLBACK_API_KEY,
            )

    logger.info("  [Fallback] Using Ollama model: %s", selected_model)

    completion = ollama_client.chat.completions.create(
        model=selected_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=DEFAULT_TEMPERATURE,
    )

    return completion.choices[0].message.content or ""
```

---

# 5. Make SQLite safer for parallel writes

Your `SynthesisCacheStore` creates a new connection each time, which is good. But for parallel workers, enable WAL mode and timeouts.

Update `_get_connection()`:

```python
def _get_connection(self) -> sqlite3.Connection:
    """Create a new database connection with safer concurrency settings."""
    connection = sqlite3.connect(self.database_path, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA synchronous=NORMAL;")
    connection.execute("PRAGMA busy_timeout=30000;")
    return connection
```

Also add a write lock in `__init__`:

```python
def __init__(self, database_path: str = DEFAULT_CACHE_DB_PATH) -> None:
    self.database_path: str = database_path
    self._write_lock = threading.RLock()
    self._initialize_schema()
```

Then wrap write operations with the lock.

Example:

```python
def save_document_cache(
    self,
    file_path: str,
    file_hash: str,
    topic_signature: str,
    granular_payload: str,
) -> None:
    with self._write_lock:
        with self._get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO document_cache (
                    file_path,
                    file_hash,
                    topic_signature,
                    granular_payload
                )
                VALUES (?, ?, ?, ?);
                """,
                (file_path, file_hash, topic_signature, granular_payload),
            )
            connection.commit()
```

Do the same for:

```python
save_outline_cache()
save_chapter_cache()
clear()
```

This reduces the chance of:

```text
sqlite3.OperationalError: database is locked
```

---

# 6. Parallelize Stage 1 ingestion

Create a dedicated function for processing one file.

```python
def ingest_single_file(
    file_path: Path,
    base_dir: Path,
    cache_store: SynthesisCacheStore,
) -> Optional[Dict[str, Any]]:
    """Process one source file in a worker thread."""
    relative_path_str = str(file_path.relative_to(base_dir))

    try:
        file_text = extract_file_text(file_path)

        if not file_text:
            return None

        file_hash = SynthesisCacheStore.calculate_hash(file_text)
        cached_result = cache_store.get_document_cache(relative_path_str, file_hash)

        if cached_result:
            logger.info("(Cached) %s", relative_path_str)
            topic_sig, granular_load = cached_result
        else:
            logger.info("Processing: %s", relative_path_str)
            topic_sig, granular_load = extract_dual_tier_summary(
                relative_path_str,
                file_text,
            )
            cache_store.save_document_cache(
                relative_path_str,
                file_hash,
                topic_sig,
                granular_load,
            )

        return {
            "relative_path": relative_path_str,
            "filename": file_path.name,
            "topic_signature": topic_sig,
            "granular_payload": granular_load,
        }

    except Exception as ingestion_error:
        logger.warning(
            "Failed to ingest %s: %s",
            relative_path_str,
            ingestion_error,
        )
        return None
```

Then replace the sequential Stage 1 loop with a thread pool.

Current sequential version:

```python
for index, file_path in enumerate(candidate_files, 1):
    ...
```

Replace with:

```python
extracted_records: List[Dict[str, Any]] = []

max_ingestion_workers = CLOUD_MAX_WORKERS

logger.info(
    "Starting parallel ingestion with %d workers...",
    max_ingestion_workers,
)

with ThreadPoolExecutor(
    max_workers=max_ingestion_workers,
    thread_name_prefix="ingest",
) as executor:

    future_to_file = {
        executor.submit(
            ingest_single_file,
            file_path,
            base_dir,
            cache_store,
        ): file_path
        for file_path in candidate_files
    }

    for future in as_completed(future_to_file):
        file_path = future_to_file[future]

        try:
            record = future.result()
            if record:
                extracted_records.append(record)
        except Exception as worker_error:
            logger.warning(
                "Worker failed for %s: %s",
                file_path,
                worker_error,
            )

extracted_records.sort(key=lambda record: record["relative_path"])
```

Sorting is important because `as_completed()` returns results in completion order, not file order.

Sorting gives you deterministic Stage 2 input:

```python
extracted_records.sort(key=lambda record: record["relative_path"])
```

---

# 7. Optional: parallelize chunk summaries inside large files

Your current `extract_dual_tier_summary()` processes chunks sequentially:

```python
for chunk_idx, chunk_text in enumerate(text_chunks, 1):
    chunk_summary = call_llm(chunk_prompt, chunk_text)
```

For large documents, this can also be parallelized.

Example:

```python
from concurrent.futures import ThreadPoolExecutor

def summarize_chunk(chunk_args: Tuple[int, str]) -> str:
    chunk_idx, chunk_text = chunk_args

    chunk_prompt = (
        f"You are analyzing segment {chunk_idx}/{len(text_chunks)} of document '{file_name}'. "
        "Extract all factual details, schemas, parameters, code signatures, and rules in dense bullet points."
    )

    return call_llm(chunk_prompt, chunk_text)


if len(text_chunks) == 1:
    ...
else:
    logger.info(
        "  (Document exceeds threshold; processing %d semantic chunks)",
        len(text_chunks),
    )

    max_chunk_workers = min(4, len(text_chunks))

    with ThreadPoolExecutor(
        max_workers=max_chunk_workers,
        thread_name_prefix="chunks",
    ) as chunk_executor:

        chunk_summaries = list(
            chunk_executor.map(
                summarize_chunk,
                enumerate(text_chunks, 1),
            )
        )

    combine_prompt = (
        "Consolidate these segmented extractions into a single dense reference payload. "
        "Eliminate redundancy between segments while retaining all granular details and formulas."
    )

    granular_payload = call_llm(
        combine_prompt,
        "\n\n".join(chunk_summaries),
    )
```

This can significantly accelerate large multi-page files.

However, because each chunk calls the LLM, the global `CLOUD_SEMAPHORE` or `LOCAL_SEMAPHORE` still controls actual concurrency.

That is good.

---

# 8. Should Stage 3 chapter synthesis be parallelized?

Yes, but carefully.

Chapters are independent:

```text
Chapter 1 uses files A, B
Chapter 2 uses files C, D
Chapter 3 uses files E, F
```

So technically, you can synthesize chapters in parallel.

But I recommend limited parallelism:

| Backend | Chapter synthesis workers |
|---|---:|
| OpenRouter paid/fast | 2–4 |
| OpenRouter free | 1–2 |
| Local Ollama | 1 |
| High-detail technical corpus | 1–2 |

Why not too many?

1. LLM rate limits.
2. Higher memory usage.
3. Less consistent writing style.
4. Progressive accumulation inside a chapter still has to be sequential.
5. Large chapter payloads can saturate context windows.

If you do parallelize chapters, collect results by chapter index:

```python
chapter_results: Dict[int, str] = {}

with ThreadPoolExecutor(max_workers=2) as chapter_executor:

    future_to_chapter = {}

    for index, section in enumerate(outline_sections, 1):
        cached_chapter = cache_store.get_chapter_cache(index)

        if cached_chapter:
            chapter_results[index] = cached_chapter
            continue

        assigned_file_paths = section.get("assigned_files", [])

        assigned_records = [
            record_lookup[path]
            for path in assigned_file_paths
            if path in record_lookup
        ]

        if not assigned_records:
            continue

        future = chapter_executor.submit(
            synthesize_section_budgeted,
            section["title"],
            section.get("objective", ""),
            assigned_records,
        )

        future_to_chapter[future] = index

    for future in as_completed(future_to_chapter):
        index = future_to_chapter[future]

        try:
            chapter_content = future.result()
            chapter_results[index] = chapter_content

            cache_store.save_chapter_cache(
                index,
                outline_sections[index - 1]["title"],
                chapter_content,
            )

        except Exception as chapter_error:
            logger.warning("Chapter %d failed: %s", index, chapter_error)
```

Then assemble in order:

```python
for index, section in enumerate(outline_sections, 1):
    section_body = chapter_results.get(index, "")
    chapter_markdown_blocks.append(
        f"\n# {section['title']}\n\n{section_body}\n\n---\n"
    )
```

For your first parallel implementation, I would only parallelize Stage 1. Once that is stable, optionally add Stage 3 parallelism with 2 workers.

---

# 9. Asyncio/event-loop alternative

If by “event pool” you mean `asyncio`, then yes, this is also possible.

The async version would look like this:

```python
import asyncio
from openai import AsyncOpenAI

async_client = AsyncOpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=API_KEY,
    default_headers={
        "HTTP-Referer": REFERER,
        "X-Title": APP_NAME,
    },
)

LLM_SEMAPHORE = asyncio.Semaphore(4)


async def call_llm_async(system_prompt: str, user_content: str) -> str:
    async with LLM_SEMAPHORE:
        completion = await async_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=DEFAULT_TEMPERATURE,
        )

        return completion.choices[0].message.content or ""
```

Then ingest files like this:

```python
async def ingest_file_async(file_path: Path, base_dir: Path):
    text = await asyncio.to_thread(extract_file_text, file_path)
    ...
```

But this requires changing your current synchronous `call_llm()` architecture.

So my recommendation is:

> If you want a quick and safe improvement, use `ThreadPoolExecutor`.  
> If you are rewriting the tool anyway, use `AsyncOpenAI` + `asyncio.Semaphore`.

---

# 10. Add retry/backoff before falling back to Ollama

Your current code falls back to Ollama on any OpenRouter failure:

```python
except Exception as api_exception:
    USE_OLLAMA_ONLY = True
    return call_ollama(...)
```

With parallel ingestion, one temporary network error or rate-limit error could force the whole run into local Ollama too early.

Better behavior:

```text
1. Retry OpenRouter 2–3 times with exponential backoff.
2. If repeated failure occurs, then fallback to Ollama.
```

Simple retry wrapper:

```python
import time

def call_llm_with_retry(
    system_prompt: str,
    user_content: str,
    model_identifier: str = MODEL_NAME,
    retries: int = 3,
) -> str:
    last_error: Optional[Exception] = None

    for attempt in range(retries):
        try:
            return call_llm(
                system_prompt,
                user_content,
                model_identifier,
            )
        except Exception as llm_error:
            last_error = llm_error
            wait_seconds = 2 ** attempt
            logger.warning(
                "LLM call failed, attempt %d/%d. Retrying in %ss. Error: %s",
                attempt + 1,
                retries,
                wait_seconds,
                llm_error,
            )
            time.sleep(wait_seconds)

    raise RuntimeError(
        f"LLM call failed after {retries} attempts"
    ) from last_error
```

For OpenRouter free models, retry/backoff is especially important.

---

# 11. Avoid unlimited parallelism

Do not do this:

```python
for file_path in candidate_files:
    threading.Thread(target=process_file, args=(file_path,)).start()
```

That can cause:

- OpenRouter 429 rate limits,
- Ollama queue saturation,
- excessive memory usage,
- unstable local inference,
- SQLite lock contention,
- difficult-to-debug failures.

Use bounded pools:

```python
ThreadPoolExecutor(max_workers=4)
```

or:

```python
asyncio.Semaphore(4)
```

or:

```python
threading.BoundedSemaphore(4)
```

---

# 12. Expected speedup

For 55 documents, if the bottleneck is OpenRouter latency, you may see something like:

| Workers | Approximate expected speedup |
|---:|---:|
| 1 | baseline |
| 2 | ~1.8x |
| 4 | ~3x–3.5x |
| 8 | depends heavily on rate limits |
| local Ollama + 4 | often not faster, sometimes slower |

The speedup is not perfectly linear because:

- API rate limits,
- token generation time,
- large files requiring multiple chunk calls,
- SQLite writes,
- fallback behavior,
- local GPU/CPU saturation.

But for I/O-bound cloud calls, bounded threading usually gives a large improvement.

---

# 13. Best practical configuration for your script

I would start with these environment variables:

```bash
export SYNTHESIS_CLOUD_WORKERS=4
export SYNTHESIS_LOCAL_WORKERS=1
```

On Windows PowerShell:

```powershell
$env:SYNTHESIS_CLOUD_WORKERS = "4"
$env:SYNTHESIS_LOCAL_WORKERS = "1"
```

Then run:

```bash
python doc_synthesis.py . --clean -o MASTER_SYNTHESIS.md
```

If you see rate-limit errors, reduce:

```bash
export SYNTHESIS_CLOUD_WORKERS=2
```

If using Ollama only, use:

```bash
export SYNTHESIS_LOCAL_WORKERS=1
```

---

# 14. My recommended implementation priority

Do it in this order:

## Phase 1: Safe parallel ingestion

Add:

- `ThreadPoolExecutor`
- `ingest_single_file()`
- SQLite WAL
- write lock
- semaphores
- sorted output records

This gives the biggest gain.

## Phase 2: Add retry/backoff

Improve reliability:

- retry OpenRouter before fallback,
- avoid switching to Ollama because of one transient error.

## Phase 3: Parallelize chunk summaries

Useful for large files:

- parallel chunk extraction,
- bounded by LLM semaphore.

## Phase 4: Optional parallel chapter synthesis

Use only after Stage 1 is stable:

- 1–2 workers for local Ollama,
- 2–4 workers for cloud,
- collect chapters by index,
- preserve chapter cache.

---

# 15. Final recommendation

Yes, you should accelerate ingestion with parallel workers.

The best technique for your current code is:

> **Bounded `ThreadPoolExecutor` ingestion + semaphore-limited LLM calls + SQLite WAL + thread-safe cache writes.**

Use `asyncio` only if you are willing to rewrite the LLM client layer using `AsyncOpenAI`.

For 55 documents, a safe starting configuration is:

```text
OpenRouter workers: 4
Local Ollama workers: 1
Chunk workers per large file: 2–4
Chapter synthesis workers: 1–2 only after Stage 1 is stable
```

That should significantly speed up ingestion while preserving:

- cache resumability,
- deterministic ordering,
- zero-detail-loss mapping,
- fallback safety,
- SQLite consistency.