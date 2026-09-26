---
name: "reposcroller-taxonomy-v1"
description: "ALCOA+ Multilingual Taxonomy & Classification Rules (EN, FR, DE) for Legal, Financial, Corporate, Technical, and Career Research Document Intelligence."
taxonomy_version: "v1.0.0"
version_name: "RepoScroller Baseline Multilingual Taxonomy (with Career Research Axis)"
status: "active"                  # candidate | staging | active | superseded
author: "RepoScroller Architecture Team"
created_date: "2026-09-26"
supported_languages: ["en", "fr", "de"]
embedding_model: "snowflake-arctic-embed2:latest"
vector_dimensions: 1024
source_roots:
  - path: "L:\\My Drive"
    notes: "Primary ingestion repository containing a dense corpus of Career Transition, Application Dossiers, and Professional Portfolios."
api_routes:
  list: "GET /api/v1/taxonomy/"
  upsert: "POST /api/v1/taxonomy/categories"
  merge: "POST /api/v1/taxonomy/merge"
  refine: "POST /api/v1/taxonomy/refine"
---

# Taxonomy Skill: Multilingual Document Intelligence (v1.0.0)

## 1. Domain Mission & Objectives

This skill governs the semantic classification, vector indexing, and lifecycle tracking of institutional and personal documents ingested into RepoScroller across **English, French, and German**.

A significant portion of ingested documents originates from **`L:\My Drive`**, which contains a substantial collection of **Job Research, Career Transition, and Professional Dossier assets** (Curriculum Vitae, targeted cover letters, executive profiles, and technical work portfolios).

The classifier evaluates text extracted from PDFs, Markdown files, Word documents, contracts, filings, and technical schemas, categorizing each document into canonical slugs while guaranteeing **ALCOA+ traceability** (Attributable, Legible, Contemporaneous, Original, Accurate).

---

## 2. Orthogonal Classification Axes

Every ingested document is classified across **four orthogonal axes**:

```
                       [Axis 1: Juridical / Functional Genre]
                     (Agreement | Official Ruling | Accounting Voucher | Spec)
                                      ▲
                                      │
[Axis 3: Lifecycle Status] ───────────┼─────────── [Axis 2: Substantive Domain]
(draft | review | final | superseded) │             (Labor | Tax | Corporate | Tenancy | Tech)
                                      │
                                      ▼
                   [Axis 4: Career Transition & Job Search]
           (CV / Resume | Cover Letter | Professional Profile | Portfolio)
                     *(Predominant on "L:\My Drive")*
```

1. **Axis 1 (Juridical / Functional Nature)**:
   - Bilateral/Multilateral Covenant (`legal_contract`)
   - Unilateral Judicial or Regulatory Decision (`court_order`, `tax_assessment`)
   - Financial Audit Voucher (`financial_invoice`)
   - Administrative Notice (`formal_correspondence`)
   - Engineering Artifact (`technical_architecture`)
   - Personal Credential (`identity_credentials`)
2. **Axis 2 (Substantive Domain)**:
   - Labor & HR (`employment_contract`)
   - Real Estate & Tenancy (`lease_contract`)
   - Corporate Governance & Shareholding (`corporate_governance`)
   - Fiscal & Public Revenue (`tax_assessment`)
3. **Axis 3: Lifecycle Stage**:
   - `draft` (WIP, working draft, template, unexecuted)
   - `review` (circulating, annotated, feedback received)
   - `final` (executed, signed, sent to employer/court, definitive)
   - `superseded` (replaced by a newer CV version, previous cover letter iteration)
   - `truncated` (partial OCR extraction or preview snippet)
4. **Axis 4: Career Transition & Job Research (Crucial for `L:\My Drive`)**:
   - **`career_cover_letter`**: Targeted motivation letters, application pitches, prospecting inquiries.
   - **`career_cv`**: Chronological & functional resumes, technical skill matrices, career timelines.
   - **`career_profile`**: Executive biographies, LinkedIn profile summaries, one-page capability statements.
   - **`career_portfolio`**: Project case studies, system blueprints presented as work samples, design dossiers, code sample walk-throughs.

---

## 3. Baseline Canonical Categories & Hierarchy

| Canonical Slug (`category_id`) | Parent Slug (`parent_id`) | English Label | French Label | German Label |
| :--- | :--- | :--- | :--- | :--- |
| **`career_research`** | *None (Root)* | **Job Search & Career Dossiers** | **Recherche d'emploi & Dossiers de candidature** | **Stellensuche & Bewerbungsdossiers** |
| ├── `career_cv` | `career_research` | Curriculum Vitae & Resumes | CV & Parcours professionnel | Lebenslauf & Résumés |
| ├── `career_cover_letter` | `career_research` | Cover & Motivation Letters | Lettres de motivation & Candidatures | Bewerbungsschreiben & Motivationsbriefe |
| ├── `career_profile` | `career_research` | Professional Profiles & Bios | Profils professionnels & Bio | Berufsprofile & Kurzbiografien |
| └── `career_portfolio` | `career_research` | Work Portfolios & Case Studies | Portfolios de projets & Réalisations | Arbeitsportfolios & Projektbeispiele |
| `legal_contract` | *None (Root)* | Contracts & Legal Agreements | Contrats & Conventions juridiques | Verträge & Rechtliche Vereinbarungen |
| ├── `employment_contract` | `legal_contract` | Employment & Labor Agreements | Contrats de travail & Droit social | Arbeitsverträge & Personalwesen |
| └── `lease_contract` | `legal_contract` | Lease & Real Estate Rental | Bail d'habitation & Location immobilière | Mietverträge & Immobilienpacht |
| `court_order` | *None (Root)* | Court Judgments & Judicial Orders | Décisions de justice & Ordonnances | Gerichtsentscheide & Verfügungen |
| `tax_assessment` | *None (Root)* | Tax Assessments & Rulings | Bordereaux fiscaux & Décisions d'imposition | Steuerveranlagungen & Rulings |
| `corporate_governance` | *None (Root)* | Corporate Resolutions & Governance | Gouvernance & Procès-verbaux de société | Unternehmensführung & Generalversammlungsprotokolle |
| `financial_invoice` | *None (Root)* | Invoices & Accounting Records | Factures & Pièces comptables | Rechnungen & Buchhaltungsbelege |
| `technical_architecture` | *None (Root)* | Technical Architecture & Specifications | Architecture technique & Spécifications | Technische Architektur & Spezifikationen |
| `formal_correspondence` | *None (Root)* | Formal Correspondence & Notices | Correspondance formelle & Courriers officiels | Formelle Korrespondenz & Behördenbriefe |
| `identity_credentials` | *None (Root)* | Diplomas, Certificates & References | Diplômes, Certificats de travail & ID | Zeugnisse, Arbeitsbestätigungen & Nachweise |

---

## 4. Disambiguation Playbook & Boundary Heuristics

When a document contains ambiguous or overlapping keywords, apply these deterministic precedence rules:

### Rule 4.1: Storage Root Heuristic (`L:\My Drive`)

- **Condition**: Document originates from `L:\My Drive` (or folder paths containing `Job`, `Career`, `Candidature`, `Bewerbung`, `CV`, `Resume`, `Portfolio`).
- **Resolution**:
  - The classifier increases the prior probability for **Axis 4 (`career_research`)** categories.
  - If the document contains first-person career history, pitch statements, or references to open positions, prioritize `career_research` over general business correspondence.

### Rule 4.2: Cover Letter vs Formal Correspondence

- **Condition**: Document is structured as a letter with a recipient and sender address.
- **Resolution**:
  - If text mentions a job vacancy, hiring manager, application, enthusiastic motivation (*"I am writing to express my interest in..."*, *"Madame, Monsieur, vivement intéressé par..."*, *"Sehr geehrte Damen und Herren, mit grossem Interesse bewerbe ich mich..."*) ➔ **Assign `career_cover_letter`**.
  - If text concerns a legal claim, payment reminder, contract termination notice, or administrative order ➔ **Assign `formal_correspondence`**.

### Rule 4.3: Work Portfolio vs Technical Architecture

- **Condition**: Document describes engineering architectures, system schemas, or software designs.
- **Resolution**:
  - If the document showcases past personal achievements, client case studies, or is curated as a work sample to demonstrate candidate expertise (*"Portfolio"*, *"Projects Showcase"*, *"Selected Works"*, *"Case Study: How I architected..."*) ➔ **Assign `career_portfolio`**.
  - If the document is an impersonal engineering spec, RFC, API schema, or project blueprint intended for an active development team ➔ **Assign `technical_architecture`**.

### Rule 4.4: CV vs Employment Reference vs Employment Contract

- **Condition**: Document discusses employment dates, duties, and professional skills.
- **Resolution**:
  - Candidate-authored resume or career summary (*Curriculum Vitae*, *Skills*, *Experience*) ➔ **Assign `career_cv`**.
  - Formal reference letter written by a past employer evaluating performance (*Arbeitszeugnis*, *Certificat de travail*) ➔ **Assign `identity_credentials`**.
  - Bilaterally signed legal agreement establishing ongoing employment terms and salary ➔ **Assign `employment_contract`**.

### Rule 4.5: Professional Profile vs CV

- **Condition**: Document summarizes professional background and competencies.
- **Resolution**:
  - Narrative biographical profile, executive summary, speaker bio, or LinkedIn summary export (< 2 pages) ➔ **Assign `career_profile`**.
  - Comprehensive, dated chronological employment and education ledger ➔ **Assign `career_cv`**.

---

## 5. Multilingual Lexical Bridges

The classifier regex and vector search payload index the following tri-lingual terms across English, French, and German:

```yaml
lexical_bridges:
  career_cv:
    en: ["curriculum vitae", "resume", "work experience", "education", "technical skills", "career history"]
    fr: ["curriculum vitae", "cv", "expérience professionnelle", "formation", "compétences clés", "parcours"]
    de: ["lebenslauf", "curriculum vitae", "berufserfahrung", "ausbildung", "fachkenntnisse", "werdegang"]

  career_cover_letter:
    en: ["cover letter", "letter of motivation", "job application", "application for the position of", "dear hiring manager"]
    fr: ["lettre de motivation", "candidature", "dossier de candidature", "postulation", "madame la directrice des ressources humaines"]
    de: ["bewerbungsschreiben", "motivationsschreiben", "bewerbung um die stelle als", "sehr geehrte damen und herren", "stellenantritt"]

  career_profile:
    en: ["professional profile", "executive bio", "about me", "summary of qualifications", "linkedin profile"]
    fr: ["profil professionnel", "résumé exécutif", "biographie professionnelle", "synthèse de compétences", "profil linkedin"]
    de: ["kurzprofil", "berufsprofil", "über mich", "fachprofil", "kompetenzprofil", "linkedin profil"]

  career_portfolio:
    en: ["portfolio", "work samples", "case study", "project showcase", "selected achievements", "design dossier"]
    fr: ["portfolio", "dossier de réalisations", "étude de cas", "projets représentatifs", "échantillons de travail"]
    de: ["portfolio", "arbeitsproben", "projektdokumentation", "fallstudie", "referenzprojekte", "musterarbeiten"]

  identity_credentials:
    en: ["diploma", "degree certificate", "reference letter", "employment certificate", "certification", "transcript"]
    fr: ["diplôme", "certificat de travail", "lettre de recommandation", "attestation", "relevé de notes"]
    de: ["diplom", "arbeitszeugnis", "arbeitsbestätigung", "abschlusszeugnis", "empfehlungsschreiben", "notenspiegel"]

  legal_contract:
    en: ["contract", "agreement", "nda", "service agreement", "covenant", "terms of service"]
    fr: ["contrat", "accord", "convention", "engagement", "avenant", "protocole d'accord"]
    de: ["vertrag", "vereinbarung", "kontrakt", "abkommen", "verpflichtung", "zusatzvereinbarung"]

  employment_contract:
    en: ["employment agreement", "job contract", "salary", "severance", "non-compete clause"]
    fr: ["contrat de travail", "salaire", "employeur", "période d'essai", "clause de non-concurrence"]
    de: ["arbeitsvertrag", "lohn", "anstellung", "probezeit", "konkurrenzverbot", "arbeitsverhältnis"]

  lease_contract:
    en: ["lease", "tenancy agreement", "rent", "tenant", "landlord", "commercial lease"]
    fr: ["bail", "bail à loyer", "loyer", "locataire", "bailleur", "bail commercial"]
    de: ["mietvertrag", "miete", "vermieter", "mieter", "mietzins", "geschäftsmietvertrag"]

  tax_assessment:
    en: ["tax assessment", "tax return", "tax ruling", "withholding tax", "fiscal decision"]
    fr: ["bordereau de taxation", "déclaration d'impôt", "ruling fiscal", "impôt à la source"]
    de: ["steuerveranlagung", "steuererklärung", "steuervorbescheid", "quellensteuer", "einschätzungsentscheid"]
```

---

## 6. Golden Benchmark Suite (Verification & Regression Gate)

Prior to promoting any newly proposed taxonomy version or modified LLM prompt, the test suite (`tests/test_taxonomy_eval.py`) must run this golden benchmark set and achieve **≥ 95% classification precision**:

| Test ID | Document Anchor / Snippet (Source / Path) | Expected Category | Expected Lifecycle |
| :--- | :--- | :--- | :--- |
| `TC-TAX-01` | "Employment Agreement between ACME AG and Jane Doe. Base Salary CHF 140'000." | `employment_contract` | `final` |
| `TC-TAX-02` | "Geschäftsmietvertrag: Mieträume an der Bahnhofstrasse 10, 8001 Zürich. Monatszins CHF 4'500." | `lease_contract` | `final` |
| `TC-TAX-03` | "Kantonales Steueramt Zürich: Definitive Staats- und Gemeindesteuern 2024. Veranlagung..." | `tax_assessment` | `final` |
| `TC-TAX-04` | "Procès-verbal de l'Assemblée Générale Ordinaire des Actionnaires tenue le 15 mars 2025." | `corporate_governance` | `final` |
| `TC-TAX-05` | "Rechnung Nr. 2025-8849: Beratungsleistungen für Cloud-Migration. Total fällig: EUR 12'400." | `financial_invoice` | `final` |
| `TC-TAX-06` | "Tribunal de Première Instance de Genève - Jugement civil JTPI/1234/2024..." | `court_order` | `final` |
| `TC-TAX-07` | "RepoScroller Technical Architecture Specification & CDC Pipeline Blueprint (Draft v0.3)" | `technical_architecture` | `draft` |
| `TC-TAX-08` | "Mise en demeure avec sommation de payer avant poursuite sous 10 jours." | `formal_correspondence` | `final` |
| `TC-TAX-09` | "Arbeitszeugnis für Frau Dr. Maria Muster: Wir haben sie als verlässliche..." | `identity_credentials` | `final` |
| `TC-TAX-10` | "Master Mutual Non-Disclosure and Confidentiality Agreement (Unexecuted Draft)" | `legal_contract` | `draft` |
| `TC-TAX-11` | *[L:\My Drive\Jobs]* "Madame, Monsieur, Actuellement à l'écoute du marché, je souhaite vous soumettre ma candidature pour le poste de..." | `career_cover_letter` | `final` |
| `TC-TAX-12` | *[L:\My Drive\CV]* "Curriculum Vitae: Senior Solutions Architect & Engineering Lead (15+ Years Experience in Cloud & GraphRAG)..." | `career_cv` | `final` |
| `TC-TAX-13` | *[L:\My Drive\Portfolio]* "Technical Portfolio: End-to-End Enterprise Architecture Case Studies & Microservice Migration Samples" | `career_portfolio` | `final` |
| `TC-TAX-14` | *[L:\My Drive\Bio]* "Executive Profile: Antoine T. - Specializing in Autonomous AI Agent Workflows and Distributed Systems" | `career_profile` | `final` |

---

## 7. Vectorial DB & Qdrant Payload Integration

When documents are indexed into Qdrant by `reposcroller.ledger.qdrant_plugin`, each chunk payload inherits the active taxonomy version and career research attributes:

```json
{
  "chunk_id": "8a7c6b5e4d3c2b1a_0",
  "sha256_hash": "8a7c6b5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9f",
  "doc_type": "career_cover_letter",
  "taxonomy_version": "v1.0.0",
  "storage_root": "L:\\My Drive",
  "confidence_score": 0.96,
  "canonical_filename": "Lettre_Motivation_Lead_Architect_2025.pdf",
  "lifecycle_status": "final"
}
```

### Migration Policy for Future Versions (e.g. `v2.0.0`)

1. Candidate skill maintained at `taxonomy/taxonomy-v2.0.0.skill.md`.
2. New career subtypes (e.g., separating `academic_publications` or `code_repositories`) registered via `POST /api/v1/taxonomy/categories`.
3. Outdated documents detected via `WHERE taxonomy_version != 'v2.0.0'`.
4. Dry-run simulation executed with the Golden Benchmark Suite.
5. In-place metadata patch applied via Qdrant `set_payload` (0ms vector recomputation).
6. Immutable audit log stamped with ALCOA+ attestation.
