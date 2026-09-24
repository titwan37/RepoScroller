/**
 * RepoScroller Web Dashboard Client
 * Complete interactive ledger with duplicate filtering, sortable columns,
 * dynamic multilingual taxonomy filtering, and local file launch/reveal.
 */

let activeDocumentSha = null;
let watcherRunning = false;

// Filter and sorting state
let filterOnlyDuplicates = false;
let activeSortBy = "doc_date";
let activeSortOrder = "DESC";
let activeCategory = "";
let searchFilterQuery = "";
let searchDebounceTimer = null;
let cachedLedgerItems = [];

// ==========================================
// Diagnostic Console State & Interceptors
// ==========================================
let diagLogs = [];
let diagFilter = "all";
let diagSearchQuery = "";
let diagConsoleOpen = false;
let diagMaximized = false;
let diagWatermarkId = 0;
let diagPollTimer = null;
let diagHealthTimer = null;
let isReportingClientIssue = false;

// Global Frontend Exception Interceptor
window.addEventListener("error", (event) => {
  const errMsg = event.message || "Uncaught script exception";
  const errStack = event.error && event.error.stack ? event.error.stack : `${event.filename || 'unknown'}:${event.lineno}:${event.colno}`;
  logDiagnosticEntry({
    source: "frontend",
    level: "ERROR",
    logger: "window.onerror",
    message: errMsg,
    exception: errStack,
    extra: { filename: event.filename, lineno: event.lineno, colno: event.colno }
  });
  reportFrontendIssueToBackend(errMsg, errStack, "ERROR");
});

// Global Promise Rejection Interceptor
window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  const errMsg = reason ? (reason.message || String(reason)) : "Unhandled Promise rejection";
  const errStack = reason && reason.stack ? reason.stack : null;
  logDiagnosticEntry({
    source: "frontend",
    level: "ERROR",
    logger: "promise.unhandled",
    message: errMsg,
    exception: errStack
  });
  reportFrontendIssueToBackend(errMsg, errStack, "ERROR");
});

// Network Fetch Interceptor for Live Diagnostics
const _rawFetch = window.fetch;
window.fetch = async function(...args) {
  const [resource, config] = args;
  const url = typeof resource === "string" ? resource : (resource ? resource.url : "");
  const method = (config && config.method) ? config.method.toUpperCase() : "GET";
  const startTime = performance.now();

  try {
    const response = await _rawFetch.apply(this, args);
    const latency = Math.round(performance.now() - startTime);

    if (!response.ok) {
      const isDiagEndpoint = url.includes("/api/v1/diagnostics");
      if (!isDiagEndpoint) {
        let errSnippet = "";
        try {
          const clone = response.clone();
          const json = await clone.json();
          errSnippet = JSON.stringify(json, null, 2);
        } catch (_) {
          try {
            const clone = response.clone();
            errSnippet = await clone.text();
          } catch (_) {}
        }

        logDiagnosticEntry({
          source: "network",
          level: "ERROR",
          logger: `${method} ${url}`,
          message: `HTTP ${response.status} ${response.statusText} (${latency}ms)`,
          exception: errSnippet,
          extra: { status: response.status, latency_ms: latency, url }
        });
      }
    }
    return response;
  } catch (netErr) {
    const latency = Math.round(performance.now() - startTime);
    const isDiagEndpoint = url.includes("/api/v1/diagnostics");
    if (!isDiagEndpoint) {
      logDiagnosticEntry({
        source: "network",
        level: "ERROR",
        logger: `${method} ${url}`,
        message: `Network Request Failed: ${netErr.message || netErr} (${latency}ms)`,
        exception: netErr.stack || String(netErr),
        extra: { error: String(netErr), latency_ms: latency, url }
      });
    }
    throw netErr;
  }
};

document.addEventListener("DOMContentLoaded", () => {
  initDashboard();
});

async function initDashboard() {
  initDiagnostics();
  initSideColumnResizer();
  initTableColumnResizers();
  await Promise.all([
    checkBackendHealth(),
    loadMountsAndCrawlerStatus(),
    loadMetrics(),
    loadTaxonomyCategories(),
    loadLedger()
  ]);

  // Periodic refresh for metrics
  setInterval(() => {
    loadMetrics();
  }, 10000);
}

// 1. Backend Health Check
async function checkBackendHealth() {
  try {
    const res = await fetch("/api/v1/documents/stats");
    if (res.ok) {
      document.getElementById("backend-status-text").textContent = "Online (ALCOA+ Ready)";
      document.querySelector(".pulse-dot").style.background = "#10b981";
    }
  } catch (err) {
    document.getElementById("backend-status-text").textContent = "Offline / Reconnecting";
    document.querySelector(".pulse-dot").style.background = "#f43f5e";
  }
}

// 2. Storage Mounts & Crawler Status
async function loadMountsAndCrawlerStatus() {
  try {
    const res = await fetch("/api/v1/crawler/status");
    const data = await res.json();
    
    watcherRunning = data.polling_observer_running;
    updateWatcherButton();

    const container = document.getElementById("mounts-list");
    container.innerHTML = "";

    (data.configured_roots || []).forEach(r => {
      const chip = document.createElement("span");
      chip.className = `mount-chip ${r.accessible ? 'online' : 'offline'}`;
      chip.innerHTML = `${r.accessible ? '🟢' : '🔴'} ${escapeHtml(r.root)}`;
      chip.title = r.accessible ? "Storage root mounted and reachable" : "Root currently unreachable or offline";
      container.appendChild(chip);
    });
  } catch (err) {
    console.error("Failed loading crawler status:", err);
  }
}

function updateWatcherButton() {
  const btnText = document.getElementById("watch-btn-text");
  if (watcherRunning) {
    btnText.textContent = "Stop Watcher";
    document.getElementById("btn-watch").classList.add("btn-primary");
    document.getElementById("btn-watch").classList.remove("btn-outline");
  } else {
    btnText.textContent = "Start Watcher";
    document.getElementById("btn-watch").classList.remove("btn-primary");
    document.getElementById("btn-watch").classList.add("btn-outline");
  }
}

async function toggleWatcher() {
  const endpoint = watcherRunning ? "/api/v1/crawler/watch/stop" : "/api/v1/crawler/watch/start";
  try {
    const res = await fetch(endpoint, { method: "POST" });
    const data = await res.json();
    watcherRunning = (data.status === "started" || data.status === "already_running");
    updateWatcherButton();
    await loadMountsAndCrawlerStatus();
    showToast(watcherRunning ? "Watcher daemon started" : "Watcher daemon stopped", "info");
  } catch (err) {
    showToast("Watcher toggle failed: " + err, "error");
  }
}

async function triggerScan() {
  const btn = document.getElementById("btn-scan");
  btn.disabled = true;
  btn.innerHTML = `<span class="btn-icon">⏳</span> Scanning...`;

  try {
    const res = await fetch("/api/v1/crawler/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force_reprocess: false })
    });
    const summary = await res.json();
    const workersMsg = summary.parallel_workers ? ` (${summary.parallel_workers} parallel workers)` : "";
    showToast(`Scan complete${workersMsg}: ${summary.total_ingested} ingested, ${summary.total_duplicates_found} duplicates`, "success", 5000);
    await Promise.all([loadMetrics(), loadLedger()]);
  } catch (err) {
    showToast("Scan failed: " + err, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<span class="btn-icon">⚡</span> Quick Scan`;
  }
}

// 3. Metrics
async function loadMetrics() {
  try {
    const res = await fetch("/api/v1/documents/stats");
    const stats = await res.json();

    document.getElementById("metric-unique").textContent = stats.total_unique_documents;
    document.getElementById("metric-locations").textContent = stats.total_physical_locations;
    document.getElementById("metric-savings").textContent = stats.duplicates_deduplicated;
    document.getElementById("metric-lineage").textContent = stats.version_links_count;
  } catch (err) {
    console.error("Failed loading stats:", err);
  }
}

// 4. Dynamic Multilingual Taxonomy Categories
async function loadTaxonomyCategories() {
  try {
    const res = await fetch("/api/v1/taxonomy/");
    if (!res.ok) return;
    const data = await res.json();
    const select = document.getElementById("category-filter");
    if (!select) return;

    select.innerHTML = `<option value="">All Categories (Taxonomy)</option>`;
    (data.categories || []).forEach(cat => {
      const opt = document.createElement("option");
      opt.value = cat.category_id;
      const countSuffix = cat.document_count > 0 ? ` [${cat.document_count}]` : "";
      opt.textContent = `${cat.name_en} (${cat.name_fr} / ${cat.name_de})${countSuffix}`;
      select.appendChild(opt);
    });
  } catch (err) {
    console.error("Failed to load taxonomy categories:", err);
  }
}

function handleCategoryChange() {
  const select = document.getElementById("category-filter");
  activeCategory = select ? select.value : "";
  updateActiveFilterBar();
  loadLedger();
}

// 5. Duplicate Filter Toggle
function toggleDuplicatesFilter() {
  filterOnlyDuplicates = !filterOnlyDuplicates;
  const card = document.getElementById("card-duplicates");
  const badge = document.getElementById("duplicates-badge");
  const sub = document.getElementById("duplicates-sub");

  if (filterOnlyDuplicates) {
    card.classList.add("active-card");
    badge.classList.remove("hidden");
    sub.textContent = "Showing duplicates only (click to reset)";
    showToast("Filtering ledger by duplicate files (>1 locations)", "info", 3000);
  } else {
    card.classList.remove("active-card");
    badge.classList.add("hidden");
    sub.textContent = "Exact duplicate copies (click to filter)";
  }
  updateActiveFilterBar();
  loadLedger();
}

// Helper: get the substantive document date (filename prefix, content, or last modified)
function getEffectiveDocDate(doc) {
  if (!doc) return "";
  if (doc.doc_date) return String(doc.doc_date);

  const fn = String(doc.canonical_filename || "").trim();

  // 1. Prefix European: DD.MM.YYYY or DD.MM.YY (e.g. 05.08.25-...)
  const mPrefEur = fn.match(/^(0[1-9]|[12]\d|3[01])[-_.](0[1-9]|1[0-2])[-_.](20\d{2}|19\d{2}|\d{2})(?:[-_\s.]|$)/);
  if (mPrefEur) {
    let y = mPrefEur[3];
    if (y.length === 2) y = (parseInt(y, 10) > 70 ? "19" : "20") + y;
    return `${y}-${mPrefEur[2]}-${mPrefEur[1]}`;
  }

  // 2. Prefix ISO: YYYY[-_.]MM[-_.]DD (e.g. 2024-03-15_...)
  const mPrefIso = fn.match(/^(19\d{2}|20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?:[-_\s.]|$)/);
  if (mPrefIso) {
    return `${mPrefIso[1]}-${mPrefIso[2]}-${mPrefIso[3]}`;
  }

  // 3. Prefix compact European: DDMMYYYY (e.g. 16102025-...)
  const mPrefDmy = fn.match(/^(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])(19\d{2}|20\d{2})(?:[-_\s.]|$)/);
  if (mPrefDmy) {
    return `${mPrefDmy[3]}-${mPrefDmy[2]}-${mPrefDmy[1]}`;
  }

  // 4. Prefix compact ISO: YYYYMMDD (e.g. 20231016_...)
  const mPrefYmd = fn.match(/^(19\d{2}|20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[-_\s.]|$)/);
  if (mPrefYmd) {
    return `${mPrefYmd[1]}-${mPrefYmd[2]}-${mPrefYmd[3]}`;
  }

  // 5. File modification time (mtime)
  if (doc.doc_mtime && doc.doc_mtime > 0) {
    try {
      return new Date(doc.doc_mtime * 1000).toISOString().slice(0, 10);
    } catch (e) { }
  }
  if (doc.locations && doc.locations.length > 0) {
    for (const loc of doc.locations) {
      if (loc.mtime && loc.mtime > 0) {
        try {
          return new Date(loc.mtime * 1000).toISOString().slice(0, 10);
        } catch (e) { }
      }
    }
  }

  // 6. Fallback to indexing date (created_at)
  if (doc.created_at) {
    return String(doc.created_at).slice(0, 10);
  }

  return "";
}

// 6. Sortable Table Columns
function setSort(column) {
  if (activeSortBy === column) {
    activeSortOrder = (activeSortOrder === "ASC") ? "DESC" : "ASC";
  } else {
    activeSortBy = column;
    if (column === "canonical_filename" || column === "doc_type") {
      activeSortOrder = "ASC";
    } else {
      activeSortOrder = "DESC";
    }
  }
  updateSortIndicators();

  // Instant client-side sort of currently loaded items (zero delay in UI)
  if (cachedLedgerItems && cachedLedgerItems.length > 0) {
    cachedLedgerItems = sortItemsLocally(cachedLedgerItems, activeSortBy, activeSortOrder);
    renderLedgerRows(cachedLedgerItems);
  }

  // Also query backend for synchronization
  loadLedger();
}

function sortItemsLocally(items, sortBy, sortOrder) {
  const isAsc = String(sortOrder).toUpperCase() === "ASC";
  return [...items].sort((a, b) => {
    let valA, valB;
    if (sortBy === "canonical_filename") {
      valA = String(a.canonical_filename || "").toLowerCase();
      valB = String(b.canonical_filename || "").toLowerCase();
    } else if (sortBy === "doc_type") {
      valA = String(a.doc_type || "").toLowerCase();
      valB = String(b.doc_type || "").toLowerCase();
    } else if (sortBy === "maturity_score") {
      valA = Number(a.maturity_score) || 0;
      valB = Number(b.maturity_score) || 0;
    } else if (sortBy === "lifecycle_status") {
      valA = String(a.lifecycle_status || "").toLowerCase();
      valB = String(b.lifecycle_status || "").toLowerCase();
    } else if (sortBy === "location_count") {
      const countA = a.location_count != null ? a.location_count : (a.locations ? a.locations.length : 0);
      const countB = b.location_count != null ? b.location_count : (b.locations ? b.locations.length : 0);
      valA = Number(countA);
      valB = Number(countB);
    } else if (sortBy === "doc_date" || sortBy === "created_at" || sortBy === "date") {
      valA = getEffectiveDocDate(a);
      valB = getEffectiveDocDate(b);
    } else {
      valA = a.created_at || "";
      valB = b.created_at || "";
    }

    if (valA < valB) return isAsc ? -1 : 1;
    if (valA > valB) return isAsc ? 1 : -1;

    // Stable secondary tie-breaker: filename
    const nameA = String(a.canonical_filename || "").toLowerCase();
    const nameB = String(b.canonical_filename || "").toLowerCase();
    if (nameA < nameB) return -1;
    if (nameA > nameB) return 1;
    return 0;
  });
}

function updateSortIndicators() {
  const cols = ["canonical_filename", "doc_type", "maturity_score", "lifecycle_status", "location_count", "doc_date", "created_at"];
  cols.forEach(col => {
    const indicator = document.getElementById(`sort-${col}`);
    const th = indicator ? indicator.closest("th") : null;
    if (!indicator) return;

    if (col === activeSortBy || (col === "doc_date" && activeSortBy === "created_at") || (col === "created_at" && activeSortBy === "doc_date")) {
      indicator.textContent = (activeSortOrder === "ASC") ? "▲" : "▼";
      if (th) {
        th.className = `th-sortable sorted-${activeSortOrder.toLowerCase()}`;
      }
    } else {
      indicator.textContent = "↕";
      if (th) {
        th.className = "th-sortable";
      }
    }
  });
}

// 7. Search and Filter Bar Handling
function handleSearch(event) {
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    searchFilterQuery = event.target.value.trim().toLowerCase();
    updateActiveFilterBar();
    loadLedger();
  }, 250);
}

function clearAllFilters() {
  filterOnlyDuplicates = false;
  activeCategory = "";
  searchFilterQuery = "";

  const card = document.getElementById("card-duplicates");
  if (card) card.classList.remove("active-card");
  const badge = document.getElementById("duplicates-badge");
  if (badge) badge.classList.add("hidden");
  const sub = document.getElementById("duplicates-sub");
  if (sub) sub.textContent = "Exact duplicate copies (click to filter)";

  const catFilter = document.getElementById("category-filter");
  if (catFilter) catFilter.value = "";
  const statusFilter = document.getElementById("status-filter");
  if (statusFilter) statusFilter.value = "";
  const searchBox = document.getElementById("search-box");
  if (searchBox) searchBox.value = "";

  updateActiveFilterBar();
  loadLedger();
}

function updateActiveFilterBar() {
  const bar = document.getElementById("active-filter-bar");
  const text = document.getElementById("active-filter-text");
  const resetBtn = document.getElementById("btn-clear-filters");

  const activeFilters = [];
  if (filterOnlyDuplicates) activeFilters.push("Duplicates Only");
  if (activeCategory) activeFilters.push(`Category: ${activeCategory}`);
  const status = document.getElementById("status-filter")?.value;
  if (status) activeFilters.push(`Status: ${status}`);
  if (searchFilterQuery) activeFilters.push(`Query: "${searchFilterQuery}"`);

  if (activeFilters.length > 0) {
    bar.classList.remove("hidden");
    text.innerHTML = `Active filter: <strong>${escapeHtml(activeFilters.join(" • "))}</strong>`;
    if (resetBtn) resetBtn.classList.remove("hidden");
  } else {
    bar.classList.add("hidden");
    if (resetBtn) resetBtn.classList.add("hidden");
  }
}

// 8. Open File Directly or Reveal in Explorer
async function openFile(filePath, reveal = false) {
  if (!filePath) {
    showToast("Invalid file path", "error");
    return;
  }

  const actionName = reveal ? "Revealing in File Explorer" : "Opening file";
  showToast(`${actionName}: ${filePath}`, "info", 5000);

  try {

    /*
    if (reveal) {
      const parentFolder = filePath.split("\\").slice(0, -1).join("\\");
      filePath = parentFolder;
      console.log("reveal is true: ", filePath);
      showToast(`Opening folder: ${filePath}`, "info", 5000);
    } else {
      console.log("reveal is false: ", filePath);
      showToast(`Opening file: ${filePath}`, "info", 5000);
    }
    */

    const res = await fetch("/api/v1/documents/open-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_path: filePath, reveal: reveal })
    });

    const data = await res.json();
    if (!res.ok) {
      showToast(`Error: ${data.detail || "Could not open file"}`, "error", 7000);
    } else {
      const verb = reveal ? "Revealed in Explorer" : "Launched default application";
      showToast(`${verb}: ${filePath}`, "success", 5000);
    }
  } catch (err) {
    showToast(`Network error: ${err.message}`, "error", 7000);
  }
}

function handleOpenPathClick(event, el, reveal = false) {
  event.stopPropagation();
  const path = el.getAttribute("data-path");
  openFile(path, reveal);
}

// ==========================================
// 8.5 Layout Resizers (Side Column & Table Cols)
// ==========================================
function initSideColumnResizer() {
  const resizer = document.getElementById("side-column-resizer");
  const grid = document.querySelector(".dashboard-grid");
  const sideColumn = document.getElementById("side-column");
  if (!resizer || !grid || !sideColumn) return;

  // Restore saved width from localStorage
  const savedWidth = localStorage.getItem("reposcroller_side_width");
  if (savedWidth) {
    grid.style.setProperty("--side-column-width", `${savedWidth}px`);
  }

  let isDragging = false;
  let startX = 0;
  let startWidth = 0;

  resizer.addEventListener("mousedown", (e) => {
    isDragging = true;
    resizer.classList.add("is-dragging");
    document.body.classList.add("resizing-side-column");
    startX = e.clientX;
    startWidth = sideColumn.getBoundingClientRect().width;
    e.preventDefault();
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    // Moving mouse to the left makes the side-column wider
    const delta = startX - e.clientX;
    const maxW = Math.max(300, window.innerWidth - 380);
    const newWidth = Math.max(280, Math.min(maxW, Math.round(startWidth + delta)));
    grid.style.setProperty("--side-column-width", `${newWidth}px`);
  });

  window.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      resizer.classList.remove("is-dragging");
      document.body.classList.remove("resizing-side-column");
      const currentWidth = Math.round(sideColumn.getBoundingClientRect().width);
      localStorage.setItem("reposcroller_side_width", currentWidth);
    }
  });

  // Double click resets to default 420px
  resizer.addEventListener("dblclick", () => {
    grid.style.setProperty("--side-column-width", "420px");
    localStorage.setItem("reposcroller_side_width", "420px");
    showToast("Panel width reset to default (420px)", "info", 2000);
  });
}

function initTableColumnResizers() {
  const table = document.querySelector(".ledger-table");
  if (!table) return;

  const ths = table.querySelectorAll("thead th");
  if (!ths || ths.length === 0) return;

  // Restore saved widths if any
  const savedColWidths = JSON.parse(localStorage.getItem("reposcroller_table_widths") || "{}");

  // Default proportional widths for the 7 columns
  const defaultWidths = ["30%", "14%", "12%", "11%", "9%", "14%", "10%"];

  ths.forEach((th, index) => {
    const colKey = `col_${index}`;
    if (savedColWidths[colKey]) {
      th.style.width = savedColWidths[colKey];
    } else if (defaultWidths[index]) {
      th.style.width = defaultWidths[index];
    }

    // Do not add resizer to the very last column ("Actions")
    if (index === ths.length - 1) return;

    // Clean up if already exists
    const existing = th.querySelector(".th-resizer");
    if (existing) existing.remove();

    const resizer = document.createElement("div");
    resizer.className = "th-resizer";
    resizer.title = "Drag to resize column (Double-click to reset)";

    // Prevent sort triggers or clicks
    resizer.addEventListener("click", (e) => e.stopPropagation());

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    resizer.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      e.preventDefault();
      isResizing = true;
      startX = e.clientX;
      startWidth = th.getBoundingClientRect().width;
      resizer.classList.add("is-resizing");
      document.body.classList.add("resizing-table-col");

      const onMouseMove = (moveEvent) => {
        if (!isResizing) return;
        const delta = moveEvent.clientX - startX;
        const newWidth = Math.max(50, Math.round(startWidth + delta));
        th.style.width = `${newWidth}px`;
      };

      const onMouseUp = () => {
        if (isResizing) {
          isResizing = false;
          resizer.classList.remove("is-resizing");
          document.body.classList.remove("resizing-table-col");
          window.removeEventListener("mousemove", onMouseMove);
          window.removeEventListener("mouseup", onMouseUp);

          // Save custom width to localStorage
          const widths = JSON.parse(localStorage.getItem("reposcroller_table_widths") || "{}");
          widths[colKey] = `${Math.round(th.getBoundingClientRect().width)}px`;
          localStorage.setItem("reposcroller_table_widths", JSON.stringify(widths));
        }
      };

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    });

    resizer.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      th.style.width = defaultWidths[index] || "";
      const widths = JSON.parse(localStorage.getItem("reposcroller_table_widths") || "{}");
      delete widths[colKey];
      localStorage.setItem("reposcroller_table_widths", JSON.stringify(widths));
      showToast("Column reset to default width", "info", 1500);
    });

    th.appendChild(resizer);
  });
}

// 9. Load Document Ledger Table
async function loadLedger() {
  const statusFilter = document.getElementById("status-filter")?.value || "";
  
  const params = new URLSearchParams();
  if (statusFilter) params.append("status", statusFilter);
  if (activeCategory) params.append("category", activeCategory);
  if (filterOnlyDuplicates) params.append("only_duplicates", "true");
  params.append("sort_by", activeSortBy);
  params.append("sort_order", activeSortOrder);
  params.append("limit", "100");
  params.append("_t", String(Date.now())); // Prevent browser HTTP caching

  const url = `/api/v1/documents/ledger?${params.toString()}`;
  
  try {
    const res = await fetch(url);
    const data = await res.json();

    let items = data.items || [];
    if (searchFilterQuery) {
      items = items.filter(d => 
        (d.canonical_filename || "").toLowerCase().includes(searchFilterQuery) ||
        (d.text_snippet || "").toLowerCase().includes(searchFilterQuery)
      );
    }

    // Always sort locally as well to guarantee immediate client accuracy
    cachedLedgerItems = sortItemsLocally(items, activeSortBy, activeSortOrder);
    renderLedgerRows(cachedLedgerItems);
  } catch (err) {
    console.error("Failed loading ledger:", err);
  }
}

function renderLedgerRows(items) {
  const tbody = document.getElementById("ledger-rows");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!items || items.length === 0) {
    const emptyMsg = filterOnlyDuplicates 
      ? "No duplicate files found in the ledger. All files are currently unique."
      : "No documents matching the current filters.";
    tbody.innerHTML = `<tr><td colspan="7" class="text-center loading-cell">${emptyMsg}</td></tr>`;
    return;
  }

  items.forEach(doc => {
    const tr = document.createElement("tr");
    tr.onclick = () => selectDocument(doc.sha256_hash);

    const maturityPercent = Math.round((doc.maturity_score || 0) * 100);
    const statusBadgeClass = `badge-${(doc.lifecycle_status || 'draft').toLowerCase()}`;
    
    const locations = doc.locations || [];
    const primaryLoc = locations.find(l => l.is_primary_source) || locations[0] || null;
    const primaryPath = primaryLoc ? primaryLoc.absolute_path : "";
    const locCount = doc.location_count != null ? doc.location_count : locations.length;
    const isDuplicate = locCount > 1;

    const subpathHtml = primaryPath ? `
      <div class="doc-subpath" data-path="${escapeHtml(primaryPath)}" onclick="handleOpenPathClick(event, this, false)" title="Click to open: ${escapeHtml(primaryPath)}">
        🔗 ${escapeHtml(primaryPath)}
      </div>
    ` : '';

    const effectiveDate = getEffectiveDocDate(doc);
    let dateBadge = '';
    const src = doc.doc_date_source;
    if (src === 'filename_prefix') {
      dateBadge = '<span class="date-badge-source src-prefix" title="Date from filename prefix">🏷️ Prefix</span>';
    } else if (src === 'filename') {
      dateBadge = '<span class="date-badge-source src-fn" title="Date from filename">📁 Name</span>';
    } else if (src === 'content') {
      dateBadge = '<span class="date-badge-source src-content" title="Date inside document content">📄 Content</span>';
    } else if (src === 'mtime') {
      dateBadge = '<span class="date-badge-source src-mtime" title="Date from file last-modified timestamp">🕒 Modified</span>';
    }

    const dateTooltip = `Document Date: ${effectiveDate || '--'} (${src || 'detected'})${doc.doc_mtime ? `\nFile Last Modified: ${new Date(doc.doc_mtime * 1000).toLocaleString()}` : ''}\nIndexed at: ${doc.created_at ? new Date(doc.created_at).toLocaleString() : '--'}`;

    tr.innerHTML = `
      <td>
        <div class="doc-name">${escapeHtml(doc.canonical_filename)}</div>
        <div class="doc-snippet">${escapeHtml(doc.text_snippet || '')}</div>
        ${subpathHtml}
      </td>
      <td>
        <span class="badge" style="background: rgba(255,255,255,0.06); cursor: pointer;" title="Filter by this category" onclick="event.stopPropagation(); setCategoryFilter('${escapeHtml(doc.doc_type || '')}')">
          ${escapeHtml(doc.doc_type || 'doc')}
        </span>
      </td>
      <td>
        <div class="maturity-bar-wrapper" title="Maturity Score: ${doc.maturity_score}">
          <div class="maturity-track">
            <div class="maturity-fill" style="width: ${maturityPercent}%;"></div>
          </div>
          <span style="font-family: var(--font-mono); font-size: 0.75rem;">${maturityPercent}%</span>
        </div>
      </td>
      <td><span class="badge ${statusBadgeClass}">${escapeHtml(doc.lifecycle_status || 'draft')}</span></td>
      <td>
        <span class="badge ${isDuplicate ? 'badge-duplicate' : ''}" title="${locCount} registered location(s)">
          ${locCount} ${locCount > 1 ? 'copies' : 'copy'}
        </span>
      </td>
      <td style="white-space: nowrap; font-family: var(--font-mono); font-size: 0.75rem;" title="${escapeHtml(dateTooltip)}">
        <div style="display: flex; align-items: center; gap: 0.35rem;">
          <span style="font-weight: 500;">${effectiveDate ? escapeHtml(effectiveDate) : '--'}</span>
          ${dateBadge}
        </div>
      </td>
      <td>
        <div style="display: flex; gap: 0.35rem;">
          ${primaryPath ? `
          <button class="btn btn-outline" style="padding: 0.2rem 0.5rem; font-size: 0.72rem;" data-path="${escapeHtml(primaryPath)}" onclick="handleOpenPathClick(event, this, false)" title="Open file in default application">
            Open ↗
          </button>` : ''}
          <button class="btn btn-outline" style="padding: 0.2rem 0.5rem; font-size: 0.72rem;">View</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function setCategoryFilter(catId) {
  if (!catId) return;
  const select = document.getElementById("category-filter");
  if (select) {
    select.value = catId;
    handleCategoryChange();
  }
}

// 10. Select & Inspect Document Lineage
async function selectDocument(sha256) {
  activeDocumentSha = sha256;
  switchTab("detail");

  document.getElementById("detail-empty").classList.add("hidden");
  const panel = document.getElementById("detail-panel");
  panel.classList.remove("hidden");
  panel.innerHTML = `<div class="empty-state">Loading document lineage...</div>`;

  try {
    const res = await fetch(`/api/v1/documents/${sha256}`);
    const doc = await res.json();

    const locationsHtml = (doc.locations || []).map(loc => `
      <div class="location-item">
        <div class="location-header">
          <div class="location-path">
            <span class="location-path-link" data-path="${escapeHtml(loc.absolute_path)}" onclick="handleOpenPathClick(event, this, false)" title="Click to open file in default application">
              ${loc.is_primary_source ? '⭐ ' : ''}🔗 ${escapeHtml(loc.absolute_path)}
            </span>
          </div>
          <div class="location-actions">
            <button class="btn-icon-action" data-path="${escapeHtml(loc.absolute_path)}" onclick="handleOpenPathClick(event, this, false)" title="Open in default application">
              📄 Open
            </button>
            <button class="btn-icon-action" data-path="${escapeHtml(loc.absolute_path)}" onclick="handleOpenPathClick(event, this, true)" title="Reveal and highlight file in Explorer">
              📂 Reveal
            </button>
          </div>
        </div>
        <div class="location-root">
          Root: ${escapeHtml(loc.storage_root)} • Size: ${(loc.file_size / 1024).toFixed(1)} KB
          ${loc.mtime ? ` • Modified: ${new Date(loc.mtime * 1000).toLocaleString()}` : ''}
        </div>
      </div>
    `).join("") || `<div class="location-item text-muted">No physical location registered.</div>`;

    const parentsHtml = (doc.parents || []).map(p => `
      <div class="lineage-item" onclick="selectDocument('${p.parent_sha256}')" style="cursor: pointer;">
        <div><strong>Parent Revision:</strong> ${escapeHtml(p.canonical_filename)}</div>
        <div class="location-root">Relation: ${p.relationship} (Similarity: ${(p.similarity_score * 100).toFixed(1)}%)</div>
      </div>
    `).join("");

    const childrenHtml = (doc.children || []).map(c => `
      <div class="lineage-item" onclick="selectDocument('${c.child_sha256}')" style="cursor: pointer;">
        <div><strong>Child Revision:</strong> ${escapeHtml(c.canonical_filename)}</div>
        <div class="location-root">Relation: ${c.relationship} (Similarity: ${(c.similarity_score * 100).toFixed(1)}%)</div>
      </div>
    `).join("");

    const detailDocDate = doc.doc_date || getEffectiveDocDate(doc) || '--';
    const detailDateSrc = doc.doc_date_source || 'detected';

    panel.innerHTML = `
      <div class="detail-header">
        <div class="detail-title">${escapeHtml(doc.canonical_filename)}</div>
        <div class="hash-box" title="Click to copy SHA-256" onclick="navigator.clipboard.writeText('${doc.sha256_hash}'); showToast('Copied SHA-256 to clipboard', 'info');">
          SHA-256: ${doc.sha256_hash}
        </div>
        <div class="hash-box" style="margin-top: 0.25rem;">
          📅 Document Date: <strong>${escapeHtml(detailDocDate)}</strong> <span style="opacity: 0.7;">(${escapeHtml(detailDateSrc)})</span>
          ${doc.doc_mtime ? ` • Modified: ${new Date(doc.doc_mtime * 1000).toLocaleDateString()}` : ''}
        </div>
        <div class="hash-box" style="margin-top: 0.25rem;">
          SimHash: ${doc.simhash} • Maturity: ${doc.maturity_score} • Status: ${doc.lifecycle_status.toUpperCase()}
        </div>
      </div>

      <div class="detail-section" style="margin-top: 1rem;">
        <button class="btn btn-interrogate-detail" onclick="interrogateAboutCurrent('${escapeHtml(doc.canonical_filename)}')">
          💬 Interrogate Bot About This Document
        </button>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Physical Storage Locations (${(doc.locations || []).length})</div>
        <div class="locations-list">${locationsHtml}</div>
      </div>
     
      ${parentsHtml ? `
      <div class="detail-section">
        <div class="detail-section-title">Evolved From (Parents)</div>
        <div class="lineage-list">${parentsHtml}</div>
      </div>` : ''}

      ${childrenHtml ? `
      <div class="detail-section">
        <div class="detail-section-title">Superseded By (Revisions)</div>
        <div class="lineage-list">${childrenHtml}</div>
      </div>` : ''}


    `;
  } catch (err) {
    panel.innerHTML = `<div class="empty-state text-rose">Failed loading details: ${err}</div>`;
  }
}

// 11. Pre-flight Dropzone
function handleDragOver(e) {
  e.preventDefault();
  document.getElementById("dropzone").classList.add("drag-active");
}

function handleDragLeave(e) {
  e.preventDefault();
  document.getElementById("dropzone").classList.remove("drag-active");
}

function handleDrop(e) {
  e.preventDefault();
  document.getElementById("dropzone").classList.remove("drag-active");
  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    uploadForCheck(e.dataTransfer.files[0]);
  }
}

function triggerFileInput() {
  document.getElementById("file-input").click();
}

function handleFileSelected(e) {
  if (e.target.files && e.target.files.length > 0) {
    uploadForCheck(e.target.files[0]);
  }
}

async function uploadForCheck(file) {
  const resultDiv = document.getElementById("drop-result");
  resultDiv.classList.remove("hidden");
  resultDiv.className = "drop-result";
  resultDiv.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <span><strong>Inspecting ${escapeHtml(file.name)}...</strong> Calculating SHA-256 and SimHash...</span>
      <button onclick="document.getElementById('drop-result').classList.add('hidden')" style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1rem; padding: 0 4px;" title="Dismiss">✕</button>
    </div>`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/v1/documents/check-duplicate", {
      method: "POST",
      body: formData
    });
    const data = await res.json();

    const cat = data.status_category;
    let badgeClass = "unique";
    if (cat === "EXACT_MATCH") badgeClass = "exact";
    else if (cat === "EVOLVED_VERSION" || cat === "DRAFT_EXISTS") badgeClass = "variant";

    resultDiv.className = `drop-result ${badgeClass}`;
    resultDiv.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.35rem;">
        <span style="font-weight: 600; font-size: 0.95rem;">
          ${cat === "EXACT_MATCH" ? "⛔ Exact Duplicate Found" : (cat === "EVOLVED_VERSION" ? "🔄 Evolved Variant Detected" : "✅ Unique Document")}
        </span>
        <button onclick="document.getElementById('drop-result').classList.add('hidden')" style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1rem; padding: 0 4px;" title="Dismiss">✕</button>
      </div>
      <div style="font-size: 0.82rem; margin-bottom: 0.5rem;">${escapeHtml(data.answer)}</div>
      ${data.recommendation ? `<div style="font-size: 0.8rem; color: var(--accent-amber); font-weight: 500;">Recommendation: ${escapeHtml(data.recommendation)}</div>` : ''}
    `;
  } catch (err) {
    resultDiv.className = "drop-result";
    resultDiv.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span class="text-rose">Inspection failed: ${err}</span>
        <button onclick="document.getElementById('drop-result').classList.add('hidden')" style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1rem; padding: 0 4px;" title="Dismiss">✕</button>
      </div>`;
  }
}

// 12. Tabs & AI Chat Interrogation
function switchTab(tab) {
  document.getElementById("tab-btn-detail").classList.toggle("active", tab === "detail");
  document.getElementById("tab-btn-chat").classList.toggle("active", tab === "chat");
  document.getElementById("tab-detail").classList.toggle("active", tab === "detail");
  document.getElementById("tab-chat").classList.toggle("active", tab === "chat");
}

function sendSuggestion(query) {
  document.getElementById("chat-input").value = query;
  sendChatMessage();
}

function interrogateAboutCurrent(filename) {
  switchTab("chat");
  document.getElementById("chat-input").value = `Do we have any copy or draft of "${filename}"?`;
  sendChatMessage(activeDocumentSha);
}

async function sendChatMessage(sha = null) {
  const input = document.getElementById("chat-input");
  const query = input.value.trim();
  if (!query) return;

  const targetSha = sha || (activeDocumentSha && query.includes("Do we have") ? activeDocumentSha : null);

  input.value = "";
  const container = document.getElementById("chat-messages");

  // User Bubble
  const userDiv = document.createElement("div");
  userDiv.className = "chat-msg user";
  userDiv.innerHTML = `<div class="msg-bubble">${escapeHtml(query)}</div>`;
  container.appendChild(userDiv);

  // Bot Bubble placeholder
  const botDiv = document.createElement("div");
  botDiv.className = "chat-msg bot";
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.innerHTML = `<em>Consulting SQLite WAL ledger & SimHash indexes...</em>`;
  botDiv.appendChild(bubble);
  container.appendChild(botDiv);
  container.scrollTop = container.scrollHeight;

  // Stream via SSE
  let sseUrl = `/api/v1/chat/stream?query=${encodeURIComponent(query)}`;
  if (targetSha) {
    sseUrl += `&sha256_hash=${encodeURIComponent(targetSha)}`;
  }
  const eventSource = new EventSource(sseUrl);
  let accumulated = "";

  eventSource.onmessage = (event) => {
    if (event.data === "[DONE]") {
      eventSource.close();
      return;
    }

    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "chunk") {
        accumulated += payload.content;
        bubble.innerHTML = escapeHtml(accumulated).replace(/\n/g, '<br>');
        container.scrollTop = container.scrollHeight;
      } else if (payload.type === "recommendation") {
        accumulated += `\n\n💡 Recommendation: ${payload.recommendation}`;
        bubble.innerHTML = escapeHtml(accumulated).replace(/\n/g, '<br>');
      }
    } catch (e) {
      // Raw string
    }
  };

  eventSource.onerror = () => {
    eventSource.close();
  };
}

// 13. Toast Notification Helper
function showToast(message, type = "info", duration = 4000) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  
  const icon = type === "success" ? "✅" : (type === "error" ? "⚠️" : "ℹ️");
  toast.innerHTML = `
    <div style="display: flex; align-items: center; gap: 0.5rem; word-break: break-word;">
      <span>${icon}</span>
      <span>${escapeHtml(message)}</span>
    </div>
    <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    if (toast.parentElement) {
      toast.style.transition = "opacity 0.3s ease, transform 0.3s ease";
      toast.style.opacity = "0";
      toast.style.transform = "translateX(50px)";
      setTimeout(() => toast.remove(), 300);
    }
  }, duration);
}

// 14. HTML Escape Utility
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ==========================================================================
// 15. Floating Diagnostic Console Implementation
// ==========================================================================

function initDiagnostics() {
  // Start backend log polling (every 2.5s)
  fetchDiagnosticLogs();
  fetchDiagnosticHealth();

  if (diagPollTimer) clearInterval(diagPollTimer);
  diagPollTimer = setInterval(fetchDiagnosticLogs, 2500);

  if (diagHealthTimer) clearInterval(diagHealthTimer);
  diagHealthTimer = setInterval(fetchDiagnosticHealth, 8000);

  // Initial welcome message in diagnostic console
  logDiagnosticEntry({
    source: "frontend",
    level: "INFO",
    logger: "client.runtime",
    message: "RepoScroller frontend diagnostic monitor initialized."
  });
}

function logDiagnosticEntry(entry) {
  const timestamp = entry.timestamp || new Date().toTimeString().split(" ")[0];
  const item = {
    id: entry.id || Date.now() + Math.random(),
    timestamp: timestamp,
    level: (entry.level || "INFO").toUpperCase(),
    logger: entry.logger || "system",
    message: entry.message || "",
    exception: entry.exception || null,
    source: entry.source || "frontend",
    extra: entry.extra || {}
  };

  diagLogs.push(item);
  if (diagLogs.length > 500) {
    diagLogs.shift();
  }

  updateDiagnosticBadges();
  renderDiagnosticLogs();
}

async function fetchDiagnosticLogs() {
  try {
    const res = await _rawFetch(`/api/v1/diagnostics/logs?since_id=${diagWatermarkId}&limit=150`);
    if (!res.ok) return;

    const data = await res.json();
    if (data.logs && data.logs.length > 0) {
      data.logs.forEach(log => {
        diagLogs.push({
          id: log.id,
          timestamp: log.timestamp,
          level: (log.level || "INFO").toUpperCase(),
          logger: log.logger || "backend",
          message: log.message,
          exception: log.exception,
          source: log.source || "backend",
          extra: log.extra || {}
        });
      });

      diagWatermarkId = data.latest_id;
      if (diagLogs.length > 500) {
        diagLogs = diagLogs.slice(-500);
      }

      updateDiagnosticBadges();
      renderDiagnosticLogs();
    }
  } catch (err) {
    // Silently continue to prevent cascading failures
  }
}

async function fetchDiagnosticHealth() {
  try {
    const res = await _rawFetch("/api/v1/diagnostics/health");
    if (!res.ok) return;

    const data = await res.json();
    const statusEl = document.getElementById("telem-status");
    const walEl = document.getElementById("telem-wal");
    const rootsEl = document.getElementById("telem-roots");
    const threadsEl = document.getElementById("telem-threads");
    const uptimeEl = document.getElementById("telem-uptime");

    if (statusEl) {
      const isDegraded = data.status === "degraded";
      statusEl.textContent = isDegraded ? "Degraded" : "Healthy";
      statusEl.className = isDegraded ? "text-rose" : "text-emerald";
    }

    if (walEl && data.database) {
      walEl.textContent = `${data.database.wal_size_kb || 0} KB (WAL)`;
    }

    if (rootsEl && data.storage) {
      rootsEl.textContent = `${data.storage.online_count}/${data.storage.total_configured} Online`;
    }

    if (threadsEl) {
      threadsEl.textContent = `${data.active_threads || 1} active`;
    }

    if (uptimeEl) {
      uptimeEl.textContent = data.uptime || "--";
    }
  } catch (err) {
    // Skip
  }
}

async function reportFrontendIssueToBackend(message, stack, level = "ERROR") {
  if (isReportingClientIssue) return;
  isReportingClientIssue = true;
  try {
    await _rawFetch("/api/v1/diagnostics/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: String(message),
        stack: stack ? String(stack) : null,
        level: level,
        url: window.location.href
      })
    });
  } catch (_) {
    // Avoid recursive loops if reporting fails
  } finally {
    isReportingClientIssue = false;
  }
}

function toggleDiagnosticConsole(forceState) {
  const win = document.getElementById("diag-console-window");
  if (!win) return;

  if (typeof forceState === "boolean") {
    diagConsoleOpen = forceState;
  } else {
    diagConsoleOpen = !diagConsoleOpen;
  }

  if (diagConsoleOpen) {
    win.classList.remove("hidden");
    renderDiagnosticLogs();
    fetchDiagnosticLogs();
    fetchDiagnosticHealth();
  } else {
    win.classList.add("hidden");
  }
}

function toggleDiagnosticMaximize() {
  const win = document.getElementById("diag-console-window");
  const btn = document.getElementById("btn-diag-maximize");
  if (!win) return;

  diagMaximized = !diagMaximized;
  if (diagMaximized) {
    win.classList.add("maximized");
    if (btn) btn.textContent = "🗕";
  } else {
    win.classList.remove("maximized");
    if (btn) btn.textContent = "🗖";
  }
}

function setDiagFilter(filterName) {
  diagFilter = filterName;
  document.querySelectorAll(".diag-filter-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-filter") === filterName);
  });
  renderDiagnosticLogs();
}

function handleDiagSearch(event) {
  diagSearchQuery = (event.target.value || "").trim().toLowerCase();
  renderDiagnosticLogs();
}

async function clearDiagnosticLogs() {
  try {
    await _rawFetch("/api/v1/diagnostics/clear", { method: "POST" });
  } catch (_) {}

  diagLogs = [];
  diagWatermarkId = 0;
  updateDiagnosticBadges();
  renderDiagnosticLogs();
  showToast("Diagnostic logs cleared", "info", 2500);
}

function copyDiagnosticLogs() {
  const filtered = getFilteredLogs();
  if (filtered.length === 0) {
    showToast("No logs to copy", "info");
    return;
  }

  const textLines = filtered.map(l => {
    let out = `[${l.timestamp}] [${l.source.toUpperCase()}] [${l.level}] [${l.logger}] ${l.message}`;
    if (l.exception) {
      out += `\nStack trace / Payload:\n${l.exception}`;
    }
    return out;
  });

  const fullText = textLines.join("\n\n");
  navigator.clipboard.writeText(fullText).then(() => {
    showToast(`Copied ${filtered.length} log entries to clipboard`, "success");
  }).catch(() => {
    showToast("Failed copying logs to clipboard", "error");
  });
}

async function triggerTestDiagnosticIssue(level = "WARNING") {
  try {
    const res = await _rawFetch(`/api/v1/diagnostics/test-issue?level=${level}`, { method: "POST" });
    if (res.ok) {
      showToast(`Triggered test ${level} log`, "info");
      await fetchDiagnosticLogs();
    }
  } catch (err) {
    showToast("Failed to trigger test issue: " + err, "error");
  }
}

function getFilteredLogs() {
  return diagLogs.filter(item => {
    // Level & Source Filters
    if (diagFilter === "frontend" && item.source !== "frontend") return false;
    if (diagFilter === "backend" && item.source !== "backend") return false;
    if (diagFilter === "errors" && item.level !== "ERROR" && item.level !== "CRITICAL") return false;
    if (diagFilter === "warnings" && item.level !== "WARNING") return false;

    // Search query filter
    if (diagSearchQuery) {
      const matchMsg = (item.message || "").toLowerCase().includes(diagSearchQuery);
      const matchLogger = (item.logger || "").toLowerCase().includes(diagSearchQuery);
      const matchExc = (item.exception || "").toLowerCase().includes(diagSearchQuery);
      if (!matchMsg && !matchLogger && !matchExc) return false;
    }

    return true;
  });
}

function renderDiagnosticLogs() {
  const container = document.getElementById("diag-log-container");
  const listEl = document.getElementById("diag-log-list");
  const emptyEl = document.getElementById("diag-empty-state");
  const autoScroll = document.getElementById("diag-autoscroll")?.checked ?? true;

  if (!listEl) return;

  const filtered = getFilteredLogs();

  if (filtered.length === 0) {
    if (emptyEl) emptyEl.style.display = "flex";
    listEl.innerHTML = "";
    return;
  }

  if (emptyEl) emptyEl.style.display = "none";

  const rowsHtml = filtered.map(log => {
    const lvl = (log.level || "INFO").toLowerCase();
    const src = (log.source || "backend").toLowerCase();
    const hasStack = Boolean(log.exception);
    const stackId = `diag-stack-${String(log.id).replace(/[^a-zA-Z0-9]/g, "_")}`;

    let levelClass = "level-info";
    if (lvl === "error" || lvl === "critical") levelClass = "level-error";
    else if (lvl === "warning" || lvl === "warn") levelClass = "level-warning";
    else if (lvl === "success") levelClass = "level-success";

    return `
      <div class="diag-log-row ${levelClass}">
        <div class="diag-log-header">
          <span class="diag-log-time">[${escapeHtml(log.timestamp)}]</span>
          <span class="diag-log-src src-${escapeHtml(src)}">${escapeHtml(src)}</span>
          <span class="diag-log-lvl lvl-${escapeHtml(lvl)}">${escapeHtml(log.level)}</span>
          <span class="diag-log-logger">${escapeHtml(log.logger)}</span>
        </div>
        <div class="diag-log-msg">${escapeHtml(log.message)}</div>
        ${hasStack ? `
          <span class="diag-log-details-toggle" onclick="toggleDiagStack('${stackId}')">
            ▶ Details / Trace
          </span>
          <div id="${stackId}" class="diag-log-stack hidden">${escapeHtml(log.exception)}</div>
        ` : ""}
      </div>
    `;
  }).join("");

  listEl.innerHTML = rowsHtml;

  if (autoScroll && container) {
    container.scrollTop = container.scrollHeight;
  }
}

function toggleDiagStack(stackId) {
  const el = document.getElementById(stackId);
  if (!el) return;
  const isHidden = el.classList.contains("hidden");
  el.classList.toggle("hidden", !isHidden);
}

function updateDiagnosticBadges() {
  const errorCount = diagLogs.filter(l => l.level === "ERROR" || l.level === "CRITICAL").length;
  const warningCount = diagLogs.filter(l => l.level === "WARNING").length;
  const totalIssues = errorCount + warningCount;

  // Header counters
  const errEl = document.getElementById("diag-count-errors");
  const warnEl = document.getElementById("diag-count-warnings");
  if (errEl) errEl.textContent = `${errorCount} ❌`;
  if (warnEl) warnEl.textContent = `${warningCount} ⚠️`;

  // Filter toolbar counts
  const allEl = document.getElementById("filter-count-all");
  const feEl = document.getElementById("filter-count-frontend");
  const beEl = document.getElementById("filter-count-backend");
  const errFilterEl = document.getElementById("filter-count-errors");
  const warnFilterEl = document.getElementById("filter-count-warnings");

  if (allEl) allEl.textContent = diagLogs.length;
  if (feEl) feEl.textContent = diagLogs.filter(l => l.source === "frontend").length;
  if (beEl) beEl.textContent = diagLogs.filter(l => l.source === "backend").length;
  if (errFilterEl) errFilterEl.textContent = errorCount;
  if (warnFilterEl) warnFilterEl.textContent = warningCount;

  // Floating pill status & badge
  const pillBadge = document.getElementById("diag-pill-badge");
  const pillPulse = document.getElementById("diag-pill-pulse");
  const navBadge = document.getElementById("nav-diag-badge");

  if (pillBadge) {
    if (errorCount > 0) {
      pillBadge.textContent = `${errorCount} error${errorCount > 1 ? 's' : ''}`;
      pillBadge.className = "diag-pill-badge has-error";
    } else if (warningCount > 0) {
      pillBadge.textContent = `${warningCount} warn${warningCount > 1 ? 's' : ''}`;
      pillBadge.className = "diag-pill-badge has-warning";
    } else {
      pillBadge.textContent = "0 issues";
      pillBadge.className = "diag-pill-badge clean";
    }
  }

  if (pillPulse) {
    pillPulse.className = "diag-pill-pulse" + (errorCount > 0 ? " has-error" : (warningCount > 0 ? " has-warning" : ""));
  }

  if (navBadge) {
    if (totalIssues > 0) {
      navBadge.textContent = totalIssues;
      navBadge.classList.remove("hidden");
    } else {
      navBadge.classList.add("hidden");
    }
  }
}

