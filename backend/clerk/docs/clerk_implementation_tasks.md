# RepoScroller Administrative Clerk — Autonomous Implementation Tasks

This task manifest maps the **Implementation Plan** and **Roadmap** into **23 discrete, verifiable tasks** formatted for autonomous execution with [CodBot](file:///c:/Dev/codbot).

Each task includes:
- **Unique Identifier (`id`)**: `CLERK-001` through `CLERK-023`
- **Context Files (`context_files`)**: Explicit paths to implementation plans, existing maps, and code
- **Self-Healing Test Commands (`test_command`)**: Shell commands executed automatically by CodBot to verify completion before committing
- **Git Commit Tagging**: Automatic isolated branching (`robot/overnight-YYYYMMDD_HHMMSS`) and commit messages upon pass

---

## Task Matrix Overview

| Phase | Task ID | Title | Key Target / Output |
| :--- | :--- | :--- | :--- |
| **Phase 1: Foundation & 3-URP MVP** | `CLERK-001` | Database Models & Schema Migration | [models.py](file:///c:/Dev/RepoScroller/backend/clerk/models.py) |
| | `CLERK-002` | Pydantic Field Contracts & Swiss Validators | [schemas.py](file:///c:/Dev/RepoScroller/backend/clerk/schemas.py) |
| | `CLERK-003` | 3-URP Form Ingestion & Canonical Resolver | [form_parser.py](file:///c:/Dev/RepoScroller/backend/clerk/form_parser.py) |
| | `CLERK-004` | 3-URP AcroForm PDF Export Service Adapter | [export_service.py](file:///c:/Dev/RepoScroller/backend/clerk/export_service.py) |
| | `CLERK-005` | A2 Answer Orchestrator for 3-URP Evidence | [orchestrator.py](file:///c:/Dev/RepoScroller/backend/clerk/orchestrator.py) |
| **Phase 2: Zurich Tax Declaration** | `CLERK-006` | Zurich Tax Declaration Multi-Schedule Models | [adapters/tax/schemas.py](file:///c:/Dev/RepoScroller/backend/clerk/adapters/tax/schemas.py) |
| | `CLERK-007` | Swiss Bank *eSteuerauszug* Statement Parser | [adapters/tax/steuerauszug.py](file:///c:/Dev/RepoScroller/backend/clerk/adapters/tax/steuerauszug.py) |
| | `CLERK-008` | Deterministic Zurich & Federal Tax Calculation Engine | [adapters/tax/taxcalc_engine.py](file:///c:/Dev/RepoScroller/backend/clerk/adapters/tax/taxcalc_engine.py) |
| | `CLERK-009` | Canton Zurich Deduction Heuristics & Rules Engine | [adapters/tax/swiss_tax_rules.py](file:///c:/Dev/RepoScroller/backend/clerk/adapters/tax/swiss_tax_rules.py) |
| | `CLERK-010` | Multi-Document Cross-Verification & Anomaly Detector | [adapters/tax/copilot_verifier.py](file:///c:/Dev/RepoScroller/backend/clerk/adapters/tax/copilot_verifier.py) |
| **Phase 3: Zurich Social Assistance** | `CLERK-011` | Zurich Social Assistance Schema & Household Model | [adapters/social/schemas.py](file:///c:/Dev/RepoScroller/backend/clerk/adapters/social/schemas.py) |
| | `CLERK-012` | Mandatory Evidence Checklist Verification Engine | [adapters/social/checklist_matcher.py](file:///c:/Dev/RepoScroller/backend/clerk/adapters/social/checklist_matcher.py) |
| | `CLERK-013` | SKOS Monthly Budget Deficit Calculator | [adapters/social/skos_budget.py](file:///c:/Dev/RepoScroller/backend/clerk/adapters/social/skos_budget.py) |
| **Phase 4: Temporal AI Agent Engine** | `CLERK-014` | Temporal `AgentGoalWorkflow` State Machine | [workflows/agent_goal_workflow.py](file:///c:/Dev/RepoScroller/backend/clerk/workflows/agent_goal_workflow.py) |
| | `CLERK-015` | Temporal `ToolActivities` Worker Execution | [activities/tool_activities.py](file:///c:/Dev/RepoScroller/backend/clerk/activities/tool_activities.py) |
| | `CLERK-016` | Human-in-the-Loop Signals & Queries | [workflows/signals.py](file:///c:/Dev/RepoScroller/backend/clerk/workflows/signals.py) |
| | `CLERK-017` | Context Window Compaction Engine | [workflows/compaction.py](file:///c:/Dev/RepoScroller/backend/clerk/workflows/compaction.py) |
| **Phase 5: UI & API Service** | `CLERK-018` | Administrative Workbench FastAPI Endpoints | [api/routes/admin_forms.py](file:///c:/Dev/RepoScroller/backend/api/routes/admin_forms.py) |
| | `CLERK-019` | Field Review Studio UI Component for RepoScroller | [frontend/components/admin_workbench.js](file:///c:/Dev/RepoScroller/frontend/components/admin_workbench.js) |
| | `CLERK-020` | ALCOA+ Audit Ledger & Verification Service | [audit.py](file:///c:/Dev/RepoScroller/backend/clerk/audit.py) |
| **Phase 6: Reusable Knowledge & A3** | `CLERK-021` | Level 1/2/3 Reusable Fact Knowledge Service | [knowledge_service.py](file:///c:/Dev/RepoScroller/backend/clerk/knowledge_service.py) |
| | `CLERK-022` | A3 Targeted Document Research & Knowledge Agent | [agents/research_agent.py](file:///c:/Dev/RepoScroller/backend/clerk/agents/research_agent.py) |
| **Phase 7: End-to-End Hardening** | `CLERK-023` | End-to-End Swiss Administrative Golden Test Suite | [tests/test_golden_forms.py](file:///c:/Dev/RepoScroller/backend/clerk/tests/test_golden_forms.py) |

---

## How to Run with CodBot

In PowerShell from [`c:\Dev\codbot`](file:///c:/Dev/codbot):

```powershell
# 1. Inspect current status (23 pending tasks)
python codbot.py status

# 2. Launch overnight autonomous run targeting RepoScroller
python codbot.py run --target-dir "C:\Dev\RepoScroller" --engine codely

# Or run using Claude CLI engine:
python codbot.py run --target-dir "C:\Dev\RepoScroller" --engine claude
```
