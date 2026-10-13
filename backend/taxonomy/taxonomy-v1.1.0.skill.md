---
name: "reposcroller-taxonomy-v1.1.0"
description: "ALCOA+ Multilingual Taxonomy & Classification Rules (EN, FR, DE) for Dual-Core Institutional (Legal, Financial, Administrative) and Career Research Document Intelligence."
taxonomy_version: "v1.1.0"
version_name: "RepoScroller Dual-Core Institutional & Career Taxonomy"
status: "active"                  # candidate | staging | active | superseded
author: "RepoScroller Architecture Team"
created_date: "2026-10-09"
supported_languages: ["en", "fr", "de"]
embedding_model: "snowflake-arctic-embed2:latest"
vector_dimensions: 1024
source_roots:
  - path: "H:\\My Drive"
    notes: "Primary personal and career transition repository, certifications, qualifications, and personal records."
  - path: "\\\\SyNAS\\xcloud\\LawSuiteRAG"
    notes: "Litigation, dispute dossiers, court records, Swiss legal library (Fedlex, RO/RS), and commercial contracts."
  - path: "L:\\My Drive"
    notes: "Career transition corpus, targeted application dossiers, CV variations, RAV job search, and technical portfolios."
  - path: "\\\\SyNAS\\xcloud\\docs"
    notes: "Institutional records, banking statements, insurance policies, tax filings, and administrative notices."
  - path: "G:\\My Drive"
    notes: "Secondary archives and supplemental document backups."
  - path: "\\\\SyNAS\\CloudSpace\\LexSpace"
    notes: "Analytical legal reports, proceedings, and structured case intelligence."
api_routes:
  list: "GET /api/v1/taxonomy/"
  upsert: "POST /api/v1/taxonomy/categories"
  merge: "POST /api/v1/taxonomy/merge"
  refine: "POST /api/v1/taxonomy/refine"
---

# Taxonomy Skill: Dual-Core Document Intelligence (v1.1.0)

## 1. Domain Mission & Objectives

This skill governs the semantic classification, vector indexing, and lifecycle tracking of institutional and personal documents ingested into RepoScroller across **English, French, and German**.

RepoScroller operates across a **dual-core institutional corpus**:
1. **Career Transition & Professional Assets** (`H:\My Drive`, `L:\My Drive`): Resumes, cover letters, technical portfolios, job descriptions, and qualification records.
2. **Legal, Financial, Administrative & Reference Corpus** (`\\SyNAS\xcloud\LawSuiteRAG`, `\\SyNAS\xcloud\docs`, `\\SyNAS\CloudSpace\LexSpace`): Litigation, contracts, Swiss federal/cantonal statutes, banking statements, insurance policies, cantonal administrative orders, and technical manuals.

The classifier categorizes text extracted from PDFs, Word documents, Markdown files, scanned notices, and spreadsheets into canonical slugs while guaranteeing **ALCOA+ traceability** (Attributable, Legible, Contemporaneous, Original, Accurate).

---

## 2. Five Canonical Thematic Domains & Orthogonal Axes

Every ingested document is classified across **five substantive domains** and an orthogonal **lifecycle axis**:

```
[Domain 1: Career & Professional Dossiers]
├── career_cv (CVs, Resumes, Skill Matrices)
├── career_cover_letter (Targeted Application Letters)
├── career_job_description (Vacancies, Job Postings, Inserate, _JP.pdf)
├── career_portfolio (Engineering Case Studies, Blueprints)
└── career_profile (Executive Biographies, LinkedIn Profiles)

[Domain 2: Legal, Judicial & Legislative Intelligence]
├── legal_contract (Bilateral Contracts, NDAs, Service Agreements)
│   ├── employment_contract (Employment Agreements, Labor Contracts)
│   └── lease_contract (Real Estate Tenancy Agreements - Strictly Constrained)
├── court_order (Tribunal Judgments, Decrees, Bailiff Rulings)
├── statute_legislation (Fedlex, RS, RO, Cantonal & Federal Acts)
├── corporate_governance (Shareholder Assemblies, Board Minutes, Statutes)
└── formal_correspondence (Mises en demeure, Formal Inquiries, Demand Letters)

[Domain 3: Banking, Insurance & Wealth Assets]
├── financial_banking (Bank Statements, Credit/Debit Advices, Mortgages)
├── insurance_policy (Health, Household, Liability, Suva, AXA, Helsana)
├── financial_invoice (Bills, Payment Vouchers, B2B Invoices, Fee Notes)
└── tax_assessment (Steuerveranlagungen, Tax Rulings, Bordereaux Fiscaux)

[Domain 4: Public Administration & Credentials]
├── administrative_order (Road Traffic, Police, RAV, Municipal Notices)
└── identity_credentials (Diplomas, Arbeitszeugnisse, Certifications, IDs)

[Domain 5: Technical Engineering & Reference Knowledge]
├── technical_architecture (Engineering Specs, CDC Blueprints, Code Schemas)
└── technical_reference (Technical Books, Whitepapers, Training Modules)
```

### Orthogonal Lifecycle Status Axis:
- `draft`: Working draft, template, unexecuted document, WIP notes.
- `review`: Circulating, annotated, feedback received.
- `final`: Executed, signed, sent to employer/court, definitive issued statement.
- `superseded`: Replaced by a newer version (e.g. earlier CV draft or prior insurance policy year).
- `truncated`: Partial OCR extraction or preview snippet.

---

## 3. Canonical Categories & Hierarchy (v1.1.0)

| Canonical Slug (`category_id`) | Parent Slug (`parent_id`) | English Label | French Label | German Label |
| :--- | :--- | :--- | :--- | :--- |
| **`career_research`** | *None (Root)* | **Job Search & Career Dossiers** | **Recherche d'emploi & Dossiers de candidature** | **Stellensuche & Bewerbungsdossiers** |
| ├── `career_cv` | `career_research` | Curriculum Vitae & Resumes | CV & Parcours professionnel | Lebenslauf & Résumés |
| ├── `career_cover_letter` | `career_research` | Cover & Motivation Letters | Lettres de motivation & Candidatures | Bewerbungsschreiben & Motivationsbriefe |
| ├── `career_job_description` | `career_research` | Job Descriptions & Vacancies | Fiches de poste & Offres d'emploi | Stellenbeschreibungen & Inserate |
| ├── `career_profile` | `career_research` | Professional Profiles & Bios | Profils professionnels & Bio | Berufsprofile & Kurzbiografien |
| └── `career_portfolio` | `career_research` | Work Portfolios & Case Studies | Portfolios de projets & Réalisations | Arbeitsportfolios & Projektbeispiele |
| **`legal_contract`** | *None (Root)* | **Contracts & Legal Agreements** | **Contrats & Conventions juridiques** | **Verträge & Rechtliche Vereinbarungen** |
| ├── `employment_contract` | `legal_contract` | Employment & Labor Agreements | Contrats de travail & Droit social | Arbeitsverträge & Personalwesen |
| └── `lease_contract` | `legal_contract` | Lease & Real Estate Rental | Bail d'habitation & Location immobilière | Mietverträge & Immobilienpacht |
| **`court_order`** | *None (Root)* | **Court Judgments & Judicial Orders** | **Décisions de justice & Ordonnances** | **Gerichtsentscheide & Verfügungen** |
| **`statute_legislation`** | *None (Root)* | **Legislation, Codes & Official Gazettes** | **Législation, Codes & Recueils officiels** | **Gesetze, Erlasse & Amtliche Sammlungen** |
| **`corporate_governance`** | *None (Root)* | **Corporate Resolutions & Governance** | **Gouvernance & Procès-verbaux de société** | **Unternehmensführung & GV-Protokolle** |
| **`financial_banking`** | *None (Root)* | **Bank Statements & Accounts** | **Relevés bancaires & Comptes financiers** | **Bankauszüge & Finanzkonten** |
| **`insurance_policy`** | *None (Root)* | **Insurance Policies & Coverage** | **Polices d'assurance & Couvertures** | **Versicherungspolicen & Deckungsnachweise** |
| **`financial_invoice`** | *None (Root)* | **Invoices & Accounting Records** | **Factures & Pièces comptables** | **Rechnungen & Buchhaltungsbelege** |
| **`tax_assessment`** | *None (Root)* | **Tax Assessments & Rulings** | **Bordereaux fiscaux & Décisions d'imposition** | **Steuerveranlagungen & Rulings** |
| **`administrative_order`** | *None (Root)* | **Administrative Decisions & Official Notices** | **Décisions administratives & Notifications** | **Verwaltungsentscheide & Behördenverfügungen** |
| **`formal_correspondence`** | *None (Root)* | **Formal Correspondence & Notices** | **Correspondance formelle & Courriers officiels** | **Formelle Korrespondenz & Behördenbriefe** |
| **`identity_credentials`** | *None (Root)* | **Diplomas, Certificates & References** | **Diplômes, Certificats de travail & ID** | **Zeugnisse, Arbeitsbestätigungen & Nachweise** |
| **`technical_architecture`** | *None (Root)* | **Technical Architecture & Specifications** | **Architecture technique & Spécifications** | **Technische Architektur & Spezifikationen** |
| **`technical_reference`** | *None (Root)* | **Technical Reference, Books & Manuals** | **Ouvrages techniques & Documentation** | **Fachliteratur, Handbücher & Lernmaterialien** |

---

## 4. Disambiguation Playbook & Boundary Heuristics

When a document contains ambiguous or overlapping keywords, apply these deterministic precedence rules:

### Rule 4.1: TOP PRIORITY: Curriculum Vitae & Lebenslauf (`career_cv`)
- **Condition**: Filename contains `_CV_`, `_cv_`, `CV_`, `cv_`, `CVdinda`, `Lebenslauf`, `Curriculum_Vitae`, `Resume`, or path resides in a CV directory (`2025-CV`, `2026-CV`, `2025-CV_Tailored`, `2026-CV_Tex`, `\CV\`), and document is not an employer reference letter (*Arbeitszeugnis*, *Certificat de travail*).
- **Resolution**:
  - **Assign `career_cv`** with top precedence (confidence `0.98`).
  - **Forbidden Fallbacks**: Must NEVER be classified as `technical_architecture`, `tax_assessment`, `lease_contract`, or `corporate_governance`.

### Rule 4.2: Storage Root Prioritization (`H:\My Drive`, `L:\My Drive`)
- **Condition**: Document originates from personal/career roots and folder paths containing `Job`, `Career`, `Candidature`, `Bewerbung`, `CV`, `Resume`, `Portfolio`, `RAV`, `Positions`.
- **Resolution**:
  - Prioritize Domain 1 (`career_research`) categories over generic business correspondence.

### Rule 4.3: Cover Letter vs Formal Correspondence
- **Condition**: Document structured as a letter with recipient and sender address.
- **Resolution**:
  - If filename contains `application_letter`, `cover_letter`, `coverletter`, `bewerbungsschreiben`, `motivationsschreiben`, `bewerbung`, or text mentions applying for a vacancy, hiring manager, or motivation ➔ **Assign `career_cover_letter`**.
  - If text concerns a legal claim, payment reminder, contract termination notice, or administrative dispute ➔ **Assign `formal_correspondence`**.

### Rule 4.4: Work Portfolio vs Technical Architecture
- **Condition**: Document describes engineering architectures, software designs, or system schemas.
- **Resolution**:
  - If candidate-authored showcasing personal achievements, case studies, or work samples ➔ **Assign `career_portfolio`**.
  - If impersonal engineering spec, RFC, API schema, or project blueprint for a live system ➔ **Assign `technical_architecture`**.

### Rule 4.5: Job Descriptions & Vacancies vs Employment Agreements & Lease Contracts
- **Condition**: Document outlines role requirements, responsibilities, or vacancy postings (including files ending in `_JP.pdf`, `_jp.pdf`, `JobDescription`, `Stellenbeschreibung`, `Stellenausschreibung`).
- **Resolution**:
  - **Assign `career_job_description`** (`confidence: 0.98`).
  - **STRICT FORBIDDEN FALLBACK**: Must NEVER be classified as `lease_contract` or `employment_contract`.

### Rule 4.6: Swiss Federal & Cantonal Legislation (`statute_legislation`)
- **Condition**: Document originates from Fedlex or contains Swiss legislative codes, such as `fedlex-data-admin-ch`, `RO-202`, `RS-`, `Systematische Rechtssammlung`, `Recueil officiel`, `SR `, `CC `, `CO `, `ZGB`, `OR`, `CP `, `StGB`, `CPC`, `ZPO`.
- **Resolution**:
  - **Assign `statute_legislation`** (`confidence: 0.98`).
  - **STRICT FORBIDDEN FALLBACK**: Must NEVER be classified as `court_order` or `lease_contract`.

### Rule 4.7: Banking & Account Statements (`financial_banking`)
- **Condition**: Filename contains `CRE_P_`, `Kontoauszug`, `Konto`, `Bankauszug`, `hypothek`, or document is issued by a bank (e.g., PostFinance SA, Zuger Kantonalbank, UBS, BCV, Credit Suisse) recording account balances, interest certificates (*Zinsausweis*), credit/debit transaction notices, or mortgage agreements.
- **Resolution**:
  - **Assign `financial_banking`** (`confidence: 0.96`).
  - **Disambiguation vs `financial_invoice`**: Invoices demand future payment for delivered goods/services; banking statements record financial balances and past/current account credits and debits.

### Rule 4.8: Insurance Policies vs Accounting Invoices (`insurance_policy`)
- **Condition**: Document issued by an insurer (e.g., Helsana, AXA, Allianz, Swica, Suva, Groupe Mutuel, Zurich, Helvetia) detailing policy coverage, policy schedules (*Police d'assurance*, *Versicherungspolice*, *Versicherungsvertrag*), general terms of insurance (AVB/CGA), or annual benefit statements.
- **Resolution**:
  - **Assign `insurance_policy`** (`confidence: 0.95`).
  - **Disambiguation vs `financial_invoice`**: Routine monthly premium payment slips go to `financial_invoice`; contractual policies, coverage endorsements, and annual coverage overviews go to `insurance_policy`.

### Rule 4.9: Administrative Decisions vs Court Judgments (`administrative_order`)
- **Condition**: Document issued by an executive public authority rather than a judicial court:
  - Road Traffic Office (*Strassenverkehrsamt*, *Service des automobiles*)
  - Cantonal Police (*Kantonspolizei*)
  - Unemployment Office (*RAV*, *ORP*, *InnoPark*)
  - Social Security / Compensation Office (*SVA*, *Caisse de compensation*, *AHV/AVS*)
  - Municipal Resident Registry (*Einwohnerkontrolle*, *Contrôle des habitants*)
- **Resolution**:
  - **Assign `administrative_order`** (`confidence: 0.94`).
  - **Disambiguation vs `court_order`**: Formal judgments from courts of law (*Tribunal*, *Bezirksgericht*, *Obergericht*, *Cour de justice*) remain `court_order`.

### Rule 4.10: Technical Reference & Books vs Technical Architecture (`technical_reference`)
- **Condition**: Extensive technical reference books (e.g. *Databricks Big Book of GenAI*), academic textbooks, whitepapers, language course units and vocabulary dossiers (`P1 Vocabulary`, `P1U...`), or framework documentation.
- **Resolution**:
  - **Assign `technical_reference`** (`confidence: 0.92`).
  - Impersonal project blueprints and active system architecture specifications retain `technical_architecture`.

### Rule 4.11: Strict Guardrail for Tenancy & Lease Contracts (`lease_contract`)
- **Condition**: Document evaluated for `lease_contract`.
- **Resolution**:
  - A document qualifies as `lease_contract` **ONLY IF** it explicitly contains tenancy markers:
    - French: `bail à loyer`, `contrat de bail`, `bailleur`, `locataire`, `loyer mensuel`, `état des lieux`
    - German: `mietvertrag`, `geschäftsmietvertrag`, `wohnungsmietvertrag`, `vermieter`, `mieter`, `mietzins`, `wohnungsabnahme`
  - In the absence of these explicit rental markers, classification as `lease_contract` is **FORBIDDEN**.

---

## 5. Multilingual Lexical Bridges

```yaml
lexical_bridges:
  statute_legislation:
    en: ["federal act", "statute", "official compilation", "systematic collection of laws", "civil code", "code of obligations", "legislation"]
    fr: ["loi fédérale", "recueil officiel", "recueil systématique", "code civil", "code des obligations", "ordonnance fédérale", "législation"]
    de: ["bundesgesetz", "amtliche sammlung", "systematische rechtssammlung", "zivilgesetzbuch", "obligationenrecht", "verordnung", "gesetzgebung"]

  financial_banking:
    en: ["bank statement", "account statement", "credit advice", "debit advice", "mortgage agreement", "interest certificate", "iban", "postfinance", "account balance"]
    fr: ["relevé bancaire", "extrait de compte", "avis de crédit", "avis de débit", "prêt hypothécaire", "attestation d'intérêts", "postfinance", "solde de compte"]
    de: ["kontoauszug", "bankauszug", "gutschriftsanzeige", "belastungsanzeige", "hypothekarauszug", "zinsausweis", "schuldzinsen", "postfinance", "kontosaldo"]

  insurance_policy:
    en: ["insurance policy", "policy schedule", "certificate of insurance", "general conditions of insurance", "coverage summary", "helsana", "axa", "allianz"]
    fr: ["police d'assurance", "certificat d'assurance", "conditions générales d'assurance", "tableau des garanties", "assurance maladie", "assurance ménage", "helsana", "axa", "allianz"]
    de: ["versicherungspolice", "versicherungsschein", "allgemeine versicherungsbedingungen", "deckungsausweis", "krankenkasse", "hausratversicherung", "helsana", "axa", "allianz"]

  administrative_order:
    en: ["administrative order", "official ruling", "vehicle registration", "driving license notice", "unemployment ruling", "cantonal notice"]
    fr: ["décision administrative", "immatriculation de véhicule", "permis de conduire", "décision orp", "avis cantonal", "contrôle des habitants"]
    de: ["verwaltungsentscheid", "behördliche verfügung", "fahrzeugausweis", "führerausweisverfügung", "rav entscheid", "amtliche mitteilung", "einwohnerkontrolle"]

  technical_reference:
    en: ["technical manual", "handbook", "whitepaper", "textbook", "reference guide", "study guide", "training module"]
    fr: ["manuel technique", "guide de référence", "livre blanc", "support de cours", "module de formation"]
    de: ["handbuch", "fachbuch", "referenzhandbuch", "whitepaper", "schulungsunterlagen", "lernmodul"]
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
| `TC-TAX-11` | *[L:\My Drive\Jobs]* "Madame, Monsieur, Actuellement à l'écoute du marché, je souhaite vous soumettre ma candidature..." | `career_cover_letter` | `final` |
| `TC-TAX-12` | *[L:\My Drive\CV]* "Curriculum Vitae: Senior Solutions Architect & Engineering Lead (15+ Years Experience)..." | `career_cv` | `final` |
| `TC-TAX-13` | *[L:\My Drive\Portfolio]* "Technical Portfolio: End-to-End Enterprise Architecture Case Studies" | `career_portfolio` | `final` |
| `TC-TAX-14` | *[L:\My Drive\Bio]* "Executive Profile: Antoine T. - Specializing in Autonomous AI Agent Workflows" | `career_profile` | `final` |
| `TC-TAX-15` | *[SyNAS\xcloud\LawSuiteRAG]* `fedlex-data-admin-ch-eli-cc-2002-153-20250701-fr-pdf-a.pdf` | `statute_legislation` | `final` |
| `TC-TAX-16` | *[SyNAS\xcloud\docs]* `CRE_P_CH1709000000875861243_1108518228_0_2024122309152963.pdf` (PostFinance) | `financial_banking` | `final` |
| `TC-TAX-17` | *[SyNAS\xcloud\docs]* `2025-10-22-Helsana-Insurance-Policy-Details_Xerox-Scan_20251027104457(3p).pdf` | `insurance_policy` | `final` |
| `TC-TAX-18` | *[H:\My Drive]* `2026-08-18-Strassenverkehrsamt-Kanton-Zürich-registration-véhicule-Vehicle-recall...pdf` | `administrative_order` | `final` |
| `TC-TAX-19` | *[L:\My Drive\Positions]* `925102 Quality System Engineer- Medical Devices_JP.pdf` | `career_job_description` | `final` |
| `TC-TAX-20` | *[H:\My Drive]* `2024-12-10 Databricks-Big-Book-Of-GenAI-FINAL.pdf` | `technical_reference` | `final` |

---

## 7. Vectorial DB & Qdrant Payload Integration

When documents are indexed into Qdrant by `reposcroller.ledger.qdrant_plugin`, each chunk payload inherits the active taxonomy version:

```json
{
  "chunk_id": "8a7c6b5e4d3c2b1a_0",
  "sha256_hash": "8a7c6b5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9f",
  "doc_type": "statute_legislation",
  "taxonomy_version": "v1.1.0",
  "storage_root": "\\\\SyNAS\\xcloud\\LawSuiteRAG",
  "confidence_score": 0.98,
  "canonical_filename": "fedlex-data-admin-ch-eli-cc-2002-153-20250701-fr-pdf-a.pdf",
  "lifecycle_status": "final"
}
```

### Migration & Rollout Policy
1. Deploy skill file to `backend/taxonomy/taxonomy-v1.1.0.skill.md`.
2. Sync categories into `global_taxonomy` via `TaxonomyManager.sync_from_skill()`.
3. Execute dry-run with `TaxonomyEvolutionEngine(target_version="v1.1.0")`.
4. Run automated test suite verifying golden benchmark cases `TC-TAX-01` through `TC-TAX-20`.
5. Apply non-destructive backfill to update `doc_type` and stamp `taxonomy_version = 'v1.1.0'`.
