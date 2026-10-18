# RepoScroller Administrative Agent: architecture and implementation plan

My recommendation is to integrate the administrative tool as a new module inside RepoScroller, while keeping its execution engine modular and independently testable.

I would not build a second, standalone document-intelligence platform. RepoScroller already has much of the infrastructure your use case needs: document ingestion, a persistent ledger, multilingual processing, hybrid retrieval, a knowledge graph, a LangGraph-based agent workflow, and a FastAPI interface. Your uploaded implementation summary describes these capabilities and a background knowledge-base processing queue.&#x20;

repoScroller-implementation_summary.md

The missing piece is a dedicated Administrative Form Completion Engine: a system that understands forms, turns each field into an evidence-backed information request, delegates retrieval or research, and produces a validated answer ready for human review and export.

## 1. The product I would build

### RepoScroller — existing foundation

Document discovery · Deduplication · OCR and extraction · Hybrid GraphRAG · Knowledge graph · Audit trail

### New module: Administrative Workbench

The administrative workbench is tailored directly to real-world Swiss administrative document completion. It is specifically designed around three primary Swiss cantonal and municipal use cases (in German):

1. **Zurich Tax Declaration Form (*Zürcher Steuererklärung*)**:
   - Complex multi-schedule filing: Hauptformular, Wertschriften- und Guthabenverzeichnis, Berufsauslagen (Fahrkosten, Mehrkosten Verpflegung), Liegenschaftenunterhalt, and Schuldenverzeichnis.
   - Requires parsing financial statements (eSteuerauszug / Bankauszüge, Lohnausweis), tax deduction heuristics, and mathematical tax curve calculations.
2. **Social Assistance Application Form (*Sozialhilfeantragsformular Stadt/Kanton Zürich*)**:
   - Cantonal-level welfare application (`backend/clerk/UseCases/2-SozialAmtPflege/Antragsformular_09.2018.pdf`).
   - Strict means-testing based on SKOS guidelines. Requires reconciling mandatory evidence against `Checkliste_Unterlagen.pdf` (Mietvertrag, Krankenkassenpolice, Kontoauszüge der letzten 3–6 Monate, Betreibungsauszug).
3. **3-URP Free Juridic Assistance Form (*Gesuch um unentgeltliche Rechtspflege*, Art. 119 ZPO)**:
   - Cantonal government / judicial assistance (`backend/clerk/UseCases/3-URP-FreeJuridicAssistanceForm/Gesuch UP elektronisch ausfüllbar.pdf`).
   - Litigant poverty determination (Berechnung des betreibungsrechtlichen Existenzminimums nach SchKG / Zürcher Kreisschreiben), cross-matching procedural costs and lawyer representation fees.
   - Already mapped and populated via RepoScroller's PDF AcroForm engine (`backend/clerk/tools/fill_form.py` and `backend/clerk/maps/mapping.json`).

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Administrative Workbench                        │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Form Ingestion & AcroForm Mapping                                   │
│    AcroForms (pypdf), Swiss cantonal PDF forms, tables, checkboxes     │
│                                                                        │
│ 2. Field Analysis & Contracts (A1)                                     │
│    Canonical questions, AHV-Nr., currency (CHF), canton/commune rules  │
│                                                                        │
│ 3. Agent Orchestration via Temporal AI Agent (A2)                      │
│    Retrieve, calculate (taxcalc), verify (TaxOffice-Copilot), escalate │
│                                                                        │
│ 4. Deep Research & Knowledge Enrichment (A3)                           │
│    Scan multi-year bank statements, leases, pay slips, eSteuerauszug   │
│                                                                        │
│ 5. Review & Export Gate                                                │
│    ALCOA+ audit trail, evidence deep-linking, AcroForm PDF generation  │
└────────────────────────────────────────────────────────────────────────┘
```

### Shared knowledge layer

Reuse the existing repository and knowledge graph, with a curated layer of reusable Swiss administrative facts (AHV-Nummer, Steuer-ID, IBANs, household members, employer details, rental agreements) with explicit validity periods and provenance.

The important distinction is that this is not just another chatbot tab. It is a deterministic, workflow-oriented application that manages an administrative task from intake to verified PDF export.

## 2. How your A1 → A2 → A3 model should work

I would keep your three-agent concept, but implement it as a controlled workflow inspired by the **Temporal AI Agent** architecture (`C:\dev-hub\temporal-ai-agent`), separating deterministic workflow transitions from non-deterministic tool activities.

### A1: Form Analyst
*One question per field, with a typed output contract*

Extracts field labels, underlying intent, required format, jurisdiction (e.g., Canton Zurich / Bund), time period (e.g., Steuerjahr 2025), and dependencies on other fields (e.g., if married, spouse income required).

*Examples in our Swiss use cases*:
- Field `AHV_Nr`: Format regex `^756\.\d{4}\.\d{4}\.\d{2}$`.
- Field `Nettoeinkommen`: Mapped to Ziffer 11 on the Swiss *Lohnausweis*.
- Field `Mietzins`: Mapped to net rent + Nebenkosten in the *Mietvertrag*.
- Field `Wertschriftenertrag`: Mapped to total gross yield with withholding tax (*Verrechnungssteuer*) from the *eSteuerauszug*.

### A2: Answer Orchestrator
*Retrieve, assess evidence, execute domain tools, and choose the next action*

Coordinates retrieval across structured facts, full-text indexes, vector retrieval, and the knowledge graph. A2 also dispatches specialized deterministic tool activities (e.g., `taxcalc` for tax sums, `fill_form.py` for AcroForm mapping).

- **Evidence sufficient**: Reuses existing validated knowledge or extracts answers directly from primary documents (e.g., latest Lohnausweis), formats values (e.g., CHF rounding rules), and records exact source chunks.
- **Evidence missing / ambiguous**: Delegates to A3 for targeted corpus research or signals human review.

### A3: Research and Knowledge Enrichment Agent
*Find evidence, reconcile multi-document sources, and propose reusable facts*

Searches the wider document corpus, inspects unstructured attachments (e.g., 12 months of bank PDF exports, medical expense receipts, court summons), resolves version conflicts, extracts supported facts, and registers proposed knowledge for future filings.

### Answer validator and human review gate
Validates format, evidence, freshness, consistency, and completeness. Returns the answer to the field or flags it as unknown, conflicting, or requiring human approval before PDF stamping.

### One critical design decision
A3 should never automatically turn an LLM-generated answer into trusted knowledge.

It must propose knowledge records supported by identifiable sources with page-level citations. A validation step then determines whether the record is accepted, needs human approval, or remains unresolved. Otherwise, a hallucinated deduction or misread AHV number could silently propagate across future tax filings and legal applications.

## 3. Should it be a new tab or a separate application?

Here is how I would evaluate the options for your current architecture.

Option A — A new RepoScroller tab

Recommended

One application, shared data and infrastructure

- Reuses your existing ledger and retrieval engine.
- Gives users a familiar interface to their documents and administrative workflows.
- Avoids building a second authentication, indexing and monitoring stack.
- Makes it easy to navigate from an answer to the source document.

Option B — A separate application

Independent UI, backend and deployment

- Useful if you eventually sell this as a standalone product or serve multiple organizations.
- Allows independent release cycles and scaling.
- Introduces API contracts, deployment complexity and more operational overhead.
- Risks duplicating RepoScroller's document and knowledge infrastructure unless designed carefully.

Option C — Integrated UI, separate workflow service

The best long-term architecture

- Keep the user experience inside RepoScroller.
- Put form processing and agent orchestration behind dedicated modules and API endpoints.
- Run long-running research as background jobs.
- Scale or extract the workflow service later without redesigning the product.

My choice is Option C, implemented initially as Option A from the user's perspective. Build the feature into the existing application, but do not mix form-specific business logic into the crawler, ledger or GraphRAG modules.

This gives you a fast first release without creating a dead-end architecture.

## 4. Architecture references: Temporal AI Agent and Swiss Open-Source Tax Accelerators

We explicitly drop Lightspeed (`smartcomputer-ai/lightspeed` and `lightspeed-core/lightspeed-stack`) from the roadmap. We do not need an external Rust runtime, duplicate RAG stacks, or premature complexity. Instead, our design is inspired directly by the Python **Temporal AI Agent** architecture (`C:\dev-hub\temporal-ai-agent` / `temporal-community/temporal-ai-agent`) combined with five specialized open-source Swiss tax repositories that accelerate our primary use cases.

### 1. Temporal AI Agent (`C:\dev-hub\temporal-ai-agent`)
*The blueprint for deterministic, durable, and human-in-the-loop agent workflows*

Inspecting `C:\dev-hub\temporal-ai-agent` reveals the exact architectural pattern required for multi-field administrative forms:

- **Strict separation of Workflows and Activities**:
  - `AgentGoalWorkflow`: A deterministic state machine coordinating field-level goals, agent turns, and tool selection. Because it executes deterministically, Temporal guarantees replay safety and state persistence across worker crashes or machine restarts without re-invoking LLMs.
  - `ToolActivities`: Houses all non-deterministic, I/O-bound, and model-driven tasks: LLM completions (via LiteLLM / local Ollama / Claude), RepoScroller hybrid GraphRAG queries, OCR text extraction, AcroForm PDF field reading/writing with `pypdf` (`backend/clerk/tools/fill_form.py`), and mathematical tax calculations.
- **Signals for Human-in-the-Loop**:
  - Administrative forms require human approvals for sensitive fields (e.g., deductions, asset declarations, poverty thresholds). Temporal Workflows pause execution using `workflow.wait_condition(...)` until an external signal (`submit_user_input`, `confirm_action`, `approve_field_answer`) arrives, consuming zero compute resources while waiting days or weeks for user verification.
- **State Compaction**:
  - Multi-field forms easily exhaust model context limits. `AgentGoalWorkflow` implements context compaction, summarizing intermediate research steps into structured facts while retaining exact evidence links.
- **MCP Client and Native Tools**:
  - Direct support for Model Context Protocol (MCP) servers alongside native Python tools, allowing seamless integration with local tools and document stores.

### 2. Five Open-Source Swiss Tax Repositories
*Domain-specific accelerators for the Zurich Tax Declaration (Zürcher Steuererklärung)*

Completing Swiss tax declarations in German requires deep familiarity with cantonal tax codes, eSteuerauszug formats, and calculation curves. Rather than building these from scratch, we leverage patterns and modules from five open-source repositories:

1. **[SwissTaxAgent](https://github.com/salvatoreviticchie/SwissTaxAgent)**:
   - **Role**: Multi-agent tax reasoning patterns & prompt engineering for Swiss federal and cantonal tax law (DBG, StHG, StG ZH).
   - **Contribution**: Provides domain prompts for classifying taxable vs. tax-exempt income, Pillar 3a allowances, and distinguishing between standard and effective business expense deductions.
2. **[swissai-tax](https://github.com/Landmarklens/swissai-tax)**:
   - **Role**: Canton Zurich deduction heuristics and structured JSON tax extraction.
   - **Contribution**: Specialized rule sets for Zurich cantonal deductions: Berufsauslagen (commute/Fahrkosten, lunch/Mehrkosten für Verpflegung), training expenses (*Weiterbildungskosten*), and healthcare costs (*Krankheits- und Unfallkosten*).
3. **[steuerauszug-generator](https://github.com/CaliCaliente/steuerauszug-generator)**:
   - **Role**: Swiss electronic tax statement (*eSteuerauszug*) parser and generator.
   - **Contribution**: Automatically extracts structured securities and bank account data from bank-issued eSteuerauszug PDFs and XML files: taxable asset value (*Steuerwert*), gross yield with Swiss withholding tax (*Bruttoertrag mit Verrechnungssteuer*), and without withholding tax (*Bruttoertrag ohne Verrechnungssteuer*), populating the *Wertschriftenverzeichnis* schedule directly.
4. **[taxcalc](https://github.com/infogrind/taxcalc)**:
   - **Role**: Deterministic mathematical tax calculation engine.
   - **Contribution**: Calculates exact Swiss cantonal taxes (*Einfache Staatssteuer*), municipal multipliers (*Gemeindesteuerfuss*), and federal tax (*Direkte Bundessteuer*). A2 invokes `taxcalc` as a deterministic tool activity to verify that form totals and tax estimates balance before final export.
5. **[TaxOffice-Copilot](https://github.com/michaelbahr/TaxOffice-Copilot)**:
   - **Role**: Multi-document cross-verification and discrepancy detection.
   - **Contribution**: Reconciles reported numbers across multiple documents (e.g., verifying that salary stated on the *Lohnausweis* matches monthly bank statement inflows, or checking debt totals against credit statements). Alerts the human reviewer to omissions or red flags.

### Summary: What We Actually Use

| Capability | Engine / Reference | Rationale |
|---|---|---|
| Evidence search & GraphRAG | RepoScroller Core (SQLite WAL, FTS5, Vectors, Graph) | Proven in RepoScroller; zero duplication |
| Durable Agent Orchestration | Temporal AI Agent (`C:\dev-hub\temporal-ai-agent`) | Deterministic workflow replay, signals for human approval, activity retries |
| PDF AcroForm Filling & Mapping | `backend/clerk/tools/fill_form.py` (`pypdf`) | Working local implementation for cantonal PDF forms |
| Swiss Tax Calculations & Rules | `taxcalc` + `swissai-tax` + `SwissTaxAgent` | Accurate Zurich cantonal calculations & legal rule prompting |
| eSteuerauszug & Financial Data | `steuerauszug-generator` | Structured parsing of Swiss bank statements for Wertschriftenverzeichnis |
| Multi-Doc Verification & Anomaly Detection | `TaxOffice-Copilot` patterns | Cross-reconciliation between Lohnausweis, bank balances, and declarations |
| Lightspeed (Rust / Core) | **Excluded** | Unnecessary operational overhead and duplicate RAG layers |


## 5. The most important design improvement: build a reusable knowledge system, not just an answer cache

Your idea of enriching the knowledge base is the part that could make this genuinely valuable over time.

I would introduce a dedicated Administrative Knowledge Layer above RepoScroller's existing document index.

There should be a clear distinction between original evidence, extracted facts and approved reusable answers.

## Three levels of knowledge

Level 1 — Source evidence

Original documents, exact passages, tables, page numbers, file hashes, document versions and source dates.

Owned by the existing RepoScroller document infrastructure.

Level 2 — Extracted facts

Structured information such as legal entity, registration number, address, reporting period, revenue, employment dates and contractual status.

Each fact carries provenance, applicable dates and verification status.

Level 3 — Reusable answer knowledge

Validated answers to recurring administrative questions, including the expected output format, applicable conditions, language and links to supporting facts.

The layer A2 consults first when answering a new form.

For example, one source document may establish a company's registered address. That fact may answer fields in five different forms. Each form should reuse the fact but retain its own question, wording requirements and audit trail.

Do not create a new embedding or duplicate document for every form field. Link answers to existing source chunks and structured facts.

### Suggested data model

I would introduce the following core entities:

| Entity              | Purpose                                                          |
| ------------------- | ---------------------------------------------------------------- |
| `form_templates`    | Reusable form definitions and versions                           |
| `form_fields`       | Field label, question, format, validation rules and dependencies |
| `form_runs`         | One form completion instance                                     |
| `field_runs`        | State and answer for each field in a form run                    |
| `agent_tasks`       | A1/A2/A3 execution, retries and task status                      |
| `evidence_links`    | Connections between answers and source passages                  |
| `knowledge_facts`   | Normalized, reusable facts with validity periods                 |
| `knowledge_answers` | Approved answers to recurring question types                     |
| `review_decisions`  | Human corrections, approvals and rejections                      |
| `audit_events`      | Append-only history of important actions                         |

These should be linked to the existing ledger using stable document IDs or hashes wherever possible. I would not store the entire form workflow inside `document_ledger`.

## 6. Smart implementation details

### A. Give every field a typed contract

A1 should not produce only a natural-language question. It should return structured metadata that A2 can use deterministically.

For example, real fields from our Swiss use cases (3-URP, Zürcher Steuererklärung, Sozialhilfe) are represented with strict validation contracts:

```json
{
  "field_id": "pers_ahv_nr",
  "label": "AHV-Nummer / No AVS",
  "canonical_question": "Wie lautet die 13-stellige AHV-Nummer der antragstellenden Person?",
  "expected_type": "ahv_number",
  "output_format": "formatted_string",
  "jurisdiction": "CH",
  "required": true,
  "freshness_policy": "immutable",
  "evidence_required": true,
  "validation_rules": {
    "regex": "^756\\.\\d{4}\\.\\d{4}\\.\\d{2}$"
  }
}
```

Or for income extracted from the Swiss *Lohnausweis* (Ziffer 11) for the 3-URP and Zurich Tax forms:

```json
{
  "field_id": "einkommen_nettolohn_hauptberuf",
  "label": "Nettolohn gemäss Lohnausweis Ziffer 11",
  "canonical_question": "Wie hoch ist der jährliche Nettolohn der antragstellenden Person nach Abzug der Sozialversicherungsbeiträge?",
  "expected_type": "currency_chf",
  "output_format": "chf_amount",
  "jurisdiction": "CH-ZH",
  "period": "2025",
  "required": true,
  "freshness_policy": "annual",
  "evidence_required": true,
  "validation_rules": {
    "min_value": 0.0,
    "source_target": "Lohnausweis Ziffer 11"
  }
}
```

Use Pydantic models to validate these contracts. The LLM interprets the field, but ordinary code enforces the schema, required fields and output format.

For numerical fields, dates, checkboxes and enumerated choices, use deterministic validators rather than asking an LLM whether the output looks correct.

### B. Make retrieval progressively more expensive

I would implement A2 as a retrieval and decision pipeline, not a free-form agent loop.

1\. Structured knowledge lookup

Fastest and most deterministic

Look for an approved answer or a current, verified fact.

2\. Hybrid GraphRAG retrieval

Reuse existing infrastructure

Search exact terms, BM25, dense vectors and graph relationships; rerank evidence and inspect source authority.

3\. Targeted repository research

A3 only when needed

Expand to related documents, versions, attachments, OCR or relevant sections of larger files.

4\. Clarification or human review

When evidence is insufficient

Ask the user for missing information or present conflicting evidence instead of inventing an answer.

The existing implementation summary describes hybrid retrieval combining lexical search, vector similarity, graph expansion and answer-grounding checks.&#x20;

repoScroller-implementation_summary.md

&#x20;Extend that foundation rather than rebuilding retrieval inside the new module.

### C. Use confidence as a decision policy, not a single LLM score

A single confidence number can be misleading. I would track at least:

- Evidence relevance: does the source address the question?
- Source authority: is the source authoritative for this particular fact?
- Freshness: is the information valid for the requested period?
- Agreement: do independent sources support the same answer?
- Validation: does the answer satisfy the form's constraints?

Then define explicit policies. For example, an approved answer can be reused automatically when its source remains valid, the required evidence is present and all field validations pass. Conflicting or time-sensitive facts should be escalated.

This is particularly important for tax, legal, insurance and other regulated administrative forms.

### D. Separate research from knowledge approval

A3 should return a research package containing:

- Proposed fact or answer.
- Source document identifiers and exact passages.
- Page or section references.
- Relevant dates and version information.
- Conflicting evidence, if any.
- Explanation of what remains uncertain.

A separate validation step can then update the knowledge layer. This lets you benefit from new discoveries without silently promoting unverified claims into trusted knowledge.

### E. Make the entire process resumable

Every field should have a persistent state, such as:

`pending → analyzing → retrieving → researching → validating → review_required → approved`

A form with 80 fields should not have to restart when the application closes after processing field 47.

Use idempotent task execution, bounded retries, persisted checkpoints and explicit cancellation. This can initially be implemented using your existing Python and database infrastructure. Temporal is a potential later upgrade if durable, long-running orchestration becomes a priority.

## 7. What the user interface should look like

I would create a new top-level Administrative Workbench tab with four main views.

[VALMAX / Services | Dribbble](https://images.openai.com/static-rsc-4/Esv-Y5bVhEZyivzj3n7vx46srXHQwWbs6rctxaGHGNlTdtQhd5X-yXBHHBrIz_fgGYiYMK9tKXhWhQQV_aWtDSD7WH-DX3abjHHjSk45oisGsnDTcS2PNMnKoZ0f0zS5GChY80iN2jjGxvcGv1wRL3N1s-mFcO_hqVLD0hssW1U?purpose=inline)

1\. Form workspace

Start and resume administrative tasks

Upload a PDF, DOCX or spreadsheet; select a saved template; view completion progress; and resume existing form runs.

[CasePrepAI - AI-Assisted Underwriting Preparation Platform by Sunil M for Mayura Consultancy Services (MCS) on Dribbble](https://images.openai.com/static-rsc-4/yLBWzOkdNjraGNn4yE_hxZKvwP9pQTEGL2OpcdEd269qeQXkUI5GKHgtC_IscGo64dMEtQrfX00UL2GmTMN-H2pr72UASnZl0HUa2oTmVBKuDQLNq6m8L6heAF--zKN-TITRqntrze-ncR36x3PUw5V_Rp1MeFz5lqrN826Ze6E?purpose=inline)

2\. Field review studio

The primary working screen

Show each question, proposed answer, source excerpts, confidence signals, status and actions to approve, edit, reject or request more research.

[Daniel Danek | Python Backend Engineer for AI Governance and Agent Systems](https://images.openai.com/static-rsc-4/jg-PS4MUoYLh70EGIvznbyg1YsfHOBeHzO--Uuidk6UQ34FVRIIWo0zvxtoufDgbG5KnSroDsYp5ieEZGt9MK4bdPYQLbSxbtMH6ljtQz0PhQj4jCdmW7vaURtUAr06CEplrtMx5ipWz9o09gC3ZEniXow2L34I8NhJf90PG3FY?purpose=inline)

3\. Agent execution monitor

Operational visibility

Inspect A1/A2/A3 tasks, source documents being examined, progress, retries, errors and unresolved questions. Expose useful execution details without overwhelming normal users.

[Loopio vs. Responsive vs. Conveyor  | Conveyor](https://images.openai.com/static-rsc-4/Vhu5wV7QGslmQv4Taj2bDzrp9kj8_6ePOTDzWhp6levaIabWPpJadMt1jzTJhb8tqyAUz61FtWnBXmbvk4ECGajNPXOl9yocFbcO6ULUncII71mkUnQNbpku5FlL7nkRl7unK06PgZsHNBTg4kZHHVTDEsXn5AXnB6HPYSgC9dU?purpose=inline)

4\. Knowledge quality manager

Improve future completion runs

Review newly discovered facts, merge duplicates, resolve conflicting versions, inspect provenance and manage expiration or revalidation.

One especially valuable feature: clicking any answer should open the exact source passage in RepoScroller, not merely show the document filename.

## 8. Concrete implementation roadmap

I would implement this in six focused phases anchored directly in our three Swiss administrative use cases, starting with the fastest working win (3-URP) and scaling to multi-document tax and social assistance filings.

### Phase 01: 3-URP Free Juridic Assistance Form & AcroForm Mapping Engine
*The immediate working MVP (3–5 days)*

- **Target form**: `backend/clerk/UseCases/3-URP-FreeJuridicAssistanceForm/Gesuch UP elektronisch ausfüllbar.pdf` (Art. 119 ZPO).
- Connect and expand `backend/clerk/tools/fill_form.py` and `maps/mapping.json` for deterministic AcroForm PDF field reading and population via `pypdf`.
- Define typed Pydantic contracts for personal applicant data, monthly net income (Lohnausweis Ziffer 11), rent expenses (Mietvertrag), and basic health insurance premiums (KVG-Police).
- Implement Existenzminimum calculation check according to Cantonal Zurich guidelines (SchKG / Zürcher Kreisschreiben).
- **Deliverable**: End-to-end extraction and automated filling of the 3-URP form from indexed personal documents with 100% field traceability.

### Phase 02: Zurich Tax Declaration & Swiss Tax Open-Source Integration
*Zürcher Steuererklärung (Formular 1–5) (5–8 days)*

- Ingest and map Zurich Tax Declaration schedules: Hauptformular, Wertschriften- und Guthabenverzeichnis, Berufsauslagen, and Schuldenverzeichnis.
- Integrate **`steuerauszug-generator`** to parse bank-issued *eSteuerauszug* PDFs/XML and map *Steuerwert* and *Bruttoertrag* directly into the securities schedule.
- Integrate **`taxcalc`** as a deterministic tool activity to calculate and verify cantonal and municipal tax totals (*Einfache Staatssteuer* & *Gemeindesteuerfuss*).
- Integrate **`SwissTaxAgent`** & **`swissai-tax`** prompt patterns for deduction heuristics (commute/Fahrkosten, lunch/Verpflegung, Säule 3a, debt interest/Schuldzinsen).
- **Deliverable**: Validated, multi-schedule Zurich tax filing draft with automated calculations and verified source evidence.

### Phase 03: Zurich Social Assistance (*Sozialhilfeantragsformular*) & Checklist Verification
*Welfare assistance application & document reconciliation (5–7 days)*

- **Target form**: `backend/clerk/UseCases/2-SozialAmtPflege/Antragsformular_09.2018.pdf`.
- Implement checklist verification engine based on `Checkliste_Unterlagen.pdf` (Mietvertrag, Krankenkassenpolice, Kontoauszüge der letzten 3–6 Monate, Betreibungsauszug).
- Integrate **`TaxOffice-Copilot`** patterns to perform cross-document consistency checks (comparing bank account inflows against declared wages and deficits).
- Implement SKOS-based means-testing rule validators and household asset threshold verification.
- **Deliverable**: Complete social welfare application package with flagged missing checklist items and automated budget deficit calculation.

### Phase 04: Temporal AI Agent Orchestration Engine
*Durable workflows, signals, and state compaction (4–6 days)*

- Port the orchestration layer to the **Temporal AI Agent** architecture (`C:\dev-hub\temporal-ai-agent`).
- Implement `AgentGoalWorkflow` coordinating form goals and field state machine transitions.
- Implement `ToolActivities` housing LLM queries, GraphRAG calls, AcroForm stamping (`fill_form.py`), and `taxcalc` execution.
- Implement Temporal signals (`submit_user_input`, `confirm_action`, `approve_field_answer`) for durable human-in-the-loop pauses.
- Implement context compaction to ensure multi-field runs never exceed token limits.
- **Deliverable**: Fault-tolerant, replay-safe agent execution surviving restarts and long approval waits.

### Phase 05: Workbench UI, Field Review Studio & Export Gate
*Human review and side-by-side verification (5–7 days)*

- Build the Administrative Workbench tab inside RepoScroller with Form Library, Review Studio, and Agent Monitor.
- Side-by-side evidence viewer: clicking any proposed value highlights the exact bounding box or text excerpt in the original Swiss PDF (e.g., Lohnausweis, Mietvertrag).
- Human approval / override buttons for each field with ALCOA+ audit logging.
- Final export: Generate stamped, compliant AcroForm PDFs with full audit manifest.
- **Deliverable**: Production-ready reviewer interface for cantonal filings.

### Phase 06: Reliability, Security, and Cantonal Compliance Pilot
*Hardening and field testing (4–6 days)*

- Test with real-world edge cases: variable income, partial-year tax liability, shared rental leases, disputed debt records.
- Enforce strict local data privacy (sensitive financial and social welfare data processed via local Ollama models or isolated enterprise endpoints).
- Measure accuracy, source grounding, and time savings against human benchmark filings.
- **Deliverable**: Field-tested administrative assistant pilot for Swiss cantonal workflows.

## 9. Suggested repository structure

Keep the administrative clerk cleanly organized within `backend/clerk/`, integrating Temporal AI Agent patterns and our existing PDF mapping tools:

```text
backend/clerk/
├── __init__.py
├── models.py                     # SQLAlchemy models: form_runs, field_runs, knowledge_facts
├── schemas.py                    # Pydantic field contracts and Swiss administrative schemas
├── form_parser.py                # PDF AcroForm and template inspection
├── answer_validator.py           # Format, regex, CHF currency, and freshness validators
├── knowledge_service.py          # Level 1/2/3 Swiss administrative fact store
├── export_service.py             # Final AcroForm PDF population & audit packaging
├── audit.py                      # ALCOA+ compliant append-only ledger
│
├── workflows/                    # Temporal AI Agent Workflows (C:\dev-hub\temporal-ai-agent)
│   ├── __init__.py
│   ├── agent_goal_workflow.py    # Deterministic AgentGoalWorkflow state machine
│   └── compaction.py             # Context window compaction and fact aggregation
│
├── activities/                   # Temporal Non-Deterministic Tool Activities
│   ├── __init__.py
│   ├── tool_activities.py        # LLM completions, GraphRAG search, OCR
│   └── form_activities.py        # PDF filling, validation, calculation activities
│
├── adapters/                     # Swiss Administrative Domain Accelerators
│   ├── __init__.py
│   ├── tax/
│   │   ├── steuerauszug.py       # eSteuerauszug parser (from steuerauszug-generator)
│   │   ├── taxcalc_engine.py     # Cantonal/federal math engine (from taxcalc)
│   │   ├── swiss_tax_rules.py    # Deduction heuristics (from SwissTaxAgent & swissai-tax)
│   │   └── copilot_verifier.py   # Multi-document reconciliation (from TaxOffice-Copilot)
│   └── social/
│       ├── skos_budget.py        # SKOS welfare budget calculation (Sozialamt)
│       └── checklist_matcher.py  # Checkliste Unterlagen cross-verification
│
├── tools/                        # Existing CLI and PDF utilities
│   ├── fill_form.py              # Working AcroForm population engine (pypdf)
│   └── mapping_write.py          # Field-to-box interactive mapping generator
│
├── maps/                         # Pre-compiled form field mappings
│   ├── mapping.json              # Working 3-URP field coordinates and keys
│   ├── steuererklaerung_zh.json  # Zurich Tax Declaration field mappings
│   └── sozialhilfe_zh.json       # Zurich Social Assistance field mappings
│
└── UseCases/                     # Real Swiss Administrative Form Templates
    ├── 1-ZurichTax/              # Zurich Tax forms & eSteuerauszug samples
    ├── 2-SozialAmtPflege/        # Antragsformular_09.2018.pdf & Checkliste_Unterlagen.pdf
    └── 3-URP-FreeJuridicAssistanceForm/ # Gesuch UP elektronisch ausfüllbar.pdf
```

API routes integrate with RepoScroller's FastAPI router under `/api/v1/admin/...`:

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/admin/forms` | Create a new form run from an uploaded template (e.g. 3-URP or Zurich Tax) |
| `GET /api/v1/admin/forms/{run_id}` | Retrieve overall progress, completion percentage, and field states |
| `POST /api/v1/admin/forms/{run_id}/analyze` | Start A1 field decomposition and validation contract generation |
| `POST /api/v1/admin/forms/{run_id}/fields/{field_id}/answer` | Run A2 answer orchestration with GraphRAG and tool activities |
| `POST /api/v1/admin/forms/{run_id}/fields/{field_id}/research` | Delegate unresolved questions to A3 targeted repository research |
| `POST /api/v1/admin/forms/{run_id}/fields/{field_id}/review` | Submit human edit, approval, or rejection signal |
| `POST /api/v1/admin/forms/{run_id}/export` | Generate stamped AcroForm PDF (`fill_form.py`) and audit manifest |
| `GET /api/v1/admin/knowledge/review-queue` | Review proposed new administrative facts before knowledge promotion |

## 10. Temporal AI Agent as the Primary Workflow Engine

We do not use Lightspeed (`smartcomputer-ai/lightspeed` or `lightspeed-core/lightspeed-stack`). The Python **Temporal AI Agent** architecture (`C:\dev-hub\temporal-ai-agent`) is the exact right engine for RepoScroller Administrative Clerk.

### Why Temporal AI Agent fits our requirements:
1. **Durable Multi-Turn Execution**: Administrative forms contain dozens of fields. Filling them involves multi-step research that may take minutes or hours. Temporal Workflows never lose state if the application server restarts; they resume from their last deterministic checkpoint.
2. **First-Class Human-in-the-Loop Signals**: A tax deduction or welfare eligibility declaration requires human review. In Temporal, the workflow executes `await workflow.wait_condition(...)` until an external signal (`approve_field_answer`) is received. The worker releases all memory and CPU while waiting days or weeks for the human reviewer.
3. **Automatic Replay Safety**: Deterministic workflow logic ensures that replaying an interrupted workflow does not duplicate expensive LLM calls or overwrite previously confirmed fields. Non-deterministic operations remain strictly isolated inside `ToolActivities`.
4. **Context Compaction**: As seen in `C:\dev-hub\temporal-ai-agent`, long-running conversations and tool execution logs are periodically compacted into structured summaries, preventing context exhaustion during multi-schedule filings.
5. **Robust Retry Policies**: OCR failures, LLM rate limits, and external tax tool timeouts are handled with exponential backoff and jitter out of the box.

## 11. Define success before scaling

The pilot should be evaluated using explicit, domain-specific metrics across our three Swiss use cases:

| Metric | What to measure | Target |
|---|---|---|
| **Answer correctness** | Percentage of answers verified as factually and legally correct | ≥ 98% on approved fields |
| **Evidence coverage** | Percentage of answered fields with direct page-level citations | 100% (mandatory) |
| **Autonomous completion** | Percentage of fields completed without human correction | 70–85% for standard filings |
| **Math accuracy** | Accuracy of tax totals and budget deficit calculations | 100% verified via `taxcalc` |
| **Reuse rate** | Percentage of fields answered from existing validated knowledge | ≥ 60% for returning applicants |
| **Time saved** | Total completion and review time versus manual filing | 75% reduction in completion time |

I prioritize answer correctness, source grounding, and mathematical verification over raw automation rate. A system that leaves ambiguous fields unresolved for human review is vastly superior to one that fabricates numbers on an official cantonal filing.

## My final recommendation

Build the Administrative Workbench as a dedicated module inside RepoScroller (`backend/clerk/`), orchestrating A1 for form understanding, A2 for retrieval and domain tool execution, and A3 for targeted research and fact enrichment.

Drop Lightspeed completely. Adopt the **Temporal AI Agent** architecture (`C:\dev-hub\temporal-ai-agent`) for deterministic workflows, human-in-the-loop signals, and replay-safe durability.

Center the system immediately on the **three real Swiss administrative use cases**:
1. **3-URP Free Juridic Assistance Form** as the immediate working MVP (already supported by `backend/clerk/tools/fill_form.py` and `maps/mapping.json`).
2. **Zurich Tax Declaration (*Zürcher Steuererklärung*)**, accelerated by the five open-source Swiss tax repositories (`steuerauszug-generator`, `taxcalc`, `SwissTaxAgent`, `swissai-tax`, `TaxOffice-Copilot`).
3. **Zurich Social Assistance Form (*Sozialhilfeantragsformular*)**, powered by automated checklist verification against `Checkliste_Unterlagen.pdf`.

Keep every field traceable to original evidence chunks, enforce strict schema validation on financial numbers, and make human approval an inherent part of the workflow.
