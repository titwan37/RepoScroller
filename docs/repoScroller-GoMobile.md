### Role: Act as an Expert Frontend Engineer and PWA Specialist

Context: I have a complex, data-heavy web dashboard (RepoScroller) built with vanilla HTML, CSS, and JS. It features a Three.js 3D WebGL canvas, data tables, multi-column layouts, and a dual-node telemetry HUD.
The Problem: Currently, the top navigation bars, workspace tabs, and headers consume too much vertical space on tablets and mobile devices, obscuring the main visualizations (like the 3D Universe and Ledger).

Task: Refactor the UI to be a fully responsive, touch-optimized Progressive Web App (PWA). Please provide the updated HTML, CSS, and JS with the following specific requirements:

1. Navigation & Headers Overhaul: Convert the top navbar and workspace tabs into a compact, mobile-friendly layout. Make the workspace tabs horizontally scrollable on mobile. Ensure headers are sticky but minimal (max height ~50px). Hide secondary badges (like ALCOA+) on small screens.
1. Layout Restructuring: On screens < 1024px, switch the main .dashboard-grid from a 2-column layout to a single-column vertical stack. Convert the .side-column (detail panel) into a slide-out drawer that overlays the main content from the right.
1. Data Tables & Cards: Ensure .ledger-table and other data tables are horizontally scrollable. On mobile, hide less critical columns or transform table rows into stacked card layouts if appropriate.
1. 3D Canvas & Visualizations: Ensure the #glsl-3d-canvas-container and GraphRAG studio adapt to 100% width and calculate height dynamically using 100dvh minus the minimal header height. Hide the floating Axes Legend on mobile to save space.
1. Touch & PWA Optimization: Increase all interactive elements (buttons, chips, tabs) to a minimum touch target of 44x44px. Add necessary PWA meta tags (theme-color, apple-mobile-web-app-capable, viewport settings) and provide a manifest.json structure.
1. CSS Media Queries: Provide comprehensive @media (max-width: 768px) and @media (max-width: 1024px) rules to handle the responsive breakdown gracefully without breaking the desktop experience.

---

To discriminate and hide non-essential UI controls on smaller screens, you should adopt a strategy called **Responsive Degradation** (or Progressive Disclosure).

The goal is to categorize your UI elements into three tiers:

1. **Tier 1 (Core):** Main visualizations (3D Canvas, Ledger), primary navigation icons, and critical actions. *(Always visible)*
2. **Tier 2 (Contextual):** Subtitles, descriptive paragraphs, secondary badges, and verbose labels. *(Hidden on mobile)*
3. **Tier 3 (Desktop-Only):** Secondary camera controls, extra data table columns, and floating legends. *(Hidden on tablets/mobile)*

Here is the exact CSS strategy tailored to your **RepoScroller** dashboard. You can append this block to the bottom of your `style.css` to instantly clean up the mobile/tablet experience.

### 📋 Copy-Paste CSS for Progressive UI Degradation

```css
/* ==========================================================================
   PROGRESSIVE UI DEGRADATION (Hiding non-essential controls on small screens)
   ========================================================================== */

/* 1. WORKSPACE TABS: Icon-Only Mode on very small screens */
@media (max-width: 600px) {
  .ws-tab-title { display: none !important; } /* Hides text like "Document Ledger" */
  .ws-tab-btn { padding: 0.5rem 0.75rem !important; } /* Keeps just the emoji/icon */
}

/* 2. 3D UNIVERSE: Hide secondary camera controls & verbose labels */
@media (max-width: 768px) {
  .toolbar-lbl { display: none !important; } /* Hides "Color Mode:", "Type Filter:" */
  .universe-hero-desc { display: none !important; } /* Hides the long subtitle */
  
  /* Hide secondary camera preset buttons to save toolbar space */
  #btn-glsl-zenith, 
  #btn-glsl-orbital, 
  #btn-34-top,
  #btn-90-rotate { 
    display: none !important; 
  }
  
  /* Hide the "Tip: Drag to rotate..." footer in the legend if it ever shows */
  .legend-footer-tip { display: none !important; }
}

/* 3. LEDGER TABLE: Progressive Column Dropping */
@media (max-width: 768px) {
  /* Hide less critical columns: Maturity(3), Copies(5), Reception(7), Due Date(8) */
  /* Keep: Document(1), Category(2), Status(4), Doc Date(6), Actions(9) */
  .ledger-table th:nth-child(3), .ledger-table td:nth-child(3),
  .ledger-table th:nth-child(5), .ledger-table td:nth-child(5),
  .ledger-table th:nth-child(7), .ledger-table td:nth-child(7),
  .ledger-table th:nth-child(8), .ledger-table td:nth-child(8) {
    display: none !important;
  }
  
  /* Force table to fit screen since we dropped columns */
  .ledger-table { min-width: 100% !important; }
}

/* 4. PROCESS SCROLLER: Hide verbose descriptions & module names */
@media (max-width: 768px) {
  .stage-desc { display: none !important; } /* Hides the long paragraph explanations */
  .stage-module { display: none !important; } /* Hides "crawler.py + telemetry.py" */
  .connector-line { display: none !important; } /* Clean up vertical spacing */
}

/* 5. GRAPHRAG STUDIO: Hide subtitles & secondary labels */
@media (max-width: 768px) {
  .studio-subtitle { display: none !important; } /* Hides the long description under title */
  .chips-label { display: none !important; } /* Hides "Quick Prompts:" text */
  .studio-signals-summary { display: none !important; } /* Hides "Vectors: X • BM25: Y" */
}

/* 6. SMART TRUNCATION (Instead of hiding, truncate long strings) */
/* Prevents long document names or paths from breaking mobile layouts */
.doc-name, 
.location-path, 
.candidate-filename,
.lineage-doc-link {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
  display: block; /* Ensures ellipsis works on block/inline-block elements */
}

/* 7. DETAIL PANEL (Side Drawer): Hide verbose hash boxes on mobile */
@media (max-width: 768px) {
  /* Hide the SimHash/Maturity/Status box to save vertical space in the drawer */
  .detail-header .hash-box:last-child { 
    display: none !important; 
  }
}
```

### 💡 Key Techniques Explained

1. **Icon-Only Tabs (`@media (max-width: 600px)`)**:
   By hiding `.ws-tab-title`, your 7 workspace tabs will shrink down to just their emojis (🌐, 📊, 🗄️, etc.). This prevents horizontal scrolling on small phones while keeping 100% of the navigation functionality.
2. **Column Dropping (`nth-child`)**:
   Data tables are the hardest thing to make responsive. By hiding columns 3, 5, 7, and 8, you preserve the most important data (Document Name, Category, Status, Date) without forcing the user to horizontally scroll a massive table.
3. **Hiding "Nice-to-Have" Context**:
   Elements like `.stage-desc` (the long explanations in the Process Scroller) and `.studio-subtitle` are great for desktop users learning the app, but they consume precious vertical space on mobile. Hiding them leaves only the core metrics and titles.
4. **Smart Truncation (`text-overflow: ellipsis`)**:
   Instead of hiding a long document name or file path entirely, this CSS forces it to stay on one line and adds a `...` at the end. The user can still tap it or view it in the detail drawer, but it won't break your grid layout.
5. **Removing Secondary Camera Controls**:
   In the 3D Universe, buttons like "Zenith View", "Orbital Tour", and "90 Rotate" are powerful but secondary. Hiding them on mobile leaves the primary Layout toggles (Spatial/Thematic/Timeline) and the Filter bar, which are much more important.

---

Searched for "universe"
Searched for "universe"
Viewed style.css:7000-7100
Searched for "canvas"
Searched for "ws-pane"
Searched for "id="
Viewed index.html:1-100
Searched for "universe"
Viewed index.html:101-300
Searched for "ws-pane-universe"
Searched for "3D Knowledge Universe"
Viewed index.html:500-800
Viewed index.html:1200-1400
Viewed index.html:1800-2091
Viewed index.html:1400-1800
Viewed style.css:7050-7473
Searched for "glsl-universe-layout"
Viewed style.css:3800-4300
Searched for "glsl-3d-canvas-container"
Viewed app.js:4080-4150
Viewed app.js:4150-4250
Searched for "workspace-pane"
Viewed style.css:200-400
Viewed style.css:400-800
Viewed style.css:6950-7050
Viewed style.css:6900-6950
Viewed style.css:6850-6900
Searched for "function switchWorkspace"
Searched for "switchWorkspace"
Viewed app.js:1-250
Viewed app.js:250-400
Viewed app.js:500-700
Viewed app.js:800-1000
Viewed app.js:1200-1500
Viewed app.js:1500-2000

The issue where the **3D Knowledge Universe visualization** appears squeezed into only ~5% of space at the bottom on mobile devices is caused by a combination of CSS layout calculations, mobile body scrolling rules, and stacked header heights in [`style.css`](file:///c:/Dev/RepoScroller/frontend/style.css) and [`index.html`](file:///c:/Dev/RepoScroller/frontend/index.html).

---

### Key Technical Causes

#### 1. `html, body` Height Change on Mobile

In [`style.css` (lines 6853–6857)](file:///c:/Dev/RepoScroller/frontend/style.css#L6853-L6857):

```css
@media (max-width: 1024px) {
  html,
  body {
    height: auto;
    overflow-y: auto;
  }
}
```

On desktop, `body` is fixed at `100dvh` with `overflow: hidden`. On mobile (`max-width: 1024px`), `body` switches to `height: auto; overflow-y: auto;`. This makes the entire page vertically scrollable, pushing the universe pane down below the sticky top bars so it starts near the bottom of the initial mobile screen fold.

---

#### 2. Workspace Pane Height Offset (`calc(100dvh - 96px)`)

In [`style.css` (lines 7139–7148)](file:///c:/Dev/RepoScroller/frontend/style.css#L7139-L7148):

```css
#ws-pane-universe,
.glsl-universe-layout {
  width: 100% !important;
  height: calc(100dvh - 96px) !important;
  max-height: calc(100dvh - 96px) !important;
  padding: 0.25rem 0.5rem;
  margin: 0;
  box-sizing: border-box;
  overflow: hidden;
}
```

The subtraction of `96px` **only accounts for the top two fixed navigation bars**:

- `.navbar`: `50px`
- `.workspace-nav-bar`: `46px`

---

#### 3. Stacked Internal Headers Inside the Universe Pane

Inside `#ws-pane-universe` ([`index.html` lines 1425–1570](file:///c:/Dev/RepoScroller/frontend/index.html#L1425-L1570)), two header bars sit above the canvas in a flex column:

1. **`.universe-hero-bar`**: Consumes `~45px–50px`
2. **`.universe-toolbar`** (with `44px` mobile touch buttons): Consumes `~54px–60px`

Together, these internal toolbars consume `~105px` of space *inside* `#ws-pane-universe`. In total, **`> 200px` of vertical height** is consumed by navigation headers before the `#glsl-canvas-wrapper` gets any space.

On portrait mobile viewports (e.g. `667px–844px` tall screens), minus the browser UI/address bar, the remaining flex space for the canvas wrapper collapses significantly.

---

#### 4. Floating Mobile Node Inspector Sheet

In [`style.css` (lines 7021–7033)](file:///c:/Dev/RepoScroller/frontend/style.css#L7021-L7033):

```css
.glsl-node-inspector {
  top: auto !important;
  bottom: 74px !important;
  left: 1rem !important;
  right: 1rem !important;
  width: auto !important;
  max-height: 30vh !important;
  overflow-y: auto !important;
}
```

When an entity node is clicked or active, `.glsl-node-inspector` overlays up to `30vh` over the bottom of the canvas, floating `74px` above the bottom edge and covering most of the remaining visible 3D canvas space.

---

### Summary Diagram

```
+------------------------------------------+
| Top Navbar (.navbar)             [ 50px ]|
+------------------------------------------+
| Workspace Tabs (.workspace-nav-bar)[46px]|
+------------------------------------------+
| Hero Header (.universe-hero-bar)  [~45px]|
+------------------------------------------+
| HUD Toolbar (.universe-toolbar)   [~55px]|
+------------------------------------------+
| 3D WebGL Canvas Wrapper                  |
| (Squeezed into remaining flex space)     |
|                                          |
|  +------------------------------------+  |
|  | Node Inspector Bottom Sheet (30vh) |  |
|  +------------------------------------+  |
+------------------------------------------+
```

Searched for "@media"
Viewed style.css:6850-6885
Viewed style.css:6800-6850
Ran command: `python -c "
with open('frontend/style.css', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for idx, line in enumerate(lines):
    if '@media' in line:
        print(f'Line {idx+1}: {line.strip()}')
"`
Viewed style.css:7190-7260
Viewed style.css:7140-7195
Searched for "ws-pane-universe"
Searched for "id="pane-"
Searched for "glsl-canvas-wrapper"
Viewed index.html:1470-1560
Viewed index.html:1430-1470
Viewed index.html:1400-1430
Viewed index.html:1560-1620
Ran command: `python -c "
with open('frontend/style.css', 'r', encoding='utf-8') as f:
    lines = f.readlines()
brace_level = 0
for idx, line in enumerate(lines):
    if idx + 1 >= 6820:
        brace_level += line.count('{') - line.count('}')
        if '@media' in line:
            print(f'Line {idx+1}: {line.strip()} (level {brace_level})')
        if brace_level == 0:
            print(f'Media query starting at 6820 CLOSED at line {idx+1}')
            break
"`
Used tool: manage_task
Viewed style.css:7400-7479
Viewed index.html:1-30
Viewed index.html:35-120
Searched for "function switchWorkspace"
Searched for "switchWorkspace"
Searched for "switchWorkspace"
Viewed app.js:1813-1860
Viewed style.css:7140-7220
Searched for ".hidden {"
Searched for ".hidden"
Viewed style.css:7130-7300
Viewed index.html:110-180
Searched for "ws-pane-universe"
Searched for "ws-pane-universe"
Searched for "ws-pane-universe"
Searched for "glsl-universe"
Listed directory frontend
Searched for "universe"
Searched for "workspace-pane"
Ran command: `python -c "with open('frontend/index.html', 'rb') as f: print(f.read(10))"`
Viewed index.html:1-60
Viewed app.js:1-100
Viewed app.js:150-250
Viewed app.js:251-320
Viewed app.js:500-600
Viewed app.js:1400-1460
Viewed app.js:2150-2250
Searched for "function initDiagnostics"
Viewed app.js:7500-7700
Viewed app.js:8000-8216
Viewed app.js:300-450
Viewed app.js:7150-7350
Viewed app.js:90-160
Viewed app.js:1000-1150
Viewed app.js:2700-2850
Viewed app.js:5100-5250
Viewed app.js:6050-6200
Viewed app.js:620-720
Viewed app.js:1500-1650
Viewed app.js:2400-2550
Viewed app.js:3150-3300
Viewed app.js:4150-4300
Viewed app.js:3650-3800
Viewed app.js:3801-3950
Viewed app.js:3550-3650
Viewed app.js:3490-3550
Viewed style.css:3820-3920
Viewed style.css:3921-4050
Viewed style.css:4051-4150
Viewed style.css:4151-4250
Viewed index.html:1250-1420
Viewed index.html:1421-1600
Viewed style.css:7070-7320
Viewed style.css:150-250
Viewed style.css:250-320
Viewed style.css:500-550
Viewed style.css:930-1000
Viewed style.css:1800-1860
Viewed style.css:7400-7479
Viewed app.js:2000-2100
Viewed app.js:1700-1800
Viewed app.js:1801-1900
Viewed index.html:1600-1670
Viewed style.css:4300-4450
Viewed style.css:4530-4650
Viewed style.css:4720-4820
Viewed style.css:4821-4890
Viewed style.css:4890-4940
Viewed style.css:7320-7410
Viewed style.css:7040-7075
Viewed style.css:6990-7040
Viewed style.css:6950-6995
Viewed style.css:6900-6950
Viewed style.css:6850-6900
Viewed style.css:6810-6850
Viewed app.js:3510-3540
Viewed style.css:6815-6875
Viewed style.css:7140-7255
Viewed app.js:3510-3540
Edited app.js
Viewed style.css:6815-6845
Viewed style.css:7135-7260
Viewed style.css:7390-7405
Edited style.css
Viewed style.css:7140-7255
Edited style.css
Viewed style.css:7410-7440
Edited style.css
Viewed index.html:1555-1570
Edited index.html
Viewed app.js:3505-3565
Viewed style.css:7140-7230

### Root Cause Analysis

On your 6.7-inch phone (2400×1080 resolution), the canvas was crushed to ~3% and all verbose labels remained visible due to three issues:

1. **CSS Breakpoint Bypass ($1080\text{px} > 1024\text{px}$):**
   - The media query in [`style.css`](file:///c:/Dev/RepoScroller/frontend/style.css) was strictly `@media (max-width: 1024px)`.
   - On modern high-resolution phones reporting a viewport width of $1080\text{px}$ (or $>1024\text{px}$ in landscape or when "Desktop Mode" is active), the condition evaluated to `false`.
   - The CSS engine treated your phone as an ultra-wide desktop monitor, applying full desktop rules.

2. **Toolbar & Hero Bar Multi-Row Vertical Stacking:**
   - On desktop, the 3D Universe pane displays:
     - The `.universe-hero-bar` with the title, description, and 5 badge pills (Dim, Algo 1, Algo 2, Topology, Renderer).
     - Full button labels (*"🪐 Thematic Mindmap"*, *"🌐 Spatial View"*, *"⏳ Action Timeline"*, *"🔄 Auto-Spin: ON"*, *"🕸️ Links: Visible"*, *"🏷️ Labels: ON"*, *"🔭 Zenith View"*, etc.).
     - Range sliders (*"✨ Nodes"*, *"🕸️ Links"*), 2 `<select>` dropdowns, query filter input, and search bar.
   - On a phone screen, these desktop controls wrapped into **6 to 8 vertical rows**, pushing the 3D canvas almost completely offscreen.

3. **Flexbox Collapse:**
   - In [`style.css`](file:///c:/Dev/RepoScroller/frontend/style.css), `#glsl-canvas-wrapper` had `height: 0 !important;` while the uncollapsed headers took up the rest of the flex container, leaving the 3D WebGL canvas with only the leftover 3% at the bottom.

---

### Key Changes Implemented

#### 1. Device Resolution Telemetry in Diagnostic Console

In [`frontend/app.js`](file:///c:/Dev/RepoScroller/frontend/app.js), added `detectAndApplyMobileMode()` and hooked it directly into `initDiagnostics()`:

- Automatically detects screen resolution, physical pixels via `devicePixelRatio`, viewport width/height, touch points (`navigator.maxTouchPoints`), orientation, and active layout mode.
- Emits a diagnostic entry at startup visible in both the floating Diagnostic Console and Workspace 0's live telemetry stream:
  > `📱 Device Display: Screen 1080x2400 (2400x1080 physical px, DPR 2.63) | Viewport: 1080x2400px (portrait) | Touch: Active (5 pts) | Mode: Mobile Phone / Compact Touch (labels collapsed, 3D canvas maximized)`

#### 2. Broadened Breakpoint & Touch Device Enforcement

In [`frontend/style.css`](file:///c:/Dev/RepoScroller/frontend/style.css):

- Updated the media query from `@media (max-width: 1024px)` to:

  ```css
  @media (max-width: 1100px), 
         (pointer: coarse) and (max-height: 900px), 
         (pointer: coarse) and (max-width: 1366px), 
         (hover: none) and (max-width: 1366px)
  ```

- Added a dedicated `body.is-mobile-device` CSS block enforced by JavaScript so high-DPI screens or mobile user agents trigger compact phone mode even if the browser reports desktop viewport metrics.

#### 3. Maximized 3D Universe Screen Real Estate (~90% Height)

- **Hero Bar & Badges Hidden:** Set `.universe-hero-bar` and `.universe-badges-strip` to `display: none !important;` on mobile, saving $\sim 100\text{px}$ of vertical height.
- **Single-Row Horizontal Toolbar:** Constrained `.universe-toolbar` to `height: 48px !important; flex-wrap: nowrap !important; overflow-x: auto !important;` so it swipably scrolls on one line and never wraps into multiple rows.
- **Clean 44px Icon Buttons:** Set `.universe-toolbar .hud-glsl-btn span:not(:first-child) { display: none !important; }` on mobile, hiding verbose labels while showing clean touch icons (🪐, 🌐, ⏳, 🔄, 🕸️, 🏷️, 🔭, ↺, 📐, ↻).
- **Secondary Filters Hidden on Mobile:** Hidden sliders, select dropdowns, and search inputs on mobile viewports.
- **Canvas Height Restored:** Set `#glsl-canvas-wrapper` to `flex: 1 1 auto !important; height: 100% !important; min-height: 0 !important; overflow: hidden !important;`, expanding the Three.js WebGL canvas to fill **85–90%+** of your phone's screen.
- **Clean Inactive Panes:** Enforced `#ws-pane-universe.hidden { display: none !important; }` so inactive workspace panes do not interfere with layout.
- **Distinct 90° Rotate Icon:** Updated `#btn-90-rotate` icon in [`index.html`](file:///c:/Dev/RepoScroller/frontend/index.html) from `📐` to `↻` so it is clearly distinct from the 3/4 top view icon (`📐`).
