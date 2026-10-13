Searched for "triggerPortraitSynthesis"
Viewed app.js:7580-7660
Viewed app.js:7770-7815
Searched for "/dossier/generate"
Searched for "/generate"
Viewed dossier.py:580-640

To make querying, visualizing, and exporting all court decisions across **Kantonsgericht, Obergericht, and Staatsanwaltschaft** over the 7-year window (2019–2026) effortless, here is the end-to-end design and implementation blueprint:

---

### 1. Architectural Workflow

```
[ 1-Click "⚖️ Judicial (7Y)" Preset ] 
               │
               ▼
[ 3D Time Tunnel (layout="timeline") ] ──► Chronological Urgency Tunnel (2019–2026)
               │                             • Nodes mapped along Z-axis by judgment date
               │                             • Grouped by judicial instance
               ▼
[ Portrait & Risk Dossier Synthesis ] ──► Ollama/LLM Dual-Core Synthesis
               │                             • Chronological summary of all rulings
               │                             • Legal statute mapping (ZPO, StGB, SchKG)
               ▼
[ Export Markdown Report (.md) ]       ──► Direct download: `Portrait_Judicial_Dossier_2019_2026.md`
```

---

### 2. Implementation Steps

#### A. Add a 1-Click "Judicial Lens" Button to the 3D HUD & Ledger

In [`frontend/index.html`](file:///c:/Dev/RepoScroller/frontend/index.html) (inside the HUD topology/filter controls):

```html
<button id="btn-lens-court" class="hud-glsl-btn" onclick="activateJudicialTunnelPreset()" 
        title="Filter all court decisions (Kantonsgericht, Obergericht, StA) over 7 years in Time Tunnel">
  <span>⚖️</span> <span>Judicial 7Y Lens</span>
</button>
```

In [`frontend/app.js`](file:///c:/Dev/RepoScroller/frontend/app.js):

```javascript
/**
 * 1-Click preset to isolate judicial decisions over 7 years in the Time Tunnel.
 */
function activateJudicialTunnelPreset() {
  // 1. Switch layout to Time Tunnel
  set3DUniverseLayout("timeline");

  // 2. Set multi-entity search query matching the courts
  const query = "obergericht kantonsgericht staatsanwaltschaft urteil gericht";
  
  // 3. Request 3D graph universe with court filter
  fetch3DGraphUniverse(1500, {
    layout: "timeline",
    type: "court_order",
    theme: "theme_legal_justice",
    q: query
  });

  showToast("⚖️ Loaded 7-Year Judicial Time Tunnel (2019–2026)", "success", 4000);
}
window.activateJudicialTunnelPreset = activateJudicialTunnelPreset;
```

---

#### B. Visualize in the Time Tunnel (2019–2026)

* The backend [`get_3d_knowledge_universe(layout="timeline", filters={"type": "court_order"})`](file:///c:/Dev/RepoScroller/backend/ledger/graph_store.py#L1138) automatically retrieves all `court_order` documents in `document_ledger` and links them to `theme_legal_justice`.
* In [`frontend/app.js`](file:///c:/Dev/RepoScroller/frontend/app.js#L4363), `computeTimelineZ(date)` continuously maps each judgment along the Z-axis tunnel:
  * **2026 (Recent/Active Decisions)** &rarr; $Z \approx +20$ to $+5$
  * **2023–2025 (Mid-term Proceedings)** &rarr; $Z \approx -50$ to $-120$
  * **2019–2022 (Foundation Cases)** &rarr; $Z \approx -180$ to $-260$
* The camera aligns down the tunnel, giving a clear perspective through 7 years of court history.

---

#### C. 1-Click Export to a Comprehensive Markdown Report

To generate the structured Markdown dossier directly from the 7-year collection:
In [`frontend/app.js`](file:///c:/Dev/RepoScroller/frontend/app.js):

```javascript
/**
 * Synthesizes an executive Markdown dossier of all court proceedings over 7 years.
 */
function exportJudicialPortraitReport() {
  // Trigger portrait dossier synthesis on the root judicial theme
  triggerPortraitSynthesis("theme_legal_justice", "Judicial & Court Proceedings (7 Years)");
}
window.exportJudicialPortraitReport = exportJudicialPortraitReport;
```

The backend [`POST /api/v1/dossier/generate`](file:///c:/Dev/RepoScroller/backend/api/routes/dossier.py#L584) compiles:

1. **Executive Chronology**: Chronological list of rulings from Kantonsgericht, Obergericht, and Staatsanwaltschaft.
2. **Relational Mermaid Diagram**: Visual chart connecting authorities to cases, persons, and counterparties.
3. **Statutory Foundations**: Articles cited (e.g. Art. 308 ZPO, Art. 303 StGB, SchKG debt actions).
4. **Friction Points & Outstanding Obligations**: Active appeals, unresolved fines, and compliance deadlines.

Clicking the existing **"📥 Download Markdown"** button in the Dossier Modal downloads:

```text
Portrait_Judicial___Court_Proceedings__7_Years_.md
```

---

### 3. Updated Declarative Scenario Benchmark

To ensure this contract is continually tested in your test suite, [`case_court_orders_time_tunnel.yaml`](file:///c:/Dev/RepoScroller/backend/tests/scenarios/case_court_orders_time_tunnel.yaml) can be expanded to cover the 7-year scope:

```yaml
# backend/tests/scenarios/case_court_orders_time_tunnel.yaml
use_case: "Time Tunnel - Court Decision Documents"
scenario: "Filter, visualize in the 3D Time Tunnel, and export court documents over 7 years"

input:
  filename: "2024-03-15-Obergericht-Zug-Urteil-Zivilabteilung.pdf"
  doc_type_raw: "gerichtsurteil"
  text_snippet: "Urteil des Obergerichts des Kantons Zug betreffend Zivilklage und Rechtsöffnung gemäss Art. 308 ZPO."
  query_filter:
    layout: "timeline"
    type: "court_order"
    theme: "theme_legal_justice"
    authorities:
      - "Obergericht Zug"
      - "Kantonsgericht Zug"
      - "Staatsanwaltschaft Zug"
    time_window_years: 7
    min_date: "2019-01-01"
    max_date: "2026-12-31"

expected:
  canonical_category: "court_order"
  macro_theme: "theme_legal_justice"
  entities:
    - { type: "organization", name: "Obergericht Zug" }
    - { type: "statute", name: "Art. 308 ZPO" }
  time_tunnel:
    layout: "timeline"
    axis_z: "Chronological Urgency Timeline (Z-Tunnel)"
    min_date: "2019-01-01"
    max_date: "2026-12-31"
    doc_type: "court_order"
    min_returned_documents: 1
    export_format: "markdown_dossier"
```

Running `python -m pytest backend/tests/test_use_cases.py` verifies this scenario against the database and extractor.
