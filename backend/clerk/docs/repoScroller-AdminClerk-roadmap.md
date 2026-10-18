## Short answer

**Do not build a separate standalone administrative agent product.**  
Build it as a **new “Administrative Workbench” tab inside RepoScroller**, but architect it as a **cleanly separated module** with its own tables, API routes, agent workflow, background jobs, and review/export pipeline.

That gives you the fastest path because RepoScroller already owns the hardest parts:

- document ingestion,
- deduplication,
- OCR/text extraction,
- SQLite WAL ledger,
- FTS5 lexical search,
- dense vector embeddings,
- knowledge graph,
- GraphRAG retrieval,
- multilingual taxonomy,
- FastAPI backend,
- web dashboard,
- audit trail / ALCOA+ mindset.

The missing piece is not another document indexer.  
The missing piece is a **form-aware, evidence-backed, resumable administrative workflow engine**.

So the recommended architecture is:

> **Integrated UI + separated workflow service inside RepoScroller.**

Later, if you want to sell it or serve multiple organizations, you can extract the `admin_forms` module into its own service without redesigning the product.

---

# 1. Recommended product shape

## RepoScroller today

RepoScroller is already a document intelligence platform:

```text
Repositories / NAS / Google Drive
        ↓
Crawler + SHA-256 + SimHash + FTS5 + Vector + Graph
        ↓
Document Ledger + Knowledge Graph + GraphRAG
        ↓
Chat / Interrogation / 3D Universe / Obligations
```

## New Administrative Workbench

Add a new layer above it:

```text
┌────────────────────────────────────────────────────────────────────┐
│                         RepoScroller UI                            │
│                                                                    │
│  Ledger | GraphRAG | 3D Universe | Obligations | Admin Workbench   │
└───────────────────────────────┬────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Administrative Workbench API                    │
│                                                                    │
│  /api/v1/admin/forms                                               │
│  /api/v1/admin/forms/{run_id}/analyze                              │
│  /api/v1/admin/forms/{run_id}/fields/{field_id}/research           │
│  /api/v1/admin/forms/{run_id}/fields/{field_id}/review             │
│  /api/v1/admin/forms/{run_id}/export                               │
│  /api/v1/admin/knowledge/review-queue                              │
└───────────────────────────────┬────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│                      Admin Form Orchestrator                       │
│                                                                    │
│   A1 Form Analyst                                                  │
│   A2 Answer Orchestrator                                           │
│   A3 Research & Knowledge Enrichment Agent                         │
│   Validator / Human Review Gate                                    │
└──────────────┬───────────────────────────────┬─────────────────────┘
               │                               │
               ▼                               ▼
┌──────────────────────────────┐   ┌──────────────────────────────────┐
│ Existing RepoScroller KB     │   │ New Administrative Knowledge     │
│                              │   │ Layer                            │
│ document_ledger              │   │                                  │
│ document_chunks              │   │ form_templates                   │
│ knowledge_nodes              │   │ form_fields                      │
│ knowledge_edges              │   │ form_runs                        │
│ document_entity_links        │   │ field_runs                       │
│ FTS5 / vectors / graph       │   │ knowledge_facts                  │
│ audit_log                    │   │ knowledge_answers                │
└──────────────────────────────┘   │ evidence_links                   │
                                   │ review_decisions                 │
                                   │ agent_tasks                      │
                                   │ audit_events                     │
                                   └──────────────────────────────────┘
```

The key rule:

> **Do not store the whole form workflow inside `document_ledger`.**  
> Use `document_ledger`, `document_chunks`, and the knowledge graph as evidence sources.  
> Store form state, field state, proposed answers, approvals, and reusable administrative knowledge in dedicated tables.

---

# 2. Core design principle: forms are workflows, not chatbots

A normal chatbot answers a question.

An administrative form agent must:

1. understand a form template,
2. decompose it into fields,
3. determine dependencies between fields,
4. retrieve evidence,
5. validate the answer format,
6. request missing information,
7. research unresolved fields,
8. propose reusable knowledge,
9. allow human review,
10. export a compliant result,
11. survive interruption,
12. maintain an audit trail.

So this should not be implemented as “just another chat tab”.

It should be a **field-level workflow engine**.

---

# 3. Agent model: A1 → A2 → A3

Your A1/A2/A3 concept is good, but it should be implemented as a **controlled state machine**, not three free-running agents chatting with each other.

## A1 — Form Analyst

Responsibility:

> Turn a raw form field into a typed, machine-readable contract.

Input:

- PDF form field,
- DOCX table cell,
- spreadsheet row,
- web form label,
- scanned OCR region,
- instruction text,
- surrounding context.

Output:

```json
{
  "field_id": "company_registered_address",
  "label": "Registered office address",
  "canonical_question": "What is the company's registered address?",
  "expected_type": "postal_address",
  "output_format": "structured_address",
  "jurisdiction": "CH",
  "language": "fr",
  "required": true,
  "freshness_policy": "current",
  "evidence_required": true,
  "dependencies": [],
  "validation_rules": {
    "required_components": ["street", "postal_code", "city", "country"],
    "country_allowed": ["CH", "LI", "DE", "FR", "IT"]
  }
}
```

A1 should combine:

- deterministic parsing,
- layout analysis,
- OCR/text extraction,
- LLM interpretation,
- Pydantic validation.

Important:

> The LLM may interpret the field, but ordinary code must enforce the schema.

---

## A2 — Answer Orchestrator

Responsibility:

> Decide how to answer the field using the cheapest reliable source first.

A2 is not a “chat agent”.  
A2 is a **retrieval and decision policy engine**.

Retrieval ladder:

```text
1. Approved reusable answer knowledge
2. Validated structured fact
3. Existing GraphRAG evidence
4. Targeted document research by A3
5. Ask user for clarification
6. Escalate to human review
```

A2 output:

```json
{
  "field_run_id": "fr_123",
  "status": "answer_proposed",
  "answer": {
    "type": "postal_address",
    "value": {
      "street": "Bahnhofstrasse 1",
      "postal_code": "6300",
      "city": "Zug",
      "country": "CH"
    }
  },
  "confidence": {
    "relevance": 0.94,
    "authority": 0.91,
    "freshness": 0.88,
    "agreement": 0.97,
    "validation": 1.0
  },
  "evidence": [
    {
      "source_type": "document_chunk",
      "sha256_hash": "abc...",
      "chunk_id": 98231,
      "page": 2,
      "excerpt": "The registered office of the company is in Zug.",
      "document_date": "2025-11-14"
    }
  ],
  "requires_human_review": false
}
```

A2 should never silently invent an answer.

If evidence is weak, conflicting, stale, or missing, A2 must route to:

- A3 research,
- user clarification,
- or human review.

---

## A3 — Research and Knowledge Enrichment Agent

Responsibility:

> Find missing evidence in the repository and propose reusable knowledge.

A3 is triggered when A2 cannot answer confidently from existing structured knowledge or retrieval results.

A3 workflow:

```text
Research request
    ↓
Query planning
    ↓
Hybrid search: FTS5 + vectors + graph + metadata
    ↓
Document candidate ranking
    ↓
Passage extraction
    ↓
Entity/fact extraction
    ↓
Conflict detection
    ↓
Proposed fact / proposed answer
    ↓
Validation gate
    ↓
Human approval or automatic certification if policy allows
    ↓
Knowledge base enrichment
```

Critical design rule:

> A3 must not automatically promote every LLM-generated answer into trusted knowledge.

A3 should produce a **research package**:

```json
{
  "requested_question": "What is the company's registered address?",
  "proposed_facts": [
    {
      "subject": "organization:Example SA",
      "predicate": "has_registered_address",
      "value": {
        "street": "Bahnhofstrasse 1",
        "postal_code": "6300",
        "city": "Zug",
        "country": "CH"
      },
      "valid_from": "2025-01-01",
      "status": "proposed"
    }
  ],
  "proposed_answers": [],
  "evidence": [],
  "conflicts": [],
  "uncertainties": [
    "A 2023 document lists another address; newer commercial register extract preferred."
  ]
}
```

Then a validator or human reviewer decides whether to accept it.

---

# 4. Field lifecycle state machine

Each field should have persistent state.

Recommended states:

```text
pending
  ↓
parsing
  ↓
contracted
  ↓
retrieving
  ↓
answering
  ↓
validating
  ↓
review_required
  ↓
approved
  ↓
exported

Alternative branches:

research_pending
clarification_required
conflict_detected
rejected
stale
failed
cancelled
```

Example:

```text
field_run.state = "retrieving"
field_run.last_agent_task_id = "task_442"
field_run.answer_json = null
field_run.evidence_summary = []
```

If the process crashes after field 47 of 80, restarting the form run should resume from field 47, not redo fields 1–46.

This is essential.

---

# 5. The reusable knowledge layer

This is the most important long-term design decision.

Do not build merely an “answer cache”.

Build a three-level knowledge system.

---

## Level 1 — Source evidence

Owned by existing RepoScroller.

Examples:

- original document,
- SHA-256 hash,
- file path,
- page number,
- extracted chunk,
- OCR text,
- document date,
- maturity status,
- version lineage.

Tables:

```text
document_ledger
file_locations
document_chunks
version_chains
audit_log
```

---

## Level 2 — Extracted structured facts

New administrative knowledge layer.

Examples:

```text
Company X has registered address Y.
Company X has UID CHE-123.456.789.
Person A was employed from 2020-01-01 to 2024-08-31.
Contract B has notice period 3 months.
Invoice C amount is CHF 1,250.00.
Tax assessment D due date is 2026-03-31.
```

Each fact must carry:

- subject,
- predicate,
- value,
- validity period,
- jurisdiction,
- language,
- source evidence,
- verification status,
- confidence dimensions,
- created by,
- verified by.

---

## Level 3 — Reusable approved answers

These are validated answers to recurring administrative questions.

Example:

```text
Question: What is the company's registered address?
Jurisdiction: CH
Language: FR
Format: structured_address
Answer: Bahnhofstrasse 1, 6300 Zug, CH
Valid until: current
Evidence: commercial register extract 2025-11-14
Status: approved
```

A2 consults Level 3 first.

If a validated answer exists and is still fresh, the system can reuse it immediately.

This is how the system becomes faster and stronger over time.

---

# 6. Suggested database schema

Below is a practical SQLite-compatible schema for the new module.

You can adapt names to your existing conventions.

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS form_templates (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT,
    source_sha256 TEXT,
    source_path TEXT,
    format TEXT NOT NULL,              -- pdf, docx, xlsx, web, markdown
    jurisdiction TEXT,                 -- CH, FR, DE, IT, etc.
    language TEXT,                     -- en, fr, de, it
    category TEXT,                     -- tax, insurance, banking, hr, legal
    schema_json TEXT NOT NULL,         -- full template structure
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS form_fields (
    field_id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL REFERENCES form_templates(template_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    label TEXT NOT NULL,
    canonical_question TEXT NOT NULL,
    question_hash TEXT,                -- normalized hash for reuse
    field_type TEXT NOT NULL,          -- text, date, amount, address, enum, boolean, table_row
    expected_format TEXT,              -- structured_address, iso_date, decimal_currency, etc.
    required INTEGER NOT NULL DEFAULT 0,
    validation_rules_json TEXT,
    dependency_json TEXT,              -- fields this field depends on
    freshness_policy TEXT DEFAULT 'current',
    evidence_required INTEGER NOT NULL DEFAULT 1,
    sensitivity TEXT DEFAULT 'normal', -- normal, pii, financial, legal
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_form_fields_template ON form_fields(template_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_form_fields_question_hash ON form_fields(question_hash);

CREATE TABLE IF NOT EXISTS form_runs (
    run_id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL REFERENCES form_templates(template_id),
    entity_scope_json TEXT,            -- person/org/period/locale involved
    status TEXT NOT NULL DEFAULT 'created',
    progress_pct REAL DEFAULT 0,
    created_by TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    exported_at TIMESTAMP,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS field_runs (
    field_run_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES form_runs(run_id) ON DELETE CASCADE,
    field_id TEXT NOT NULL REFERENCES form_fields(field_id),
    state TEXT NOT NULL DEFAULT 'pending',
    answer_text TEXT,
    answer_json TEXT,
    normalized_answer_json TEXT,
    confidence_json TEXT,
    evidence_summary_json TEXT,
    requires_human_review INTEGER NOT NULL DEFAULT 0,
    review_status TEXT DEFAULT 'not_required', -- not_required, pending, approved, rejected, edited
    last_agent_task_id TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, field_id)
);

CREATE INDEX IF NOT EXISTS idx_field_runs_run_state ON field_runs(run_id, state);
CREATE INDEX IF NOT EXISTS idx_field_runs_review ON field_runs(review_status, requires_human_review);

CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES form_runs(run_id) ON DELETE CASCADE,
    field_run_id TEXT REFERENCES field_runs(field_run_id) ON DELETE CASCADE,
    agent_role TEXT NOT NULL,             -- A1, A2, A3, validator
    task_type TEXT NOT NULL,              -- parse_field, retrieve_answer, research, validate
    status TEXT NOT NULL DEFAULT 'queued',-- queued, running, succeeded, failed, cancelled
    input_json TEXT NOT NULL,
    output_json TEXT,
    checkpoint_json TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_field_run ON agent_tasks(field_run_id, created_at);

CREATE TABLE IF NOT EXISTS evidence_links (
    evidence_id TEXT PRIMARY KEY,
    field_run_id TEXT REFERENCES field_runs(field_run_id) ON DELETE CASCADE,
    knowledge_fact_id TEXT,
    knowledge_answer_id TEXT,
    source_type TEXT NOT NULL,             -- document, chunk, entity, fact, external
    sha256_hash TEXT,
    chunk_id INTEGER,
    node_id TEXT,
    page_number INTEGER,
    character_start INTEGER,
    character_end INTEGER,
    excerpt TEXT,
    citation TEXT,
    authority_score REAL,
    freshness_score REAL,
    relevance_score REAL,
    retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_evidence_field_run ON evidence_links(field_run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_sha ON evidence_links(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_evidence_chunk ON evidence_links(chunk_id);

CREATE TABLE IF NOT EXISTS knowledge_facts (
    fact_id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,              -- e.g. organization:example_sa, person:jane_doe
    subject_type TEXT NOT NULL,
    predicate TEXT NOT NULL,               -- has_registered_address, has_uid, employed_from
    value_json TEXT NOT NULL,
    unit TEXT,
    currency TEXT,
    jurisdiction TEXT,
    language TEXT,
    period_start TEXT,
    period_end TEXT,
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'proposed', -- proposed, validated, rejected, expired
    confidence_json TEXT,
    created_by_agent TEXT,
    verified_by TEXT,
    verified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fact_subject_predicate ON knowledge_facts(subject_id, predicate, status);
CREATE INDEX IF NOT EXISTS idx_fact_status ON knowledge_facts(status, updated_at);

CREATE TABLE IF NOT EXISTS knowledge_answers (
    answer_id TEXT PRIMARY KEY,
    canonical_question TEXT NOT NULL,
    question_hash TEXT NOT NULL,
    answer_text TEXT,
    answer_json TEXT NOT NULL,
    output_format TEXT NOT NULL,
    jurisdiction TEXT,
    language TEXT,
    applicability_json TEXT,
    validity_policy TEXT DEFAULT 'current',
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'proposed', -- proposed, approved, rejected, expired
    usage_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_answer_unique_question
ON knowledge_answers(question_hash, jurisdiction, language, output_format, status);

CREATE TABLE IF NOT EXISTS review_decisions (
    decision_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,             -- field_run, knowledge_fact, knowledge_answer
    target_id TEXT NOT NULL,
    decision TEXT NOT NULL,                -- approve, edit, reject, request_research
    reviewer TEXT NOT NULL,
    comment TEXT,
    before_json TEXT,
    after_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_review_target ON review_decisions(target_type, target_id, created_at);

CREATE TABLE IF NOT EXISTS admin_audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    run_id TEXT,
    field_run_id TEXT,
    detail_json TEXT,
    source_sha256 TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_run ON admin_audit_events(run_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_admin_audit_actor ON admin_audit_events(actor, timestamp);
```

---

# 7. Typed contracts with Pydantic

Use Pydantic models to enforce structure.

Example:

```python
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class FieldType(str, Enum):
    text = "text"
    date = "date"
    amount = "amount"
    address = "address"
    enum = "enum"
    boolean = "boolean"
    table_row = "table_row"
    identifier = "identifier"


class FreshnessPolicy(str, Enum):
    current = "current"
    period_specific = "period_specific"
    point_in_time = "point_in_time"
    immutable = "immutable"


class FieldContract(BaseModel):
    field_id: str
    label: str
    canonical_question: str
    expected_type: FieldType
    output_format: str
    jurisdiction: Optional[str] = None
    language: Optional[str] = None
    required: bool = True
    freshness_policy: FreshnessPolicy = FreshnessPolicy.current
    evidence_required: bool = True
    dependencies: list[str] = Field(default_factory=list)
    validation_rules: dict = Field(default_factory=dict)
    sensitivity: str = "normal"


class EvidenceRef(BaseModel):
    source_type: str
    sha256_hash: Optional[str] = None
    chunk_id: Optional[int] = None
    node_id: Optional[str] = None
    page_number: Optional[int] = None
    excerpt: Optional[str] = None
    citation: Optional[str] = None
    authority_score: Optional[float] = None
    freshness_score: Optional[float] = None
    relevance_score: Optional[float] = None


class ConfidenceDimensions(BaseModel):
    relevance: float
    authority: float
    freshness: float
    agreement: float
    validation: float


class AnswerProposal(BaseModel):
    field_run_id: str
    status: str
    answer_text: Optional[str] = None
    answer_json: Optional[dict] = None
    confidence: Optional[ConfidenceDimensions] = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    requires_human_review: bool = True
    rationale: Optional[str] = None
    unresolved_questions: list[str] = Field(default_factory=list)
```

This is important because administrative forms need deterministic validation, not vibes.

---

# 8. Retrieval policy: progressive, not greedy

A2 should use a cost/evidence ladder.

## Step 1 — Approved answer lookup

Check `knowledge_answers`.

Match by:

- canonical question hash,
- jurisdiction,
- language,
- output format,
- entity scope,
- validity period.

If approved and fresh:

```text
reuse answer
link evidence
mark field approved or review_required depending on policy
```

---

## Step 2 — Structured fact lookup

Check `knowledge_facts`.

Example predicates:

```text
has_registered_address
has_uid
has_vat_number
has_bank_account_iban
has_employment_period
has_annual_revenue
has_signatory
has_insurance_policy_number
has_tax_identification_number
```

If a valid fact exists, format it into the field’s required output.

---

## Step 3 — Existing GraphRAG retrieval

Use RepoScroller’s existing hybrid engine:

- SHA-256 exact lookup,
- SimHash near-duplicate/version lineage,
- FTS5 BM25,
- dense vector cosine search,
- knowledge graph 1-hop / 2-hop expansion,
- Reciprocal Rank Fusion.

This is where RepoScroller’s current investment pays off.

---

## Step 4 — A3 targeted research

Only if Steps 1–3 are insufficient.

A3 may:

- search broader document sets,
- inspect related versions,
- follow lineage graphs,
- read adjacent pages,
- inspect tables,
- compare drafts vs final signed copies,
- extract candidate facts,
- detect contradictions.

---

## Step 5 — Clarification or human review

If still unresolved:

- ask the user,
- flag conflict,
- mark field as `clarification_required`,
- or send to human review.

Never hallucinate.

---

# 9. Confidence should be multidimensional

Do not rely on one LLM confidence score.

Track at least:

| Dimension | Meaning |
| --- | --- |
| Relevance | Does the source actually answer the question? |
| Authority | Is the source authoritative for this fact? |
| Freshness | Is the information valid for the requested period? |
| Agreement | Do independent sources support the same answer? |
| Validation | Does the answer satisfy format/legal constraints? |
| Provenance | Can we trace the answer to exact evidence? |

Example policy:

```python
def should_auto_approve(confidence, sensitivity, evidence_count):
    if sensitivity in {"pii", "financial", "legal"}:
        return False

    return (
        confidence.relevance >= 0.92
        and confidence.authority >= 0.90
        and confidence.freshness >= 0.88
        and confidence.agreement >= 0.90
        and confidence.validation >= 0.98
        and evidence_count >= 2
    )
```

For tax, legal, insurance, payroll, and government forms, I would strongly recommend:

> **Human review mandatory for critical fields.**

The system can propose, but a human approves.

---

# 10. Integration with existing RepoScroller components

The admin module should call existing services through interfaces, not directly manipulate low-level tables from every agent.

## Reuse directly

| RepoScroller component | Use in Admin Workbench |
| --- | --- |
| `document_ledger` | source identity, SHA-256, lifecycle status |
| `file_locations` | physical path of evidence |
| `document_chunks` | exact passage evidence |
| FTS5 | lexical search |
| vector store | semantic search |
| `knowledge_nodes` / `knowledge_edges` | entity graph |
| `document_entity_links` | document-entity relationships |
| taxonomy | category/theme scoping |
| GraphRAG engine | hybrid retrieval |
| duplicate agent | version/draft resolution |
| audit log | ALCOA+ traceability |
| FastAPI | admin API routes |
| frontend dashboard | Admin Workbench tab |

## Add new services

```text
backend/admin_forms/
    models.py
    schemas.py
    form_parser.py
    field_analyzer.py
    orchestrator.py
    answer_validator.py
    knowledge_service.py
    evidence_service.py
    export_service.py
    audit.py
    agents/
        form_analyst.py
        answer_orchestrator.py
        research_agent.py
```

Suggested API layer:

```text
backend/api/routes/admin_forms.py
```

---

# 11. Recommended backend workflow engine

For the first version, do not force Temporal immediately.

Use an abstraction:

```python
class WorkflowEngine(Protocol):
    def enqueue_field_task(...)
    def get_task_status(...)
    def retry_task(...)
    def cancel_task(...)
```

Initial implementation:

```text
SQLite-backed job queue + background worker
```

This matches your existing RepoScroller style and avoids new infrastructure.

Later, if needed, swap in:

```text
Temporal workflow engine
```

without changing the UI or agent contracts.

## When Temporal becomes worthwhile

Introduce Temporal when you need:

- long-running form runs lasting hours/days,
- durable human approval waits,
- reliable retries across process restarts,
- multiple concurrent form runs,
- complex cancellation/compensation,
- strong observability of agent workflows,
- production-grade SLAs.

The `temporal-community/temporal-ai-agent` repo is a very relevant reference for this.

But for MVP:

> Start with persistent SQLite states and idempotent workers.  
> Add Temporal when durability becomes a real operational requirement.

---

# 12. Temporal AI Agent Architecture and Swiss Domain Accelerators

We explicitly drop Lightspeed (`smartcomputer-ai/lightspeed` and `lightspeed-core/lightspeed-stack`) from the roadmap. We do not need an external Rust runtime, duplicate RAG stacks, or premature complexity. Instead, our design is inspired directly by the Python **Temporal AI Agent** architecture (`C:\dev-hub\temporal-ai-agent` / `temporal-community/temporal-ai-agent`), anchored in **three real Swiss administrative use cases** (in German), and accelerated by **five open-source Swiss tax repositories**.

---

## 12.1 The Core Blueprint: Temporal AI Agent (`C:\dev-hub\temporal-ai-agent`)

Inspecting `C:\dev-hub\temporal-ai-agent` provides the exact architectural pattern required for multi-field administrative forms. It solves the hardest challenges of agentic form completion:

```text
┌────────────────────────────────────────────────────────────────────────┐
│               Temporal Workflow: AgentGoalWorkflow                     │
│               (Deterministic State Machine & Loop)                     │
│                                                                        │
│   • Multi-turn goal evaluation                                         │
│   • Field-by-field state transitions                                   │
│   • Context compaction (preventing token exhaustion)                   │
│   • Signals: submit_user_input, approve_field, reject_field            │
│   • Queries: get_form_status, get_field_run                            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ schedules
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Temporal Activities: ToolActivities                      │
│               (Non-Deterministic, I/O-Bound, Retriable)                │
│                                                                        │
│   • LLM completions (LiteLLM / Ollama / Claude)                        │
│   • RepoScroller hybrid GraphRAG retrieval                             │
│   • AcroForm PDF reading & stamping (backend/clerk/tools/fill_form.py) │
│   • OCR text extraction for scanned enclosures                         │
│   • Deterministic tax calculations (taxcalc)                           │
│   • eSteuerauszug banking extraction (steuerauszug-generator)          │
│   • Anomaly & cross-document verification (TaxOffice-Copilot)          │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Pillars:
1. **Strict separation of Workflows and Activities**:
   - `AgentGoalWorkflow` contains only deterministic logic. When a worker restarts, Temporal replays history up to the current point without re-running expensive LLM inferences or mutating external databases.
   - All I/O, LLM prompts, embeddings, database queries, and PDF modifications live strictly inside `ToolActivities`.
2. **First-Class Human-in-the-Loop via Signals**:
   - Administrative filings require human approvals for sensitive financial, legal, or social welfare claims.
   - The workflow uses `await workflow.wait_condition(...)` to pause execution until an external signal (`submit_user_input`, `confirm_action`, `approve_field_answer`) is delivered. While waiting days or weeks for user review, workers consume zero CPU or memory.
3. **State Compaction**:
   - Administrative forms span dozens of fields and hundreds of document chunks. In `C:\dev-hub\temporal-ai-agent`, conversation and tool history are periodically compacted into structured summaries, ensuring context windows are never blown during complex multi-schedule filings.
4. **Native and MCP Tool Integration**:
   - Tools can be local Python functions (e.g. `pypdf` AcroForm engine) or external Model Context Protocol (MCP) servers (e.g. local SQLite, Ollama, document parsers).
5. **Activity Retries & Backoff**:
   - OCR timeouts, LLM rate limits, and network hiccups are handled automatically with configurable exponential backoff and jitter.

---

## 12.2 The Three Real Swiss Administrative Use Cases (in German)

Rather than designing for generic hypothetical forms, the entire engine is grounded in three real-world Swiss administrative documents:

### Use Case 1: Zurich Tax Declaration Form (*Zürcher Steuererklärung*)
*Target: Official Cantonal Tax Declaration (Formular 1–5)*

- **Scope & Schedules**:
  - **Hauptformular**: Personal data, AHV-Nummer (`756.xxxx.xxxx.xx`), marital status, net employment income (*Nettolohn gemäss Lohnausweis Ziffer 11*), pension income (AHV/IV, BVG/Pensionskasse).
  - **Wertschriften- und Guthabenverzeichnis**: Bank accounts, savings, stocks, bonds, funds. Requires *Steuerwert per 31.12.*, *Bruttoertrag mit Verrechnungssteuer*, and *Bruttoertrag ohne Verrechnungssteuer*.
  - **Berufsauslagen**: Commute expenses (*Fahrkosten mit ÖV/Velo/Auto*), additional meal costs (*Mehrkosten für auswärtige Verpflegung*), and professional development (*Weiterbildungskosten*).
  - **Schuldenverzeichnis**: Personal loans, mortgages, credit card debt (*Schulden per 31.12.* and *Schuldzinsen*).
  - **Liegenschaften**: Official rental value (*Eigenmietwert*) and maintenance deductions (*Liegenschaftenunterhalt: pauschal vs. effektiv*).
- **Primary Source Documents**:
  - *Lohnausweis* (Ziffer 1 bis 15), *eSteuerauszug* (bank tax statements), mortgage interest statements, Pillar 3a certificates (*Säule 3a Bescheinigungen*), donation receipts.
- **Legal Rules**:
  - Zürcher Steuergesetz (StG ZH), Bundesgesetz über die direkte Bundessteuer (DBG), Steuerharmonisierungsgesetz (StHG).

### Use Case 2: Zurich Social Assistance (*Sozialhilfeantragsformular Stadt/Kanton Zürich*)
*Target: Municipal/Cantonal Social Assistance Application (`backend/clerk/UseCases/2-SozialAmtPflege/`)*

- **Scope & Files**:
  - `Antragsformular_09.2018.pdf`: Multi-page formal application for social assistance (*Gesuch um Ausrichtung von wirtschaftlicher Hilfe*).
  - `Checkliste_Unterlagen.pdf`: Mandatory evidence checklist that must accompany the application.
- **Key Requirements**:
  - Household composition (*Zusammensetzung des Haushalts / Wohnsituation*).
  - Means-testing under SKOS guidelines (Schweizerische Konferenz für Sozialhilfe).
  - Income and asset declaration (*Einkommens- und Vermögensverhältnisse*): all bank accounts, cash, vehicles, life insurance surrender values.
  - Monthly budget deficit calculation: Basic living allowance (*Grundbedarf für den Lebensunterhalt*), actual rent and heating costs (*Mietzins inkl. Nebenkosten*), mandatory basic health insurance (*KVG-Prämie*), integration allowances (*Integrationszulage*).
- **Checklist Verification Engine**:
  - Cross-verifies presence of required proofs from `Checkliste_Unterlagen.pdf`: Mietvertrag, current KVG health insurance policy, bank statements for all accounts covering the last 3–6 months, extract from the debt enforcement register (*Betreibungsauszug*), latest tax bill, and divorce/separation agreements.

### Use Case 3: 3-URP Free Juridic Assistance Form (*Gesuch um unentgeltliche Rechtspflege*)
*Target: Cantonal Judicial Assistance Form (`backend/clerk/UseCases/3-URP-FreeJuridicAssistanceForm/`)*

- **Scope & Files**:
  - `Gesuch UP elektronisch ausfüllbar.pdf`: Official cantonal court form for legal aid under Art. 119 ZPO.
  - **Immediate Working MVP**: Already supported by RepoScroller's PDF AcroForm engine (`backend/clerk/tools/fill_form.py` and `backend/clerk/maps/mapping.json`).
- **Key Requirements**:
  - Court procedural context: Court name (*Behörde / Gericht*), case number (*Prozess- / Geschäfts-Nr.*), opposing party (*Gegenpartei*), lawyer representation details.
  - Proof of lack of financial means (*Bedürftigkeit der gesuchstellenden Person*).
  - Minimum existence budget (*Berechnung des betreibungsrechtlichen Existenzminimums nach SchKG / Zürcher Kreisschreiben*):
    - Basic monthly allowance (*Grundbetrag nach SchKG*).
    - Housing costs (*Wohnungsmiete inkl. Nebenkosten*).
    - Health insurance premiums (*Krankenkasse Grundversicherung KVG*).
    - Work-related expenses (*Unumgängliche Berufsauslagen*).
    - Child support / maintenance obligations (*Unterhaltsbeiträge*).
  - Comparison against monthly net income to prove inability to bear litigation costs without encroaching on basic subsistence.

---

## 12.3 Five Open-Source Swiss Tax Repositories as Domain Accelerators

To complete the Zurich Tax Declaration with professional accuracy, we integrate patterns, parsers, and engines from five specialized open-source repositories:

### 1. [SwissTaxAgent](https://github.com/salvatoreviticchie/SwissTaxAgent)
- **Technical Role**: Swiss tax domain reasoning and multi-agent prompt engineering.
- **Integration**:
  - Provides system prompts and few-shot examples for classifying income and deductions under Swiss federal (DBG) and cantonal (StG ZH) tax law.
  - Distinguishes between standard lump-sum deductions (*Pauschalabzüge*) and documented effective costs (*effektive Kosten*).
  - Used in A1 for canonical question framing and in A2 for deduction strategy recommendations.

### 2. [swissai-tax](https://github.com/Landmarklens/swissai-tax)
- **Technical Role**: Canton Zurich deduction heuristics and structured tax extraction.
- **Integration**:
  - Implements Canton Zurich-specific deduction rule sets:
    - Commute limits: ÖV vs. private vehicle justification (Fahrkostenabzug).
    - Daily meal allowances: Half vs. full day external lunch (Mehrkosten Verpflegung).
    - Continuing education allowances (*Weiterbildungskosten* up to cantonal ceiling).
    - Maximum Pillar 3a deduction limits (with and without 2nd pillar pension fund).
  - Outputs structured JSON ready for injection into our `field_runs` contracts.

### 3. [steuerauszug-generator](https://github.com/CaliCaliente/steuerauszug-generator)
- **Technical Role**: Electronic Swiss tax statement (*eSteuerauszug*) parser and generator.
- **Integration**:
  - Parses bank-issued *eSteuerauszug* PDFs and standardized XML files (UBS, Credit Suisse, ZKB, Raiffeisen, PostFinance, Swissquote).
  - Automatically extracts:
    - Taxable asset value per 31.12. (*Steuerwert per Stichtag*),
    - Gross yield subject to Swiss withholding tax (*Bruttoertrag mit Verrechnungssteuer 35%*),
    - Gross yield exempt from withholding tax (*Bruttoertrag ohne Verrechnungssteuer*),
    - Associated custody account fees (*Depotgebühren*).
  - Maps directly into the schedules of the *Wertschriften- und Guthabenverzeichnis*, eliminating hours of manual data entry.

### 4. [taxcalc](https://github.com/infogrind/taxcalc)
- **Technical Role**: Deterministic Swiss tax calculation engine.
- **Integration**:
  - Implements the exact mathematical tax curves for:
    - Simple cantonal basic tax (*Einfache Staatssteuer Kanton Zürich*),
    - Municipal tax multiplier (*Gemeindesteuerfuss*, e.g., Stadt Zürich, Winterthur, Uster),
    - Direct Federal Tax (*Direkte Bundessteuer*).
  - A2 invokes `taxcalc` as a deterministic tool activity to calculate projected tax liabilities, verify form line sums, and ensure that deductions mathematically match cantonal tax brackets.

### 5. [TaxOffice-Copilot](https://github.com/michaelbahr/TaxOffice-Copilot)
- **Technical Role**: Multi-document cross-verification and discrepancy detection.
- **Integration**:
  - Performs cross-document reconciliation:
    - Verifies that salary declared matches *Lohnausweis* Ziffer 11 and monthly bank statement inflows.
    - Flags discrepancies between previous year wealth declarations and current year opening balances.
    - Detects missing mandatory attachments (e.g. Pillar 3a certificate missing despite deduction claimed).
  - Powers the Field Review Studio's anomaly warning banner before final submission.

---

## 12.4 Summary Matrix: What We Use, Adapt, and Drop

| Component | Status | Rationale |
|---|---|---|
| **RepoScroller Core** | **Retain directly** | SQLite WAL, FTS5 lexical search, dense vectors, knowledge graph, and GraphRAG retrieval. |
| **Temporal AI Agent** (`C:\dev-hub\temporal-ai-agent`) | **Adopt as primary workflow engine** | Deterministic `AgentGoalWorkflow`, `ToolActivities`, signals for human review, and replay-safe durability. |
| **PDF AcroForm Engine** (`backend/clerk/tools/fill_form.py`) | **Retain & expand** | Working local `pypdf` population engine for Swiss cantonal PDF forms. |
| **3-URP Free Juridic Assistance Form** | **Phase 1 MVP target** | Ready-to-use template with existing field mapping (`maps/mapping.json`). |
| **Zurich Tax Declaration** | **Phase 2 target** | Supported by the 5 Swiss tax accelerators (`steuerauszug-generator`, `taxcalc`, `SwissTaxAgent`, etc.). |
| **Zurich Social Assistance Form** | **Phase 3 target** | Reconciled against `Checkliste_Unterlagen.pdf` and SKOS means-testing rules. |
| **Lightspeed Core Stack** (`lightspeed-core/lightspeed-stack`) | **Dropped completely** | Redundant Python RAG stack; RepoScroller GraphRAG already handles retrieval. |
| **Lightspeed Harness** (`smartcomputer-ai/lightspeed`) | **Dropped completely** | Complex Rust runtime with heavy multi-tenant container overhead unnecessary for our Python architecture. |

---

# 13. Recommended architecture decision

## Best option

**Integrated RepoScroller tab + separated admin workflow module.**

### Why

Fastest delivery:

- no duplicate ingestion,
- no duplicate retrieval,
- no duplicate auth,
- no duplicate dashboard,
- no duplicate knowledge graph,
- no duplicate audit system.

Clean future extraction:

- own API namespace,
- own tables,
- own worker,
- own schemas,
- own UI workspace.

If later you want to sell it:

```text
RepoScroller Admin Workbench
        ↓
extract /api/v1/admin/*
        ↓
standalone Administrative Agent service
```

without rewriting the core.

---

# 14. UI design: Administrative Workbench tab

Add a new top-level workspace:

```text
📋 Admin Workbench
```

Inside it, four main views.

---

## View 1 — Form Library

Purpose:

- upload new form templates,
- select saved templates,
- start a new form run,
- resume existing runs,
- see completion progress.

Example cards:

```text
Swiss Tax Declaration 2025
  Status: 62% complete
  Fields: 148
  Pending review: 12
  Last run: 2026-10-12

Employee Onboarding Form
  Status: draft
  Fields: 43
  Required evidence: 29

Bank KYC Form
  Status: blocked
  Missing: registered address proof, UBO declaration
```

---

## View 2 — Form Workspace

Purpose:

- show the original form,
- show extracted fields,
- allow field mapping corrections,
- show progress by section.

Important feature:

> If A1 misinterprets a field, the user must be able to correct the field contract.

Example:

```text
Original label: "Siège social"
A1 proposed:
  canonical_question: "What is the company's registered address?"
  expected_type: postal_address
  jurisdiction: CH

User can edit:
  ✓ accept
  ✎ edit
  ⚠ mark ambiguous
```

---

## View 3 — Field Review Studio

This is the primary working screen.

For each field:

```text
Question
Proposed answer
Evidence excerpts
Source document
Page / chunk
Confidence dimensions
Validation status
Actions
```

Actions:

```text
Approve
Edit
Reject
Request research
Ask user
Mark not applicable
Link to source document
Open in 3D Universe
Open in Ledger
```

Example:

```text
Field: Company registered address

Proposed answer:
Bahnhofstrasse 1, 6300 Zug, Switzerland

Evidence:
1. Commercial Register Extract, 2025-11-14, page 1
   SHA-256: abc...
   "The registered office is in Zug."

2. Articles of Association, 2024-03-02, page 3
   SHA-256: def...
   "The company has its seat in Zug."

Confidence:
Relevance: 0.96
Authority: 0.94
Freshness: 0.91
Agreement: 0.98
Validation: 1.00

Status:
Ready for approval
```

Clicking evidence should open the exact source passage, not merely the filename.

---

## View 4 — Agent Execution Monitor

Purpose:

- inspect A1/A2/A3 tasks,
- see retries,
- see failed extractions,
- see LLM latency,
- see source documents being researched,
- see unresolved questions.

Example:

```text
Task queue:
  A1 parse field 18/148        succeeded
  A2 retrieve field 19/148     running
  A3 research field 20/148     queued
  validator field 17/148       review_required
```

This is important for trust.

Users need to see why the system believes an answer.

---

## View 5 — Knowledge Quality Manager

Purpose:

- review newly proposed facts,
- merge duplicates,
- resolve conflicts,
- expire stale facts,
- approve reusable answers.

Example:

```text
Proposed fact:
  Subject: Example SA
  Predicate: has_registered_address
  Value: Bahnhofstrasse 1, 6300 Zug
  Source: Commercial Register 2025-11-14
  Status: proposed

Actions:
  Approve
  Reject
  Merge with existing fact
  Mark expired
  Request additional evidence
```

This is how the knowledge graph becomes stronger without becoming polluted.

---

# 15. Export design

The system must produce more than a chat response.

Supported exports:

## Phase 1

```text
JSON
CSV
XLSX
Markdown review report
```

Example JSON:

```json
{
  "run_id": "run_123",
  "template": "swiss_tax_declaration_2025",
  "generated_at": "2026-10-18T10:00:00Z",
  "fields": [
    {
      "field_id": "company_registered_address",
      "label": "Registered office address",
      "answer": "Bahnhofstrasse 1, 6300 Zug, CH",
      "status": "approved",
      "evidence": [
        {
          "sha256_hash": "abc...",
          "page": 1,
          "excerpt": "The registered office is in Zug."
        }
      ]
    }
  ]
}
```

## Phase 2

```text
Filled PDF
Filled DOCX
Structured government submission payload
```

For PDF filling:

- use PyMuPDF for AcroForm fields,
- use Docling/layout analysis for non-tagged forms,
- preserve original template,
- generate a separate output file,
- never mutate the source document.

For DOCX:

- use `python-docx`,
- map content controls/table cells,
- preserve formatting.

For web forms:

- later use Playwright/browser automation or a browser extension,
- but keep this out of MVP unless required.

---

# 16. ALCOA+ mapping for the admin module

Your existing RepoScroller architecture already targets ALCOA+. The admin module must inherit that.

| ALCOA+ principle | Administrative Workbench implementation |
| --- | --- |
| Attributable | Every answer, edit, approval, rejection, and research task logs actor, agent, timestamp, and source hash |
| Legible | Field answers, evidence excerpts, and validation reports stored as UTF-8 text and structured JSON |
| Contemporaneous | Field state transitions and agent task events recorded at execution time |
| Original | Evidence links point to original document SHA-256 and exact chunk/page |
| Accurate | Deterministic validators, multidimensional confidence, human review for critical fields |
| Complete | Missing fields, unresolved questions, conflicts, and clarifications are explicitly tracked |
| Consistent | Canonical facts and approved answers prevent contradictory reuse |
| Enduring | SQLite WAL ledger + append-only audit events |
| Available | REST API, dashboard, export, deep links to source evidence |

---

# 17. Implementation roadmap

This expands the previous AdminClerk plan into an executable roadmap.

Total estimate:

> **4–7 weeks for a serious pilot**, depending on form complexity and UI polish.

A narrow proof-of-concept can be delivered in **10–14 days**.

---

## Phase 0 — Architecture spike and reference form (3-URP)

Duration: **2–3 days**

### Objective

Prove the end-to-end concept using our first real Swiss administrative document: the **3-URP Free Juridic Assistance Form (*Gesuch um unentgeltliche Rechtspflege*, Art. 119 ZPO)** in `backend/clerk/UseCases/3-URP-FreeJuridicAssistanceForm/Gesuch UP elektronisch ausfüllbar.pdf`.

### Tasks

- Select the reference form:
  - **3-URP Gesuch um unentgeltliche Rechtspflege** (already supported by RepoScroller's PDF AcroForm engine `backend/clerk/tools/fill_form.py` and `maps/mapping.json`).
  - Next in line: **Zürcher Steuererklärung** (with Swiss tax accelerators) and **Sozialhilfeantragsformular** (`backend/clerk/UseCases/2-SozialAmtPflege/`).
- Freeze scope:
  - Language: German (Swiss administrative standard).
  - Primary source documents: *Lohnausweis* (salary certificate), *Mietvertrag* (lease), basic health insurance policy (*KVG*), bank extract.
  - Export format: Official AcroForm PDF via `backend/clerk/tools/fill_form.py`.
- Identify 10 golden fields from the 3-URP form:
  - 5 answerable from indexed personal documents (Name, AHV-Nr., Geburtsdatum, Wohnadresse, Nettolohn Ziffer 11).
  - 3 requiring calculation / research (Mietzins inkl. Nebenkosten, KVG-Prämie, Existenzminimum Grundbetrag).
  - 2 intentionally missing/conflicting to test human review (disputed legal debt, missing spouse income).
- Define initial typed field contract schema (`AHVNumber`, `CHFCurrency`, `DateField`).
- Validate that RepoScroller GraphRAG retrieves exact source chunks from the applicant's dossier.

### Deliverables

```text
backend/clerk/docs/admin-forms-reference-spec.md
backend/clerk/schemas.py
backend/clerk/maps/mapping.json
backend/clerk/tests/golden_questions_3urp.json
```

### Acceptance criteria

- The official 3-URP cantonal PDF form is parsed into structured field records.
- Existing RepoScroller retrieval finds at least 5/10 golden answers with exact page citations.
- Field state transitions (`pending` → `retrieving` → `answer_proposed` → `approved`) are validated.

---

## Phase 1 — Foundation: tables, contracts, API skeleton

Duration: **3–5 days**

### Objective

Create the administrative data model and basic API surface.

### Tasks

- Add SQLite migration/schema for:
  - `form_templates`,
  - `form_fields`,
  - `form_runs`,
  - `field_runs`,
  - `agent_tasks`,
  - `evidence_links`,
  - `knowledge_facts`,
  - `knowledge_answers`,
  - `review_decisions`,
  - `admin_audit_events`.
- Add Pydantic models.
- Add repository/service layer:
  - `FormRepository`,
  - `FieldRunRepository`,
  - `KnowledgeService`,
  - `EvidenceService`,
  - `AuditService`.
- Add FastAPI routes skeleton:
  - `POST /api/v1/admin/forms`
  - `GET /api/v1/admin/forms/{run_id}`
  - `POST /api/v1/admin/forms/{run_id}/analyze`
  - `POST /api/v1/admin/forms/{run_id}/fields/{field_id}/review`
  - `POST /api/v1/admin/forms/{run_id}/export`
- Add basic audit event logging.
- Add unit tests for schema and repository CRUD.

### Deliverables

```text
backend/admin_forms/models.py
backend/admin_forms/schemas.py
backend/admin_forms/repository.py
backend/api/routes/admin_forms.py
backend/tests/admin_forms/test_schema.py
backend/tests/admin_forms/test_repository.py
```

### Acceptance criteria

- Form template can be created.
- Form run can be created.
- Field runs can be created in `pending`.
- Audit events are written.
- API returns valid JSON.

---

## Phase 2 — Form ingestion and A1 Form Analyst

Duration: **4–6 days**

### Objective

Turn uploaded forms into structured field contracts.

### Tasks

- Support initial formats:
  - digital PDF,
  - DOCX,
  - optionally XLSX.
- Extract:
  - labels,
  - instructions,
  - field types,
  - checkboxes,
  - tables,
  - repeated sections,
  - required markers,
  - visible form structure.
- Use existing extraction stack:
  - PyMuPDF,
  - Docling,
  - text_extractor,
  - OCR if needed.
- Implement A1:
  - deterministic parser,
  - LLM-assisted interpretation,
  - Pydantic validation,
  - canonical question generation,
  - dependency detection.
- Add editable field mapping UI.
- Allow user correction of A1 output.
- Persist corrected field contracts.

### Deliverables

```text
backend/admin_forms/form_parser.py
backend/admin_forms/agents/form_analyst.py
frontend Admin Workbench: Form Workspace view
tests/admin_forms/test_form_parser.py
tests/admin_forms/test_form_analyst.py
```

### Acceptance criteria

- Upload one PDF/DOCX form.
- System extracts at least 80% of fields correctly.
- User can edit ambiguous fields.
- Each field has a typed contract.
- Field dependencies are represented.

---

## Phase 3 — A2 Answer Orchestrator and retrieval-first answering

Duration: **5–8 days**

### Objective

Answer fields using existing knowledge before doing expensive research.

### Tasks

- Implement A2 pipeline:
  1. approved answer lookup,
  2. structured fact lookup,
  3. GraphRAG retrieval,
  4. evidence ranking,
  5. answer formatting,
  6. validation.
- Integrate with existing:
  - FTS5,
  - vector store,
  - property graph,
  - GraphRAG query engine,
  - duplicate/version agent.
- Add answer formatters:
  - address,
  - date,
  - amount/currency,
  - enum,
  - boolean,
  - identifier,
  - text.
- Add validators:
  - required fields,
  - regex,
  - date ranges,
  - currency precision,
  - jurisdiction rules.
- Add multidimensional confidence scoring.
- Add policy engine:
  - auto-approve,
  - review required,
  - research required,
  - clarification required.
- Persist evidence links.
- Add field-level status transitions.

### Deliverables

```text
backend/admin_forms/agents/answer_orchestrator.py
backend/admin_forms/answer_validator.py
backend/admin_forms/knowledge_service.py
backend/tests/admin_forms/test_answer_orchestrator.py
backend/tests/admin_forms/test_validators.py
```

### Acceptance criteria

- For the reference form, at least 60% of fields can be proposed automatically.
- Every proposed answer has at least one evidence link.
- Missing evidence produces `research_pending` or `clarification_required`, not hallucinated text.
- Critical fields default to human review.

---

## Phase 4 — Review UI and export MVP

Duration: **5–8 days**

### Objective

Make the system usable by a human administrator.

### Tasks

- Build Field Review Studio:
  - question,
  - proposed answer,
  - evidence excerpt,
  - source document,
  - confidence,
  - actions.
- Build Agent Execution Monitor basic view:
  - queued/running/succeeded/failed tasks.
- Add approve/edit/reject/request-research actions.
- Add deep link:
  - open source chunk in Ledger,
  - highlight excerpt,
  - optionally open related node in 3D Universe.
- Add export:
  - JSON,
  - CSV,
  - Markdown review report.
- Add form run progress dashboard.
- Add resume behavior:
  - reopening a run shows saved states.

### Deliverables

```text
frontend Admin Workbench: Field Review Studio
frontend Admin Workbench: Agent Monitor
backend/admin_forms/export_service.py
backend/tests/admin_forms/test_export.py
```

### Acceptance criteria

- User can review all proposed fields.
- User can edit answers.
- User can approve/reject.
- Export contains answers plus evidence references.
- Interrupted run can be resumed.

This is already a valuable MVP.

---

## Phase 5 — A3 Research and Knowledge Enrichment

Duration: **5–8 days**

### Objective

Resolve unanswered fields and improve future runs.

### Tasks

- Implement A3 research agent:
  - query planner,
  - document candidate selection,
  - version/draft resolution,
  - passage extraction,
  - fact extraction,
  - conflict detection,
  - research package generation.
- Add background worker for long-running research.
- Add retry and checkpointing.
- Add proposed facts to `knowledge_facts`.
- Add proposed answers to `knowledge_answers`.
- Add Knowledge Quality Manager UI:
  - review proposed facts,
  - approve/reject/merge/expire.
- Add validation gate before promotion to trusted knowledge.
- Add reuse metrics:
  - how often approved answers are reused,
  - research yield,
  - fact acceptance rate.

### Deliverables

```text
backend/admin_forms/agents/research_agent.py
backend/admin_forms/knowledge_promotion.py
frontend Admin Workbench: Knowledge Quality Manager
backend/tests/admin_forms/test_research_agent.py
backend/tests/admin_forms/test_knowledge_promotion.py
```

### Acceptance criteria

- A3 can resolve at least 50% of initially unanswered golden questions.
- A3 proposals are not automatically trusted.
- Human can approve proposed facts.
- Approved facts are reused in subsequent form runs.
- Conflicting evidence is surfaced, not hidden.

---

## Phase 6 — Temporal AI Agent Workflow Engine (`C:\dev-hub\temporal-ai-agent`)

Duration: **3–5 days**

### Objective

Adopt the Python **Temporal AI Agent** architecture (`C:\dev-hub\temporal-ai-agent`) as the durable execution backbone for long-running form runs, retries, context compaction, and human approval signals.

### Tasks

- Port agent orchestration to Temporal:
  - Map form runs and goals to `AgentGoalWorkflow` (`temporalio.workflow`).
  - Map non-deterministic tools (LLM queries, GraphRAG search, AcroForm stamping, `taxcalc` engine) to `ToolActivities` (`temporalio.activity`).
- Implement human-in-the-loop signals:
  - `submit_user_input`: Resumes workflow when applicant supplies missing info.
  - `confirm_action` / `approve_field_answer`: Unblocks PDF field stamping upon human review.
- Implement workflow queries:
  - `get_form_status`: Instant live progress query without DB polling.
  - `get_field_run`: Direct inspection of field evidence and confidence.
- Implement state compaction:
  - Port compaction patterns from `C:\dev-hub\temporal-ai-agent` to periodically summarize intermediate tool thoughts and fact history, keeping token usage lean across multi-schedule filings.
- Configure retry policies with exponential backoff for OCR, LLM APIs, and external calculation services.

### Deliverables

```text
backend/clerk/workflows/agent_goal_workflow.py
backend/clerk/workflows/compaction.py
backend/clerk/activities/tool_activities.py
backend/clerk/activities/form_activities.py
backend/tests/clerk/test_temporal_workflow.py
backend/tests/clerk/test_temporal_activities.py
```

### Acceptance criteria

- Killing the worker process mid-run does not lose completed field states or restart already approved fields.
- Workflows sleep indefinitely waiting for human review signals with zero compute overhead.
- Intermediate tool history is automatically compacted when context limits are approached.
- Replaying workflow history does not trigger redundant LLM calls or duplicate audit records.

---

## Phase 7 — Security, privacy, pilot metrics, hardening

Duration: **4–6 days**

### Objective

Prepare for real administrative data.

### Tasks

- Add access control:
  - who can view forms,
  - who can approve facts,
  - who can export.
- Add PII handling:
  - masking in logs,
  - sensitive field flags,
  - export restrictions.
- Add retention policy:
  - evidence retention,
  - fact expiration,
  - audit retention.
- Add metrics:
  - answer correctness,
  - evidence coverage,
  - autonomous completion rate,
  - reuse rate,
  - research yield,
  - review burden,
  - time saved.
- Add golden regression tests.
- Add pilot documentation.

### Deliverables

```text
docs/admin-workbench-pilot-runbook.md
backend/tests/admin_forms/test_security.py
metrics dashboard or API endpoint
```

### Acceptance criteria

- Pilot user can complete one real form end-to-end.
- Every critical answer is traceable to evidence.
- No unresolved field is silently exported as fact.
- System reports accuracy and coverage metrics.

---

# 18. Suggested MVP scope

To deliver immediate value, ground the MVP in our three real Swiss administrative use cases:

## MVP primary form (Milestone 1)

**3-URP Free Juridic Assistance Form (*Gesuch um unentgeltliche Rechtspflege*, Art. 119 ZPO)**  
Location: `backend/clerk/UseCases/3-URP-FreeJuridicAssistanceForm/Gesuch UP elektronisch ausfüllbar.pdf`

*Why this is the fastest win*:
- Official cantonal court form with fillable AcroForm fields already mapped in `backend/clerk/maps/mapping.json`.
- Working PDF engine already exists in `backend/clerk/tools/fill_form.py`.
- Clear, well-defined rules for financial eligibility (Existenzminimum under SchKG and Zurich court circulars).

## Next priority forms (Milestones 2 & 3)

1. **Zurich Tax Declaration (*Zürcher Steuererklärung*, Formular 1–5)**:
   - Hauptformular, Wertschriftenverzeichnis, Berufsauslagen, Liegenschaften, Schulden.
   - Accelerated by the 5 Swiss tax repositories (`steuerauszug-generator`, `taxcalc`, `SwissTaxAgent`, `swissai-tax`, `TaxOffice-Copilot`).
2. **Zurich Social Assistance Form (*Sozialhilfeantragsformular Stadt/Kanton Zürich*)**:
   - Location: `backend/clerk/UseCases/2-SozialAmtPflege/Antragsformular_09.2018.pdf`.
   - Means-testing under SKOS guidelines with evidence cross-reconciliation against `Checkliste_Unterlagen.pdf`.

## MVP formats

```text
Digital AcroForm PDF (via fill_form.py / pypdf) + XML/eSteuerauszug
```

Skip initially:
- handwritten paper mail forms,
- robotic process automation (RPA) of government web portals,
- automated direct submission to cantonal authorities.

## MVP capabilities

```text
Form upload & AcroForm inspection
A1 typed field contracts (AHV-Nr, CHF amounts, dates)
A2 retrieval from existing GraphRAG & personal dossiers
Evidence deep-linking to exact document pages/chunks
Temporal AI Agent workflow coordination (C:\dev-hub\temporal-ai-agent)
Domain tool activities: taxcalc math verification & eSteuerauszug parsing
Field Review Studio with human approval signals
Automated AcroForm PDF stamping via backend/clerk/tools/fill_form.py
Audit manifest generation (ALCOA+ compliant)
```

## MVP non-goals

```text
Unsupervised autonomous government submission without human review
Public multi-tenant SaaS hosting
Scanned handwriting OCR
Direct cantonal tax server API connectivity (eTax portal)
```

---

# 19. 10-day proof-of-concept plan

If you want the fastest possible visible result, do this:

## Day 1

- Create `admin_forms` module.
- Add core tables:
  - `form_templates`,
  - `form_fields`,
  - `form_runs`,
  - `field_runs`,
  - `evidence_links`.
- Add Pydantic `FieldContract`.

## Day 2

- Build API skeleton:
  - create form run,
  - get field runs,
  - update field run state.
- Add audit event stub.

## Day 3

- Implement PDF/DOCX field extraction.
- Populate `form_fields`.
- Add simple frontend list of extracted fields.

## Day 4

- Implement A1 canonical question generation.
- Add LLM + deterministic validation.
- Allow manual edit of field contract.

## Day 5

- Connect A2 to existing GraphRAG.
- Retrieve top evidence chunks for each field.
- Store evidence links.

## Day 6

- Add answer formatter and validator.
- Add confidence dimensions.
- Produce proposed answers.

## Day 7

- Build Field Review Studio minimal UI.
- Show question, answer, evidence excerpt, approve/edit/reject.

## Day 8

- Add export JSON/CSV.
- Add Markdown review report.
- Add resume from saved field states.

## Day 9

- Add A3 stub:
  - if no evidence, mark `research_pending`.
- Add background task placeholder.
- Add diagnostic logging.

## Day 10

- Run golden tests.
- Fix obvious parser/retrieval issues.
- Demo one complete form run.

This gives you a working internal pilot before investing in full knowledge enrichment.

---

# 20. API design

Suggested endpoints:

```text
POST   /api/v1/admin/templates
GET    /api/v1/admin/templates
GET    /api/v1/admin/templates/{template_id}

POST   /api/v1/admin/forms
GET    /api/v1/admin/forms
GET    /api/v1/admin/forms/{run_id}

POST   /api/v1/admin/forms/{run_id}/analyze
POST   /api/v1/admin/forms/{run_id}/process
POST   /api/v1/admin/forms/{run_id}/cancel

GET    /api/v1/admin/forms/{run_id}/fields
GET    /api/v1/admin/forms/{run_id}/fields/{field_id}

POST   /api/v1/admin/forms/{run_id}/fields/{field_id}/research
POST   /api/v1/admin/forms/{run_id}/fields/{field_id}/review
POST   /api/v1/admin/forms/{run_id}/fields/{field_id}/clarify

GET    /api/v1/admin/forms/{run_id}/tasks
GET    /api/v1/admin/tasks/{task_id}

POST   /api/v1/admin/forms/{run_id}/export
GET    /api/v1/admin/forms/{run_id}/export/{format}

GET    /api/v1/admin/knowledge/facts
POST   /api/v1/admin/knowledge/facts
POST   /api/v1/admin/knowledge/facts/{fact_id}/review

GET    /api/v1/admin/knowledge/answers
POST   /api/v1/admin/knowledge/answers/{answer_id}/review

GET    /api/v1/admin/audit-events
```

Example review payload:

```json
{
  "decision": "approve",
  "reviewer": "user:admin",
  "comment": "Verified against commercial register extract.",
  "edited_answer_json": null
}
```

Example research payload:

```json
{
  "reason": "No current registered address evidence found.",
  "priority": "high",
  "allowed_sources": [
    "commercial_register",
    "articles_of_association",
    "signed_contract"
  ]
}
```

---

# 21. Agent orchestration pseudocode

A simplified orchestrator:

```python
async def process_form_run(run_id: str):
    run = form_repo.get_run(run_id)
    fields = form_repo.get_field_runs(run_id)

    ordered_fields = topological_sort_by_dependencies(fields)

    for field_run in ordered_fields:
        if field_run.state in {"approved", "exported", "rejected"}:
            continue

        await update_state(field_run, "contracted")

        contract = await a1_analyze_field(field_run)

        await update_state(field_run, "retrieving")

        proposal = await a2_retrieve_answer(contract)

        if proposal.status == "answer_proposed":
            validation = await validator.validate(contract, proposal)

            if validation.auto_approve_allowed:
                await approve_field(field_run, proposal)
            else:
                await request_human_review(field_run, proposal)

        elif proposal.status == "research_required":
            await update_state(field_run, "research_pending")
            research_package = await a3_research(contract)

            validation = await validator.validate_research(research_package)

            if validation.can_propose:
                await propose_knowledge(research_package)
                await request_human_review(field_run, research_package.answer)
            else:
                await request_clarification(field_run, validation.reasons)

        elif proposal.status == "clarification_required":
            await request_user_clarification(field_run, proposal.questions)

    await finalize_run(run_id)
```

The important part is that every transition is persisted.

---

# 22. Knowledge promotion policy

A3 should propose, not certify.

Suggested lifecycle:

```text
proposed
  ↓
validated automatically? ── yes ─→ approved
  │
  no
  ↓
review_required
  ↓
human approve ──→ approved
human reject ──→ rejected
expired ───────→ expired
```

Automatic approval should only happen when:

- source authority is high,
- evidence is fresh,
- fact is non-sensitive,
- multiple sources agree,
- validator passes,
- no conflict exists.

For critical facts:

```text
always human review
```

Examples requiring human review:

- legal representative,
- tax identification,
- bank account,
- salary,
- ownership,
- UBO,
- criminal liability,
- insurance declarations,
- residency status,
- contract signing authority.

---

# 23. Conflict handling

Administrative knowledge often conflicts because of versions.

Examples:

```text
Old address vs new address
Draft contract vs signed contract
Expired commercial register extract vs current extract
OCR mistake vs clean digital PDF
Personal backup copy vs authoritative NAS copy
```

The system must detect conflicts and resolve them using:

- document date,
- lifecycle status,
- maturity score,
- source authority,
- signature/stamp presence,
- version lineage,
- repository priority,
- human override.

Conflict output:

```json
{
  "conflict_type": "temporal_supersession",
  "winner": "commercial_register_extract_2025",
  "loser": "articles_of_association_2021",
  "reason": "Newer authoritative register extract supersedes older constitutional address statement.",
  "requires_human_review": false
}
```

RepoScroller already has maturity/version lineage concepts. Reuse them.

---

# 24. Multilingual design

Your existing taxonomy supports FR/DE/EN.

The admin module should reuse that.

For each field:

```text
label_fr
label_de
label_en
canonical_question
jurisdiction
language
output_format
```

Canonical question hashing should be language-aware but concept-aligned.

Example:

```text
FR: "Quelle est l'adresse du siège social ?"
DE: "Wie lautet der Sitz der Gesellschaft?"
EN: "What is the company's registered address?"
```

All map to:

```text
question_hash: company_registered_address
```

But the answer format may differ by jurisdiction/language:

```text
CH-FR: address format Swiss French
CH-DE: address format Swiss German
DE: DIN 5008 style maybe
```

---

# 25. Dependencies and conditional fields

Many forms have conditional logic.

Example:

```text
If marital_status = married:
    spouse_name is required
    spouse_birth_date is required
else:
    spouse fields are not applicable
```

A1 should output dependency metadata:

```json
{
  "field_id": "spouse_name",
  "depends_on": "marital_status",
  "condition": "marital_status == 'married'",
  "required_if_condition_true": true
}
```

The orchestrator should process fields in topological order.

If a prerequisite is unresolved, dependent fields become:

```text
blocked
```

not failed.

---

# 26. Evidence deep-linking

This is a major UX advantage over a generic chatbot.

Every answer should be clickable to the exact evidence.

Evidence link should contain:

```text
sha256_hash
chunk_id
page_number
character_start
character_end
excerpt
source_path
document_date
lifecycle_status
```

Frontend behavior:

```text
Click evidence
    ↓
Open Ledger document detail
    ↓
Highlight exact chunk/page
    ↓
 Optionally open related entity in 3D Universe
```

This makes the system trustworthy.

---

# 27. Background processing design

For MVP:

```text
FastAPI receives request
    ↓
Creates agent_task row
    ↓
Local worker thread/process polls queued tasks
    ↓
Updates field_run state
    ↓
Frontend polls /api/v1/admin/forms/{run_id}/tasks
```

Use the existing diagnostic/logging architecture.

For heavier production:

```text
Temporal worker
    ↓
Workflow per form_run
    ↓
Activities per A1/A2/A3/validator
    ↓
Signals for human review
```

Design the interface now so you can swap later.

---

# 28. Observability

Add metrics for every field and task:

```text
latency_ms
llm_tokens_in
llm_tokens_out
retrieval_candidates
evidence_count
confidence_relevance
confidence_authority
confidence_freshness
confidence_agreement
confidence_validation
retry_count
error_type
source_documents_consulted
```

Expose in:

```text
/api/v1/admin/metrics
Floating Diagnostic Console
Admin Workbench Agent Monitor
```

Important operational question:

> How much of the form can be completed without human correction?

That is the real value metric.

---

# 29. Success metrics

Prioritize correctness over automation rate.

| Metric | Target for pilot |
| --- | --- |
| Answer correctness | ≥ 95% for approved answers |
| Evidence coverage | 100% of approved answers have evidence |
| Autonomous completion | 40–70% depending on form complexity |
| Human correction rate | ≤ 20% of proposed answers |
| Reuse rate | increases over time, target ≥ 30% after 10 runs |
| Research yield | ≥ 50% of A3 tasks produce usable evidence |
| Reliability | zero lost field states after restart |
| Time saved | measure manual vs assisted completion time |

A system that fills every field but fabricates critical answers is dangerous.

Better:

```text
transparently unresolved
```

than:

```text
silently wrong
```

---

# 30. Security and privacy

Administrative forms often contain PII.

Required controls:

- role-based access,
- sensitive field classification,
- log redaction,
- encrypted backups,
- audit trails,
- export permissions,
- data retention policy,
- evidence access control,
- no secrets in prompts/logs,
- local-first LLM routing where possible.

For sensitive fields:

```text
sensitivity = pii | financial | legal
```

Then:

- mask in diagnostic logs,
- require human review,
- restrict export,
- record every access.

---

# 31. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| LLM hallucinates answers | Evidence-first policy, validators, human review |
| Form parser misreads fields | Editable field mapping UI |
| Old documents used as current facts | Freshness policies and validity periods |
| Conflicting versions | Maturity score, lineage graph, source authority |
| Knowledge base pollution | Proposed vs approved separation |
| Long-running tasks lost | Persistent field states, checkpoints, retries |
| Users distrust answers | Evidence deep links and confidence breakdown |
| Too much complexity early | Narrow MVP, one form, one export format |
| Temporal overkill | Start local queue, abstract workflow engine |
| PII leakage | Sensitivity flags, redaction, access control |

---

# 32. Final recommended architecture

Use this as the target design:

```text
RepoScroller Admin Workbench
│
├── Frontend tab: Administrative Workbench
│   ├── Form Library
│   ├── Form Workspace
│   ├── Field Review Studio
│   ├── Agent Monitor
│   └── Knowledge Quality Manager
│
├── Backend module: backend/admin_forms
│   ├── form_parser.py
│   ├── field_analyzer.py
│   ├── orchestrator.py
│   ├── answer_validator.py
│   ├── knowledge_service.py
│   ├── evidence_service.py
│   ├── export_service.py
│   ├── audit.py
│   └── agents/
│       ├── form_analyst.py       # A1
│       ├── answer_orchestrator.py # A2
│       └── research_agent.py      # A3
│
├── API namespace: /api/v1/admin/*
│
├── Dedicated SQLite tables
│   ├── form_templates
│   ├── form_fields
│   ├── form_runs
│   ├── field_runs
│   ├── agent_tasks
│   ├── evidence_links
│   ├── knowledge_facts
│   ├── knowledge_answers
│   ├── review_decisions
│   └── admin_audit_events
│
├── Workflow engine abstraction
│   ├── local SQLite queue for MVP
│   └ optional Temporal engine later
│
└── Reuses existing RepoScroller intelligence
    ├── document_ledger
    ├── document_chunks
    ├── FTS5
    ├── vector store
    ├── knowledge graph
    ├── GraphRAG
    ├── taxonomy
    ├── duplicate/version resolution
    └ audit logging
```

---

# 33. My concrete recommendation

Build it this way:

## Step 1 — Integrate as a RepoScroller tab

Do not create a separate app.

## Step 2 — Keep the admin workflow isolated

New module, new tables, new API namespace.

## Step 3 — Start with A1 + A2 only

First valuable version:

```text
upload form
extract fields
retrieve evidence
propose answers
human review
export
```

## Step 4 — Add A3 after the review loop works

A3 should enrich knowledge only after you have a validation/approval mechanism.

## Step 5 — Adopt the Temporal AI Agent pattern

Structure agent execution according to the **Temporal AI Agent** architecture (`C:\dev-hub\temporal-ai-agent`):
- Workflows for deterministic coordination (`AgentGoalWorkflow`),
- Activities for LLM calls, GraphRAG retrieval, OCR, and PDF form filling (`ToolActivities`),
- Signals for human approval,
- State compaction for token economy.

## Step 6 — Leverage domain-specific accelerators, drop Lightspeed

```text
temporal-community/temporal-ai-agent (C:\dev-hub\temporal-ai-agent)
  └── Primary Workflow & Activity Architecture (durable, replay-safe, human-in-the-loop)

Five Open-Source Swiss Tax Repositories
  ├── salvatoreviticchie/SwissTaxAgent   → Swiss tax prompts & deduction reasoning (DBG/StHG/StG ZH)
  ├── Landmarklens/swissai-tax           → Canton Zurich deduction heuristics & structured JSON
  ├── CaliCaliente/steuerauszug-generator→ eSteuerauszug PDF/XML parsing for Wertschriftenverzeichnis
  ├── infogrind/taxcalc                  → Deterministic cantonal/municipal/federal tax math engine
  └── michaelbahr/TaxOffice-Copilot      → Multi-document cross-verification & discrepancy checks

Lightspeed (smartcomputer-ai / lightspeed-core)
  └── Dropped completely (unnecessary Rust complexity and duplicate RAG layers)
```

---

# 34. The three grounded milestones

Rather than building an abstract form engine, structure delivery around our three real Swiss administrative use cases:

## Milestone 1: 3-URP Free Juridic Assistance Form (Immediate Working MVP)

> **Target**: `backend/clerk/UseCases/3-URP-FreeJuridicAssistanceForm/Gesuch UP elektronisch ausfüllbar.pdf` (Art. 119 ZPO).

**Success means**:
- Applicant identity and case metadata extracted.
- Monthly net wage retrieved from *Lohnausweis* (Ziffer 11).
- Rent and health insurance expenses matched from leases and KVG policies.
- Existenzminimum basic allowance calculated according to Zurich court rules.
- Automated AcroForm PDF population via RepoScroller's existing `backend/clerk/tools/fill_form.py` and `maps/mapping.json`.
- Human reviewer verifies and signs off before PDF export.

## Milestone 2: Zurich Tax Declaration (*Zürcher Steuererklärung*)

> **Target**: Official Cantonal Tax Declaration (Formular 1–5 in German).

**Success means**:
- Ingestion of *Lohnausweis*, mortgage statements, and Pillar 3a certificates.
- Bank *eSteuerauszug* PDFs/XML parsed via `steuerauszug-generator` to auto-fill the *Wertschriften- und Guthabenverzeichnis*.
- Cantonal deduction rules (commute, lunch, training) applied via `swissai-tax` and `SwissTaxAgent`.
- Multi-document numbers verified and cross-checked via `TaxOffice-Copilot`.
- Cantonal (*Staatssteuer*), municipal (*Gemeindesteuer*), and federal (*Direkte Bundessteuer*) amounts verified mathematically with `taxcalc`.

## Milestone 3: Zurich Social Assistance (*Sozialhilfeantragsformular*)

> **Target**: `backend/clerk/UseCases/2-SozialAmtPflege/Antragsformular_09.2018.pdf`.

**Success means**:
- Application fields mapped to applicant family dossier and bank accounts.
- Automated verification against `Checkliste_Unterlagen.pdf` (detecting missing leases, bank statements, or debt enforcement records).
- Monthly budget deficit calculated according to SKOS standards.
- Application package exported with complete evidence citations for the municipal social office (*Sozialamt*).

---

## Bottom line

Your instinct is correct: an administrative clerk should not be a disposable chatbot. It must be a **durable, evidence-backed administrative workflow engine** that learns from every completed filing and compounds institutional knowledge over time.

The winning architecture is:

> **Integrate the Administrative Workbench inside RepoScroller (`backend/clerk/`), orchestrate via Temporal AI Agent patterns (`C:\dev-hub\temporal-ai-agent`), and accelerate domain execution using the five Swiss tax open-source tools.**

- **RepoScroller Core** provides the trusted evidence layer (SQLite WAL, FTS5, vector search, and GraphRAG).
- **Temporal AI Agent** provides replay-safe durable orchestration, human-in-the-loop signal pauses, and context compaction.
- **`fill_form.py` & AcroForm Mappings** deliver pixel-perfect official Swiss cantonal PDF generation.
- **The 3 Real Swiss Use Cases (3-URP, Zurich Tax, Sozialhilfe)** ensure every feature is anchored in actual German-language administrative reality from day one.
