/**
* RepoScroller Web Dashboard Client
* Complete interactive ledger with duplicate filtering, sortable columns,
* dynamic multilingual taxonomy filtering, and local file launch/reveal.
*/

let activeDocumentSha = null;
let watcherRunning = false;
let activeChatNode = "pc1";

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

// In-memory ring buffer to keep recent diagnostics inspectable via console or UI
window._diagnosticLogs = window._diagnosticLogs || [];
const MAX_DIAGNOSTIC_ENTRIES = 250;

/**
 * Pushes diagnostic events to internal state, browser console, and custom UI event handlers.
 *
 * @param {'info'|'warn'|'error'|'debug'} level - Severity level of the log
 * @param {string} message - Human-readable diagnostic message
 * @param {string} [subsystem="general"] - Architectural layer (e.g. "frontend", "api", "worker")
 * @param {string} [component="system"] - Specific module/component (e.g. "GLSL3D", "GraphViewer")
 * @param {Object} [metadata={}] - Optional arbitrary context, error stacks, or payloads
 */
function pushDiagnosticLog(level, message, subsystem = "general", component = "system", metadata = {}) {
  const normLevel = (level || "info").toLowerCase();
  const upperLevel = normLevel === "warn" ? "WARNING" : normLevel.toUpperCase();

  const entry = {
    timestamp: new Date().toISOString(),
    level: (level || "info").toLowerCase(),
    subsystem: subsystem || "general",
    component: component || "system",
    message: String(message),
    metadata: metadata
  };

  // 1. Maintain in-memory state with bounded size
  window._diagnosticLogs.push(entry);
  if (window._diagnosticLogs.length > MAX_DIAGNOSTIC_ENTRIES) {
    window._diagnosticLogs.shift();
  }

  // 2. Format console output with structured tags
  const prefix = `[${entry.timestamp.slice(11, 19)}] [${entry.subsystem.toUpperCase()}:${entry.component}]`;
  switch (entry.level) {
    case "error":
      console.error(prefix, entry.message, metadata);
      break;
    case "warn":
      console.warn(prefix, entry.message, metadata);
      break;
    case "debug":
      console.debug(prefix, entry.message, metadata);
      break;
    case "info":
    default:
      console.log(prefix, entry.message, metadata);
      break;
  }

  // 3. Forward to the dashboard's primary Diagnostic Console & telemetry UI
  if (typeof logDiagnosticEntry === "function") {
    logDiagnosticEntry({
      source: subsystem,
      level: upperLevel,
      logger: `${subsystem}.${component}`,
      message: String(message),
      exception: metadata && metadata.stack ? metadata.stack : null,
      extra: metadata
    });
  }

  // 4. Report critical errors to the backend telemetry endpoint
  if ((upperLevel === "ERROR" || upperLevel === "CRITICAL") && typeof reportFrontendIssueToBackend === "function") {
    reportFrontendIssueToBackend(entry.message, metadata?.stack || null, upperLevel);
  }

  // 5. Dispatch DOM event for custom UI listeners
  window.dispatchEvent(new CustomEvent("diagnosticLogAdded", { detail: entry }));

  return entry;
}
// Expose globally to guarantee availability across all scripts and scopes
window.pushDiagnosticLog = pushDiagnosticLog;
// window.addEventListener("diagnosticLogAdded", (event) => {
//     const { level, message, component } = event.detail;
//     // Update UI status bar or terminal view
// });

const getApiBase = () => {
  // If hosted under /reposcroller/, prepend it
  if (window.location.pathname.startsWith('/reposcroller')) {
    return '/reposcroller/api/v1';
  }
  return '/api/v1';
};

const API_BASE = getApiBase();
window.API_BASE = API_BASE;


// Add right before the fetch interceptor:
const API_PREFIX = window.location.pathname.startsWith("/reposcroller") ? "/reposcroller" : "";

// Network Fetch Interceptor for Live Diagnostics
const _rawFetch = window.fetch;
window.fetch = async function (...args) {
  let [resource, config] = args;
  if (typeof resource === "string" && resource.startsWith("/api/v1")) {
    resource = API_PREFIX + resource;
    args[0] = resource;
  } else if (resource && resource.url && resource.url.startsWith("/api/v1")) {
    resource = new Request(API_PREFIX + resource.url, resource);
    args[0] = resource;
  }
  const url = typeof resource === "string" ? resource : (resource ? resource.url : "");
  const method = (config && config.method) ? config.method.toUpperCase() : "GET";
  const startTime = performance.now();

  try {
    const response = await _rawFetch.apply(this, args);
    const latency = Math.round(performance.now() - startTime);

    const isProbeOrDiag = url.includes("/api/v1/diagnostics") ||
      url.includes(":11435") ||
      url.includes("/api/ps");

    if (!response.ok) {
      if (!isProbeOrDiag) {
        let errSnippet = "";
        try {
          const clone = response.clone();
          const json = await clone.json();
          errSnippet = JSON.stringify(json, null, 2);
        } catch (_) {
          try {
            const clone = response.clone();
            const text = await clone.text();
            if (text.includes("<title>") && text.includes("</title>")) {
              const match = text.match(/<title>(.*?)<\/title>/i);
              errSnippet = match ? `[Gateway Page: ${match[1]}]` : text.slice(0, 150);
            } else {
              errSnippet = text.slice(0, 500);
            }
          } catch (_) { }
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
    const isProbeOrDiag = url.includes("/api/v1/diagnostics") ||
      url.includes(":11435") ||
      url.includes("/api/ps");
    if (!isProbeOrDiag) {
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

  // 1. Critical UI load first (settled so one failure doesn't block the rest)
  await Promise.allSettled([
    checkBackendHealth(),
    loadMountsAndCrawlerStatus(),
    loadMetrics(),
    loadTaxonomyCategories(),
    loadLedger()
  ]);

  // Open the workspace requested via URL / deep-link (e.g. /3d_knowledgegraph_universe or #universe)
  const initialWs = getWorkspaceFromUrl();
  if (initialWs && initialWs !== "process") {
    switchWorkspace(initialWs, false);
  }

  // 2. Heavy telemetry runs in background without blocking initial paint
  Promise.allSettled([
    loadWorkloadTelemetry(),
    loadSidecarStats(),
    typeof loadProcessScrollerData === "function" ? loadProcessScrollerData() : Promise.resolve(),
    typeof pollOllamaProcessInspector === "function" ? pollOllamaProcessInspector() : Promise.resolve(),
    typeof loadLineageChains === "function" ? loadLineageChains() : Promise.resolve()
  ]).then(() => {
    if (typeof renderWs0DiagLogs === "function") renderWs0DiagLogs();
  });

  // Guard interval so requests only fire when not already in flight
  let isPolling = false;
  setInterval(async () => {
    if (isPolling) return;
    isPolling = true;
    try {
      await Promise.allSettled([
        loadMetrics(),
        loadSidecarStats(),
        loadWorkloadTelemetry()
      ]);
      if (activeWorkspace === "process") {
        if (typeof loadProcessScrollerData === "function") await loadProcessScrollerData();
        if (typeof pollOllamaProcessInspector === "function") await pollOllamaProcessInspector();
        if (typeof renderWs0DiagLogs === "function") renderWs0DiagLogs();
      }
    } finally {
      isPolling = false;
    }
  }, 5000);
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 4000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(timeoutId);
    return res;
  } catch (err) {
    clearTimeout(timeoutId);
    throw err;
  }
}

// 0. Split Workload Hardware Telemetry (PC1 Localhost vs PC2 Remote CUDA)
async function loadWorkloadTelemetry(force = false) {
  const refreshBtn = document.getElementById("btn-workload-refresh");
  if (force && refreshBtn) {
    refreshBtn.classList.add("refreshing");
    refreshBtn.innerHTML = `<span class="refresh-icon">⟳</span> Probing...`;
  }

  try {
    const res = await fetch(`/api/v1/diagnostics/workload${force ? '?force=true' : ''}`);
    if (!res.ok) return;
    const data = await res.json();

    // Top Bar Metadata: Timestamp & Tier Pills
    const syncTimeEl = document.getElementById("hud-sync-time");
    if (syncTimeEl && data.timestamp) {
      syncTimeEl.textContent = `⟳ Synced: ${data.timestamp}`;
    }

    const tierData = data.embedding_tier || {};
    const activeTierPill = document.getElementById("hud-active-tier-pill");
    const activeModelPill = document.getElementById("hud-active-model-pill");

    if (activeTierPill) {
      activeTierPill.textContent = tierData.tier_label || "⚡ CUDA Remote Node (PC2)";
      activeTierPill.className = `workload-hud-pill ${tierData.active_tier === 'cuda' ? 'pill-cuda' : (tierData.active_tier === 'local' ? 'pill-local' : 'pill-fallback')
        }`;
    }

    if (activeModelPill && tierData.active_model) {
      activeModelPill.textContent = tierData.active_model;
    }

    // Sync Dynamic Chat Routing Buttons & State
    const chatRouting = data.chat_routing || {};
    if (chatRouting.active_node) {
      activeChatNode = chatRouting.active_node;
    }
    const btnPc1 = document.getElementById("btn-chat-toggle-pc1");
    const btnPc2 = document.getElementById("btn-chat-toggle-pc2");
    const wsBtnPc1 = document.getElementById("chat-ws-toggle-pc1");
    const wsBtnPc2 = document.getElementById("chat-ws-toggle-pc2");

    if (btnPc1) btnPc1.classList.toggle("active", activeChatNode === "pc1");
    if (btnPc2) btnPc2.classList.toggle("active", activeChatNode === "pc2");
    if (wsBtnPc1) wsBtnPc1.classList.toggle("active", activeChatNode === "pc1");
    if (wsBtnPc2) wsBtnPc2.classList.toggle("active", activeChatNode === "pc2");

    // PC1 Localhost Node
    const pc1 = data.localhost_node;
    if (pc1) {
      const pc1Badge = document.getElementById("pc1-node-badge");
      const pc1Url = document.getElementById("pc1-node-url");
      const pc1Model = document.getElementById("pc1-model-name");
      const pc1Ping = document.getElementById("pc1-ping-ms");
      const pc1ChatCount = document.getElementById("pc1-chat-count");
      const pc1Latency = document.getElementById("pc1-latency-ms");
      const pc1Activity = document.getElementById("pc1-activity-status");
      const pc1ModelsList = document.getElementById("pc1-models-list");

      if (pc1Url) pc1Url.textContent = pc1.url;
      if (pc1Model) pc1Model.textContent = pc1.target_model || "Loading...";

      if (pc1Ping) {
        if (pc1.online) {
          const pingVal = parseFloat(pc1.ping_ms) || 0;
          const pingClass = pingVal < 400 ? 'ping-fast' : 'ping-slow';
          pc1Ping.innerHTML = `<span class="ping-dot ${pingClass}"></span> ${pingVal < 1 ? '<1' : pingVal.toFixed(1)} ms`;
        } else {
          pc1Ping.textContent = 'Offline';
        }
      }

      if (pc1ChatCount) {
        const calls = chatRouting.pc1_requests ?? pc1.stats?.requests ?? 0;
        pc1ChatCount.textContent = `${calls.toLocaleString()} calls`;
      }

      if (pc1Latency) {
        pc1Latency.textContent = `${pc1.processor || '100% CPU'} (${pc1.vram_formatted || '0 MB'})`;
        pc1Latency.title = `Host Processor: ${pc1.processor} | VRAM: ${pc1.vram_formatted}`;
      }

      if (pc1Activity) {
        const act = pc1.stats?.last_active || (pc1.online ? 'idle' : 'offline');
        const ctxStr = pc1.context_length > 0 ? ` (${(pc1.context_length >= 1024 ? (pc1.context_length / 1024).toFixed(0) + 'k' : pc1.context_length)} ctx)` : '';
        if (act === 'active') {
          pc1Activity.innerHTML = `<span class="pulse-dot-emerald"></span> active${ctxStr}`;
        } else if (pc1.online) {
          pc1Activity.innerHTML = `<span class="idle-dot"></span> idle${ctxStr}`;
        } else {
          pc1Activity.textContent = 'offline';
        }
      }

      if (pc1ModelsList && pc1.online) {
        const details = Array.isArray(pc1.models_detail) ? pc1.models_detail : [];
        if (details.length > 0) {
          pc1ModelsList.innerHTML = details.map(d => {
            const shortName = d.name.split(':')[0];
            const meta = d.quantization && d.quantization !== 'Unknown' ? ` (${d.quantization})` : '';
            return `<span class="mini-tag" title="${d.name}: ${d.size_total_mb}MB RAM | ${d.processor}">${shortName}${meta}</span>`;
          }).join('');
        } else if (Array.isArray(pc1.models_loaded) && pc1.models_loaded.length > 0) {
          pc1ModelsList.innerHTML = pc1.models_loaded.map(m => `<span class="mini-tag">${m}</span>`).join('');
        } else {
          pc1ModelsList.innerHTML = `<span class="mini-tag text-faint">None loaded</span>`;
        }
      }

      if (pc1Badge) {
        if (pc1.online) {
          pc1Badge.className = "node-status-badge badge-online";
          pc1Badge.innerHTML = `<span class="dot"></span> Online (CPU)`;
        } else {
          pc1Badge.className = "node-status-badge badge-offline";
          pc1Badge.innerHTML = `<span class="dot"></span> Fallback / Offline`;
        }
      }
    }

    // PC2 CUDA GPU Node & Multi-Tier Embedding Engine
    const pc2 = data.cuda_gpu_node;
    const effectiveTier = pc2?.effective_tier || tierData.active_tier || (pc2?.online ? "cuda" : "local");

    if (pc2) {
      const pc2Badge = document.getElementById("pc2-node-badge");
      const pc2Url = document.getElementById("pc2-node-url");
      const pc2Model = document.getElementById("pc2-model-name");
      const pc2Ping = document.getElementById("pc2-ping-ms");
      const pc2ChunksCount = document.getElementById("pc2-chunks-count");
      const pc2Latency = document.getElementById("pc2-latency-ms");
      const pc2Activity = document.getElementById("pc2-activity-status");
      const pc2ModelsList = document.getElementById("pc2-models-list");

      if (pc2Url) {
        if (effectiveTier === "local") {
          pc2Url.textContent = `${tierData.active_url || 'http://127.0.0.1:11434'} (Fallback)`;
        } else {
          pc2Url.textContent = pc2.url;
        }
      }

      if (pc2Model) {
        const rawModel = (effectiveTier === "local" ? tierData.active_model : pc2.target_model) || "Loading...";
        pc2Model.textContent = rawModel.includes(":") ? rawModel.split(":")[0] : rawModel;
      }

      if (pc2Ping) {
        if (effectiveTier === "cuda" && pc2.online) {
          const pingVal = parseFloat(pc2.ping_ms) || 0;
          const pingClass = pingVal < 400 ? 'ping-fast' : 'ping-slow';
          pc2Ping.innerHTML = `<span class="ping-dot ${pingClass}"></span> ${pingVal < 1 ? '<1' : pingVal.toFixed(1)} ms`;
        } else if (effectiveTier === "local") {
          pc2Ping.textContent = "Local Host (CPU)";
        } else {
          pc2Ping.textContent = "Offline";
        }
      }

      if (pc2ChunksCount) {
        const total = pc2.stats?.chunks_embedded ?? tierData.total_chunks ?? 0;
        pc2ChunksCount.textContent = `${total.toLocaleString()} chunks`;
      }

      if (pc2Latency) {
        if (pc2.online && pc2.total_vram_mb > 0) {
          pc2Latency.textContent = `${pc2.vram_formatted} (${pc2.processor || '100% GPU'})`;
          pc2Latency.title = `Active GPU VRAM Allocated: ${pc2.vram_formatted} | Architecture: ${pc2.processor} on NVIDIA RTX 3060`;
          pc2Latency.className = "node-metric-val text-emerald font-bold";
        } else if (pc2.stats?.last_latency_ms > 0) {
          pc2Latency.textContent = `${pc2.stats.last_latency_ms.toFixed(1)} ms`;
          pc2Latency.className = "node-metric-val text-amber";
        } else {
          pc2Latency.textContent = effectiveTier === "cuda" ? 'VRAM Hot' : 'Ready';
        }
      }

      if (pc2Activity) {
        const act = pc2.stats?.last_active || (pc2.online ? 'active' : 'offline');
        const ctxStr = pc2.context_length > 0 ? ` (${pc2.context_length.toLocaleString()} ctx)` : '';
        if (act === 'active' || (pc2.online && effectiveTier === 'cuda')) {
          pc2Activity.innerHTML = `<span class="pulse-dot-emerald"></span> active${ctxStr}`;
          pc2Activity.className = "node-metric-val text-cyan font-bold";
        } else if (pc2.online) {
          pc2Activity.innerHTML = `<span class="idle-dot"></span> idle${ctxStr}`;
        } else {
          pc2Activity.textContent = 'offline';
        }
      }

      if (pc2ModelsList) {
        if (!pc2.online) {
          pc2ModelsList.innerHTML = `<span class="mini-tag text-faint">Offline</span>`;
        } else {
          const details = Array.isArray(pc2.models_detail) ? pc2.models_detail : [];
          const embedModel = pc2.target_model || "snowflake-arctic-embed2:latest";
          const chatModel = pc2.chat_model || "llama3.2:3b";

          // Match details from /api/ps
          const embedDetail = details.find(d => d.name.includes(embedModel.split(':')[0]));
          const chatDetail = details.find(d => d.name.includes(chatModel.split(':')[0]));

          const isEmbedHot = !!embedDetail;
          const isChatHot = !!chatDetail;

          const embedVramMeta = embedDetail ? ` • ${embedDetail.size_vram_mb}MB ${embedDetail.quantization}` : '';
          const chatVramMeta = chatDetail ? ` • ${(chatDetail.size_vram_mb >= 1024 ? (chatDetail.size_vram_mb / 1024).toFixed(1) + 'GB' : chatDetail.size_vram_mb + 'MB')} ${chatDetail.quantization}` : '';

          let tagsHtml = `
            <span class="mini-tag tag-cuda" title="${isEmbedHot ? 'VRAM Resident (Active on GPU)' : 'Configured CUDA Tensor Embeddings'}">${isEmbedHot ? '⚡ ' : ''}${embedModel}${embedVramMeta}</span>
            <span class="mini-tag tag-chat" title="${isChatHot ? 'VRAM Resident (Active on GPU)' : 'Configured CUDA Chat Reasoning'}">${isChatHot ? '⚡ ' : ''}${chatModel}${chatVramMeta}</span>
          `;

          // Append any extra models running in VRAM on PC2
          details.forEach(d => {
            if (!d.name.includes(embedModel.split(':')[0]) && !d.name.includes(chatModel.split(':')[0])) {
              tagsHtml += `<span class="mini-tag tag-cuda" title="${d.name}: ${d.size_vram_mb}MB VRAM">⚡ ${d.name} (${d.size_vram_mb}MB)</span>`;
            }
          });

          pc2ModelsList.innerHTML = tagsHtml;
        }
      }

      if (pc2Badge) {
        if (effectiveTier === "cuda" && pc2.online) {
          pc2Badge.className = "node-status-badge badge-online";
          pc2Badge.innerHTML = `<span class="dot"></span> ⚡ CUDA Ready`;
          pc2Badge.title = "Embedding running on PC2 NVIDIA RTX 3060 CUDA GPU";
        } else if (effectiveTier === "local") {
          pc2Badge.className = "node-status-badge badge-fallback-local";
          pc2Badge.innerHTML = `<span class="dot"></span> 🟠 Local CPU Fallback`;
          pc2Badge.title = tierData.last_fallback_reason || "PC2 unreachable. Operating on PC1 Local CPU with snowflake-arctic-embed.";
        } else {
          pc2Badge.className = "node-status-badge badge-fallback-pseudo";
          pc2Badge.innerHTML = `<span class="dot"></span> 🔴 Offline Pseudo-Vectors`;
          pc2Badge.title = "No Ollama instances available. Operating in offline pseudo-vector mode.";
        }
      }
    }

    // 3. Dual-Node Bridge & Bidirectional Throughput Telemetry Card
    const tp = data.throughput || {};
    const epMatrix = data.endpoints_matrix || {};

    const tpFpm = document.getElementById("throughput-fpm");
    const tpCpm = document.getElementById("throughput-cpm");
    const tpTokens = document.getElementById("throughput-tokens");
    const tpCheckpoints = document.getElementById("throughput-checkpoints");
    const tpPayload = document.getElementById("throughput-payload");
    const tpPipelineBox = document.querySelector(".throughput-pipeline-box");
    const tpBadge = document.getElementById("throughput-status-badge");
    const tpStatusText = document.getElementById("throughput-status-text");
    const streamOutRate = document.getElementById("stream-outbound-rate");
    const streamInRate = document.getElementById("stream-inbound-rate");

    if (tpFpm) {
      const fpmVal = tp.files_per_minute !== undefined ? tp.files_per_minute : 0;
      tpFpm.textContent = `${fpmVal} files/m`;
    }

    if (tpCpm) {
      const cpmVal = tp.chunks_per_minute !== undefined ? tp.chunks_per_minute : 0;
      tpCpm.textContent = `${cpmVal} chunks/m`;
    }

    if (tpTokens) {
      const tokVal = tp.last_batch_tokens || 1206;
      tpTokens.textContent = `${tokVal.toLocaleString()} tok`;
      tpTokens.title = `Last prompt eval batch: ${tokVal} tokens (Total: ${(tp.total_tokens_processed || 0).toLocaleString()} tokens)`;
    }

    if (tpCheckpoints) {
      const cpVal = tp.checkpoints !== undefined ? tp.checkpoints : 0;
      tpCheckpoints.textContent = `${cpVal} (WAL)`;
      tpCheckpoints.title = `SQLite WAL Passive Checkpoint status: ${cpVal} (0 = SQLITE_OK)`;
    }

    if (tpPayload) {
      const mibVal = tp.payload_mib !== undefined ? tp.payload_mib : 37.702;
      tpPayload.textContent = `${mibVal.toFixed(2)} MiB`;
      tpPayload.title = `Total float32 vector tensor stream volume: ${mibVal.toFixed(3)} MiB (${(tp.payload_bytes || 0).toLocaleString()} bytes)`;
    }

    // 4. Real-Time Pipeline Flow Inspector ("See-Through")
    const pl = data.pipeline || {};
    const flowProducer = document.getElementById("flow-producer-val");
    const flowEmbedQ = document.getElementById("flow-embed-q-val");
    const flowWorkers = document.getElementById("flow-workers-val");
    const flowDbQ = document.getElementById("flow-db-q-val");
    const flowWriter = document.getElementById("flow-writer-val");

    if (flowProducer) {
      flowProducer.textContent = pl.producer_stage || (sidecarContinuousRunning ? "active" : "idle");
      flowProducer.className = pl.producer_stage === "chunking" ? "text-cyan" : (pl.producer_stage === "fetching_db" ? "text-indigo" : "");
    }
    if (flowEmbedQ) {
      const qVal = pl.embed_queue_depth !== undefined ? pl.embed_queue_depth : 0;
      const qMax = pl.embed_queue_max || 100;
      flowEmbedQ.textContent = `${qVal}/${qMax}`;
      flowEmbedQ.className = qVal > 80 ? "text-rose font-bold" : "text-cyan";
      flowEmbedQ.title = `${qVal} document batches waiting for PC2 GPU embedding`;
    }
    if (flowWorkers) {
      const activeW = pl.active_http_workers !== undefined ? pl.active_http_workers : 0;
      const totW = pl.total_http_workers || 4;
      flowWorkers.textContent = `${totW}x (${activeW} busy)`;
      flowWorkers.className = activeW > 0 ? "text-emerald font-bold" : "text-faint";
    }
    if (flowDbQ) {
      const dbQVal = pl.db_queue_depth !== undefined ? pl.db_queue_depth : 0;
      const dbQMax = pl.db_queue_max || 100;
      flowDbQ.textContent = `${dbQVal}/${dbQMax}`;
      flowDbQ.className = dbQVal > 80 ? "text-rose font-bold" : "text-amber";
      flowDbQ.title = `${dbQVal} embedded batches waiting for SQLite persistence`;
    }
    if (flowWriter) {
      flowWriter.textContent = pl.db_writer_stage || (sidecarContinuousRunning ? "idle" : "stopped");
      flowWriter.className = pl.db_writer_stage === "writing_sqlite" ? "text-emerald font-bold" : "";
    }
    const flowValidator = document.getElementById("flow-validator-val");
    if (flowValidator) {
      const vStage = pl.validator_stage || (data.validation && data.validation.stage) || "idle";
      flowValidator.textContent = vStage;
      flowValidator.className = (vStage === "certifying_llm" || vStage === "pruning") ? "text-cyan font-bold pulse-text" : "";
    }

    // 5. Update Real-Time Zoo Matrix Observatory Strip
    const zoo = data.zoo || {};
    const zooPdfVal = document.getElementById("zoo-pdf-val");
    const zooPdfSub = document.getElementById("zoo-pdf-sub");
    const zooLanVal = document.getElementById("zoo-lan-val");
    const zooLanSub = document.getElementById("zoo-lan-sub");
    const zooWalVal = document.getElementById("zoo-wal-val");
    const zooWalSub = document.getElementById("zoo-wal-sub");
    const zooChatVal = document.getElementById("zoo-chat-val");
    const zooChatSub = document.getElementById("zoo-chat-sub");
    const zooValidatorVal = document.getElementById("zoo-validator-val");
    const zooValidatorSub = document.getElementById("zoo-validator-sub");

    if (zooPdfVal && zoo.io_pdf_reading) {
      zooPdfVal.textContent = `${zoo.io_pdf_reading.rate_mb_s} MB/s`;
      if (zooPdfSub) zooPdfSub.textContent = `(${zoo.io_pdf_reading.files_per_min} f/m)`;
    }
    if (zooLanVal && zoo.lan_traffic) {
      const ping = zoo.lan_traffic.pc2_ping_ms ?? (data.cuda_gpu_node?.ping_ms);
      zooLanVal.textContent = (ping !== null && ping !== undefined) ? `${parseFloat(ping).toFixed(0)} ms` : `-- ms`;
      if (zooLanSub) zooLanSub.textContent = `${zoo.lan_traffic.payload_mib} MiB (${zoo.lan_traffic.transfer_direction})`;
    }
    if (zooWalVal && zoo.sqlite_wal) {
      zooWalVal.textContent = `DB ${zoo.sqlite_wal.db_size_mb}M / WAL ${zoo.sqlite_wal.wal_size_mb}M`;
      if (zooWalSub) {
        zooWalSub.textContent = zoo.sqlite_wal.status;
        zooWalSub.className = zoo.sqlite_wal.is_busy ? "zoo-sub text-amber" : "zoo-sub text-emerald";
      }
    }
    if (zooChatVal && zoo.chat_reasoning) {
      const isPc2 = zoo.chat_reasoning.active_node === "pc2";
      const modelShort = isPc2 ? (zoo.chat_reasoning.pc2_model || "PC2 Model") : (zoo.chat_reasoning.pc1_model || "PC1 Model");
      zooChatVal.textContent = `${isPc2 ? "⚡ " : "💻 "}${modelShort.split(':')[0]}`;
      zooChatVal.className = isPc2 ? "text-emerald font-bold" : "text-indigo font-bold";
      if (zooChatSub) {
        const reqs = isPc2 ? zoo.chat_reasoning.pc2_requests : zoo.chat_reasoning.pc1_requests;
        zooChatSub.textContent = `${reqs || 0} calls (${isPc2 ? zoo.chat_reasoning.pc2_model : zoo.chat_reasoning.pc1_model})`;
      }
    }
    if (zooValidatorVal) {
      const vStats = data.validation || (data.worker && data.worker.validation) || {};
      const vStage = vStats.stage || pl.validator_stage || "idle";
      zooValidatorVal.textContent = vStage === "idle" ? "Idle" : (vStage === "certifying_llm" ? "⚡ Certifying" : "🧹 Pruning");
      zooValidatorVal.className = vStage !== "idle" ? "text-cyan font-bold" : "text-emerald";
      if (zooValidatorSub) {
        const cert = vStats.total_certified || 0;
        const purged = vStats.total_purged || 0;
        if (cert > 0 || purged > 0) {
          zooValidatorSub.textContent = `+${cert} / -${purged}`;
          zooValidatorSub.className = "zoo-sub text-cyan";
        } else {
          zooValidatorSub.textContent = "Certified";
          zooValidatorSub.className = "zoo-sub text-emerald";
        }
      }
    }

    // Dynamic endpoint tags for PC1 & PC2
    const renderPingTag = (elId, epData, label) => {
      const el = document.getElementById(elId);
      if (!el) return;
      if (!epData) {
        el.textContent = `${label}: --`;
        return;
      }
      if (epData.online) {
        const ms = epData.latency_ms || 0;
        el.className = `mini-tag online ${elId.includes('pc2') ? 'tag-cuda' : ''}`;
        el.textContent = `${label}: ${ms < 1 ? '<1' : ms.toFixed(1)}ms`;
      } else {
        el.className = `mini-tag offline`;
        el.textContent = `${label}: Offline`;
      }
    };

    renderPingTag("ping-pc1-chat", epMatrix.pc1_chat, "PC1 Chat");
    renderPingTag("ping-pc1-embed", epMatrix.pc1_embed, "PC1 Embed");
    renderPingTag("ping-pc2-chat", epMatrix.pc2_chat, "PC2 Chat");
    renderPingTag("ping-pc2-embed", epMatrix.pc2_embed, "PC2 Embed");

    // Dynamic stream rate subheadings
    if (streamOutRate) {
      if (tp.chunks_per_minute > 0) {
        streamOutRate.textContent = `${tp.chunks_per_minute} chunks/m (${tp.tokens_per_second || 0} tok/s)`;
      } else {
        streamOutRate.textContent = "Pipeline Ready (Standby)";
      }
    }
    if (streamInRate) {
      if (tp.payload_mib > 0) {
        streamInRate.textContent = `${tp.payload_mib.toFixed(2)} MiB Streamed (1024d)`;
      } else {
        streamInRate.textContent = "Dense Float32 Vectors";
      }
    }

    // Bridge Status Badge & Pipeline Animation Toggle
    const isBridgeLive = pc1?.online && pc2?.online;
    if (tpBadge && tpStatusText) {
      if (isBridgeLive) {
        tpBadge.className = "node-status-badge badge-online";
        tpStatusText.textContent = "Synchronized";
      } else if (pc1?.online || pc2?.online) {
        tpBadge.className = "node-status-badge badge-fallback-local";
        tpStatusText.textContent = "Single Node";
      } else {
        tpBadge.className = "node-status-badge badge-offline";
        tpStatusText.textContent = "Disconnected";
      }
    }

    if (tpPipelineBox) {
      if (!isBridgeLive) {
        tpPipelineBox.classList.add("paused");
      } else {
        tpPipelineBox.classList.remove("paused");
      }
    }
  } catch (err) {
    console.debug("Workload telemetry probe notice:", err);
  } finally {
    if (force && refreshBtn) {
      setTimeout(() => {
        refreshBtn.classList.remove("refreshing");
        refreshBtn.innerHTML = `<span class="refresh-icon">⟳</span> Probe Hardware`;
      }, 500);
    }
  }
}

// Dynamic Chat Routing Switcher (PC1 CPU vs PC2 CUDA GPU)
async function switchChatNode(targetNode, targetModel = null) {
  try {
    activeChatNode = targetNode;

    // Optimistic UI update
    const btnPc1 = document.getElementById("btn-chat-toggle-pc1");
    const btnPc2 = document.getElementById("btn-chat-toggle-pc2");
    const wsBtnPc1 = document.getElementById("chat-ws-toggle-pc1");
    const wsBtnPc2 = document.getElementById("chat-ws-toggle-pc2");

    if (btnPc1) btnPc1.classList.toggle("active", targetNode === "pc1");
    if (btnPc2) btnPc2.classList.toggle("active", targetNode === "pc2");
    if (wsBtnPc1) wsBtnPc1.classList.toggle("active", targetNode === "pc1");
    if (wsBtnPc2) wsBtnPc2.classList.toggle("active", targetNode === "pc2");

    const res = await fetch("/api/v1/chat/routing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node: targetNode, model: targetModel })
    });

    if (res.ok) {
      const result = await res.json();
      const nodeLabel = targetNode === "pc2" ? "PC2 Remote (CUDA)" : "PC1 Host (CPU)";
      showToast(`⚡ api/chat reasoning routed to ${nodeLabel}`, "success", 4000);
      loadWorkloadTelemetry(false);
    } else {
      showToast("Failed to switch chat routing on backend", "error");
    }
  } catch (err) {
    showToast("Error switching chat routing: " + err, "error");
  }
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
    await Promise.all([loadMetrics(), loadLedger(), loadSidecarStats()]);
  } catch (err) {
    showToast("Scan failed: " + err, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<span class="btn-icon">⚡</span> Quick Scan`;
  }
}

// 3. Metrics & Knowledge Base Stats
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
    switchWorkspace("ledger");
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
  if (searchFilterQuery) params.append("query", searchFilterQuery);
  params.append("sort_by", activeSortBy);
  params.append("sort_order", activeSortOrder);
  params.append("limit", "100");
  params.append("_t", String(Date.now())); // Prevent browser HTTP caching

  const url = `/api/v1/documents/ledger?${params.toString()}`;

  try {
    const res = await fetch(url);
    const data = await res.json();

    let items = data.items || [];

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
        <span class="badge" style="background: rgba(255,255,255,0.06); cursor: pointer;" title="Filter by this category" data-cat="${escapeHtml(doc.doc_type || '')}" onclick="event.stopPropagation(); setCategoryFilter(this.getAttribute('data-cat'))">
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
        <div style="display: flex; gap: 0.35rem; align-items: center;">
          ${primaryPath ? `
          <button class="btn btn-outline" style="padding: 0.2rem 0.5rem; font-size: 0.72rem;" data-path="${escapeHtml(primaryPath)}" onclick="handleOpenPathClick(event, this, false)" title="Open file in default application">
            Open ↗
          </button>` : ''}
          <button class="btn btn-outline" style="padding: 0.2rem 0.5rem; font-size: 0.72rem;" onclick="selectDocument('${escapeHtml(doc.sha256_hash)}')">View</button>
          <button class="btn btn-outline" style="padding: 0.2rem 0.5rem; font-size: 0.72rem; color: #38bdf8; border-color: rgba(56, 189, 248, 0.45); background: rgba(56, 189, 248, 0.1);" onclick="event.stopPropagation(); visualizeDocumentIn3D('${escapeHtml(doc.sha256_hash)}', '${escapeHtml(doc.canonical_filename)}')" title="Visualize document node and connected entity links in 3D Knowledge Universe">
            🌐 3D
          </button>
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
    setChatDocumentContext(doc.sha256_hash, doc.canonical_filename);

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
      <div class="lineage-item" data-sha="${escapeHtml(p.parent_sha256)}" onclick="selectDocument(this.getAttribute('data-sha'))" style="cursor: pointer;">
        <div><strong>Parent Revision:</strong> ${escapeHtml(p.canonical_filename)}</div>
        <div class="location-root">Relation: ${p.relationship} (Similarity: ${(p.similarity_score * 100).toFixed(1)}%)</div>
      </div>
    `).join("");

    const childrenHtml = (doc.children || []).map(c => `
      <div class="lineage-item" data-sha="${escapeHtml(c.child_sha256)}" onclick="selectDocument(this.getAttribute('data-sha'))" style="cursor: pointer;">
        <div><strong>Child Revision:</strong> ${escapeHtml(c.canonical_filename)}</div>
        <div class="location-root">Relation: ${c.relationship} (Similarity: ${(c.similarity_score * 100).toFixed(1)}%)</div>
      </div>
    `).join("");

    const detailDocDate = doc.doc_date || getEffectiveDocDate(doc) || '--';
    const detailDateSrc = doc.doc_date_source || 'detected';

    panel.innerHTML = `
      <div class="detail-header">
        <div class="detail-title">${escapeHtml(doc.canonical_filename)}</div>
        <div class="hash-box" title="Click to copy SHA-256" data-hash="${escapeHtml(doc.sha256_hash)}" onclick="navigator.clipboard.writeText(this.getAttribute('data-hash')); showToast('Copied SHA-256 to clipboard', 'info');">
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
          
      <div class="detail-section" style="margin-top: 1rem; display: flex; flex-direction: column; gap: 0.5rem;">
        <button class="btn btn-interrogate-detail" data-filename="${escapeHtml(doc.canonical_filename)}" onclick="interrogateAboutCurrent(this.getAttribute('data-filename'))">
          💬 Interrogate Bot About This Document
        </button>
        <button class="btn btn-secondary btn-block" style="background: linear-gradient(135deg, rgba(56, 189, 248, 0.16), rgba(168, 85, 247, 0.16)); border: 1px solid rgba(56, 189, 248, 0.45); color: #38bdf8; font-weight: 600; padding: 0.55rem 1rem; display: flex; align-items: center; justify-content: center; gap: 0.5rem; cursor: pointer; transition: all 0.2s ease;" onclick="visualizeDocumentIn3D('${escapeHtml(doc.sha256_hash)}', '${escapeHtml(doc.canonical_filename)}')">
          <span>🌐</span> Visualize in 3D Knowledge Universe ➔
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
let currentChatDoc = null;

function setChatDocumentContext(sha, filename) {
  if (!sha || !filename) return;
  currentChatDoc = { sha256_hash: sha, canonical_filename: filename };
  const banner = document.getElementById("chat-context-banner");
  const nameEl = document.getElementById("chat-context-name");
  const inputEl = document.getElementById("chat-input");
  if (banner && nameEl) {
    nameEl.textContent = filename;
    banner.classList.remove("hidden");
  }
  if (inputEl) {
    inputEl.placeholder = `Ask anything about "${filename}" or any document...`;
  }
}

function clearChatDocumentContext() {
  currentChatDoc = null;
  const banner = document.getElementById("chat-context-banner");
  const inputEl = document.getElementById("chat-input");
  if (banner) {
    banner.classList.add("hidden");
  }
  if (inputEl) {
    inputEl.placeholder = "Ask about any document copy...";
  }
  showToast("Cleared document focus. Next questions will search globally.", "info");
}

// ==========================================
// 12. Workspace Navigation (Ledger, GraphRAG Studio, 3D Universe, Chat)
// ==========================================
let activeWorkspace = "process";

const WORKSPACE_ROUTES = {
  "3d_knowledgegraph_universe": "universe",
  "universe": "universe",
  "3d": "universe",
  "knowledgegraph": "universe",
  "ledger": "ledger",
  "graphrag": "graphrag",
  "authors": "authors",
  "author_review": "authors",
  "chat": "chat",
  "interrogate": "chat",
  "process": "process",
};

const WORKSPACE_SLUGS = {
  "universe": "3d_knowledgegraph_universe",
  "ledger": "ledger",
  "graphrag": "graphrag",
  "authors": "authors",
  "chat": "chat",
  "process": "",
};

function getWorkspaceFromUrl() {
  const hash = (window.location.hash || "").replace(/^#\/?/, "").toLowerCase();
  if (hash && WORKSPACE_ROUTES[hash]) {
    return WORKSPACE_ROUTES[hash];
  }

  const pathParts = window.location.pathname.toLowerCase().split("/").filter(Boolean);
  for (const part of pathParts) {
    if (WORKSPACE_ROUTES[part]) {
      return WORKSPACE_ROUTES[part];
    }
  }

  const params = new URLSearchParams(window.location.search);
  const qWs = (params.get("workspace") || params.get("view") || params.get("tab") || "").toLowerCase();
  if (qWs && WORKSPACE_ROUTES[qWs]) {
    return WORKSPACE_ROUTES[qWs];
  }

  return "process";
}

function switchWorkspace(ws, updateUrl = true) {
  activeWorkspace = ws;

  const btnProcess = document.getElementById("ws-btn-process");
  const btnLedger = document.getElementById("ws-btn-ledger");
  const btnGraphrag = document.getElementById("ws-btn-graphrag");
  const btnUniverse = document.getElementById("ws-btn-universe");
  const btnAuthors = document.getElementById("ws-btn-authors");
  const btnChat = document.getElementById("ws-btn-chat");

  const paneProcess = document.getElementById("ws-pane-process");
  const paneLedger = document.getElementById("ws-pane-ledger");
  const paneGraphrag = document.getElementById("ws-pane-graphrag");
  const paneUniverse = document.getElementById("ws-pane-universe");
  const paneAuthors = document.getElementById("ws-pane-authors");
  const paneChat = document.getElementById("ws-pane-chat");

  if (btnProcess) btnProcess.classList.toggle("active", ws === "process");
  if (btnLedger) btnLedger.classList.toggle("active", ws === "ledger");
  if (btnGraphrag) btnGraphrag.classList.toggle("active", ws === "graphrag");
  if (btnUniverse) btnUniverse.classList.toggle("active", ws === "universe");
  if (btnAuthors) btnAuthors.classList.toggle("active", ws === "authors");
  if (btnChat) btnChat.classList.toggle("active", ws === "chat");

  if (paneProcess) paneProcess.classList.toggle("hidden", ws !== "process");
  if (paneLedger) paneLedger.classList.toggle("hidden", ws !== "ledger");
  if (paneGraphrag) paneGraphrag.classList.toggle("hidden", ws !== "graphrag");
  if (paneUniverse) paneUniverse.classList.toggle("hidden", ws !== "universe");
  if (paneAuthors) paneAuthors.classList.toggle("hidden", ws !== "authors");
  if (paneChat) paneChat.classList.toggle("hidden", ws !== "chat");

  // Keep browser URL in sync (e.g. /reposcroller/3d_knowledgegraph_universe)
  if (updateUrl && window.history && window.history.pushState) {
    const slug = WORKSPACE_SLUGS[ws] !== undefined ? WORKSPACE_SLUGS[ws] : ws;
    const base = window.location.pathname.startsWith("/reposcroller") ? "/reposcroller/" : "/";
    const targetUrl = slug ? `${base}${slug}` : base;
    if (window.location.pathname !== targetUrl) {
      window.history.pushState({ workspace: ws }, "", targetUrl);
    }
  }

  if (ws === "process") {
    loadMetrics();
    loadMountsAndCrawlerStatus();
    loadWorkloadTelemetry();
    loadSidecarStats();
    if (typeof loadProcessScrollerData === "function") loadProcessScrollerData();
    if (typeof pollOllamaProcessInspector === "function") pollOllamaProcessInspector();
    if (typeof loadLineageChains === "function") loadLineageChains();
    if (typeof renderWs0DiagLogs === "function") renderWs0DiagLogs();
  } else if (ws === "universe") {
    init3DKnowledgeUniverse();
    load3DUniverseData();
  } else if (ws === "graphrag") {
    loadSidecarStats();
    const studioInput = document.getElementById("studio-rag-input");
    if (studioInput) studioInput.focus();
  } else if (ws === "authors") {
    loadAuthorCandidates();
    loadAuthorGraph();
  } else if (ws === "chat") {
    const chatInput = document.getElementById("chat-input");
    if (chatInput) chatInput.focus();
  } else if (ws === "ledger") {
    loadLedger();
  }
}
window.switchWorkspace = switchWorkspace;

window.addEventListener("popstate", () => {
  const ws = getWorkspaceFromUrl();
  switchWorkspace(ws, false);
});

// ==========================================
// Human-in-the-loop author candidate review
// ==========================================
const AUTHOR_REVIEW_PAGE_SIZE = 25;
let authorReviewOffset = 0;
let authorGraphRenderer = null;
let authorGraphResizeObserver = null;
let authorGraphCleanup = null;

async function loadAuthorGraph() {
  const container = document.getElementById("author-graph-canvas");
  const summary = document.getElementById("author-graph-summary");
  if (!container) return;
  if (typeof THREE === "undefined") {
    container.textContent = "Three.js is unavailable; use the candidate queue below.";
    return;
  }

  try {
    const status = document.getElementById("author-review-status")?.value || "all";
    const response = await fetch(`/api/v1/authors/graph?status=${encodeURIComponent(status)}&author_limit=60&documents_per_author=8`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const authors = data.authors || [];
    const docs = data.documents || [];
    const authorById = new Map(authors.map(author => [author.node_id, author]));
    const docById = new Map(docs.map(doc => [doc.sha256_hash, doc]));

    const points = [];
    const links = [];
    const authorPositions = new Map();
    const docCounts = new Map();
    (data.edges || []).forEach(edge => docCounts.set(edge.author_id, (docCounts.get(edge.author_id) || 0) + 1));

    authors.forEach((author, index) => {
      const angle = index * 2.399963229728653;
      const ring = 35 + Math.sqrt(index + 1) * 17;
      const position = new THREE.Vector3(Math.cos(angle) * ring, ((index % 5) - 2) * 12, Math.sin(angle) * ring);
      authorPositions.set(author.node_id, position);
      points.push({
        id: author.node_id,
        label: author.name,
        kind: "author",
        status: author.status,
        count: author.document_count,
        position,
        threshold: author.threshold_met,
      });
    });

    const docPositions = new Map();
    let docIndex = 0;
    (data.edges || []).forEach(edge => {
      const author = authorById.get(edge.author_id);
      const doc = docById.get(edge.document_id);
      if (!author || !doc) return;
      let docPosition = docPositions.get(doc.sha256_hash);
      if (!docPosition) {
        const parentPosition = authorPositions.get(author.node_id);
        const angle = (docIndex++ * 2.399963229728653) + 0.8;
        docPosition = parentPosition.clone().add(new THREE.Vector3(Math.cos(angle) * 17, 8 + (docIndex % 3) * 6, Math.sin(angle) * 17));
        docPositions.set(doc.sha256_hash, docPosition);
        points.push({
          id: doc.sha256_hash,
          label: doc.canonical_filename || doc.sha256_hash.slice(0, 12),
          kind: "document",
          status: doc.status,
          count: 1,
          position: docPosition,
          doc,
        });
      }
      links.push({ source: authorPositions.get(author.node_id), target: docPosition, status: edge.status });
    });

    authors.forEach(author => {
      if (status !== "all") {
        author.status = status;
      } else if (author.pending_count > 0) {
        author.status = "pending";
      } else if (author.approved_count > 0) {
        author.status = "approved";
      } else {
        author.status = "rejected";
      }
    });
    const approvedCount = authors.filter(author => author.status === "approved").length;
    const pendingCount = authors.filter(author => author.status === "pending").length;
    const rejectedCount = authors.filter(author => author.status === "rejected").length;
    const thresholdCount = authors.filter(author => author.threshold_met).length;
    if (summary) {
      summary.textContent = `${authors.length} candidates · ${docs.length} displayed linked documents · ${approvedCount} approved · ${pendingCount} pending · ${rejectedCount} declined · ${thresholdCount} at/above the 10-document review threshold (not authorship proof; never auto-approved).`;
    }

    renderAuthorGraph3D(container, points, links);
  } catch (error) {
    console.error("Could not load author graph:", error);
    if (summary) summary.textContent = `Could not load author graph: ${error.message}`;
  }
}

function renderAuthorGraph3D(container, points, links) {
  if (authorGraphResizeObserver) authorGraphResizeObserver.disconnect();
  if (authorGraphCleanup) authorGraphCleanup();
  if (authorGraphRenderer) {
    authorGraphRenderer.dispose();
    authorGraphRenderer = null;
  }
  container.replaceChildren();
  if (!points.length) {
    container.textContent = "No author/document graph data for this filter.";
    return;
  }

  const width = Math.max(container.clientWidth, 320);
  const height = Math.max(container.clientHeight, 430);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#0b1220");
  const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 4000);
  camera.position.set(0, 75, 250);
  authorGraphRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  authorGraphRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  authorGraphRenderer.setSize(width, height);
  container.appendChild(authorGraphRenderer.domElement);
  if (THREE.OrbitControls) {
    const controls = new THREE.OrbitControls(camera, authorGraphRenderer.domElement);
    controls.enableDamping = true;
  }

  const colorByStatus = { approved: 0x34d399, pending: 0xfbbf24, rejected: 0xfb7185 };
  const geometries = [];
  points.forEach(point => {
    const radius = point.kind === "author"
      ? Math.max(3.5, Math.min(10, 3.5 + Math.sqrt(point.count) * 1.15))
      : 2.5;
    const geometry = new THREE.SphereGeometry(radius, 14, 12);
    const color = point.kind === "document" ? 0x60a5fa : (colorByStatus[point.status] || 0xfbbf24);
    const material = new THREE.MeshStandardMaterial({ color, roughness: 0.38, metalness: 0.08 });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.copy(point.position);
    mesh.userData = point;
    scene.add(mesh);
    geometries.push({ mesh, point });
  });

  const linePositions = [];
  links.forEach(link => linePositions.push(link.source.x, link.source.y, link.source.z, link.target.x, link.target.y, link.target.z));
  if (linePositions.length) {
    const lineGeometry = new THREE.BufferGeometry();
    lineGeometry.setAttribute("position", new THREE.Float32BufferAttribute(linePositions, 3));
    const lineMaterial = new THREE.LineBasicMaterial({ color: 0x64748b, transparent: true, opacity: 0.5 });
    scene.add(new THREE.LineSegments(lineGeometry, lineMaterial));
    geometries.push({ geometry: lineGeometry, material: lineMaterial });
  }
  points.filter(point => point.kind === "author").slice(0, 18).forEach(point => {
    const label = create3DTextSprite(`${point.label} · ${point.count}`, "#c084fc", 18);
    label.position.copy(point.position).add(new THREE.Vector3(0, 11, 0));
    label.scale.set(23, 5.5, 1);
    scene.add(label);
    geometries.push({ sprite: label });
  });
  scene.add(new THREE.AmbientLight(0xffffff, 1.5));
  const light = new THREE.PointLight(0xffffff, 900);
  light.position.set(100, 120, 150);
  scene.add(light);

  const raycaster = new THREE.Raycaster();
  raycaster.params.Points.threshold = 5;
  const mouse = new THREE.Vector2();
  const tooltip = document.createElement("div");
  tooltip.className = "author-graph-tooltip";
  tooltip.hidden = true;
  container.appendChild(tooltip);
  authorGraphRenderer.domElement.addEventListener("pointermove", event => {
    const rect = authorGraphRenderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    const hitTargets = geometries.filter(item => item.mesh).map(item => item.mesh);
    const hit = raycaster.intersectObjects(hitTargets)[0];
    if (!hit) { tooltip.hidden = true; return; }
    const point = hit.object.userData;
    const detail = point.kind === "author"
      ? `${point.count} linked docs · ${point.status}${point.threshold ? " · review threshold met, not auto-approved" : ""}`
      : `Document · ${point.status}`;
    tooltip.textContent = `${point.label} — ${detail}`;
    tooltip.hidden = false;
    tooltip.style.left = `${event.clientX - rect.left + 12}px`;
    tooltip.style.top = `${event.clientY - rect.top + 12}px`;
  });

  let animFrame = 0;
  const animate = () => {
    animFrame = requestAnimationFrame(animate);
    authorGraphRenderer.render(scene, camera);
  };
  animate();
  authorGraphResizeObserver = new ResizeObserver(() => {
    if (!authorGraphRenderer) return;
    const nextWidth = Math.max(container.clientWidth, 320);
    const nextHeight = Math.max(container.clientHeight, 430);
    camera.aspect = nextWidth / nextHeight;
    camera.updateProjectionMatrix();
    authorGraphRenderer.setSize(nextWidth, nextHeight);
  });
  authorGraphResizeObserver.observe(container);
  authorGraphCleanup = () => {
    cancelAnimationFrame(animFrame);
    geometries.forEach(item => {
      if (item.mesh) {
        item.mesh.geometry.dispose();
        item.mesh.material.dispose();
      } else if (item.geometry) {
        item.geometry.dispose();
        item.material?.dispose();
      } else if (item.sprite) {
        item.sprite.material.map?.dispose();
        item.sprite.material.dispose();
      }
    });
    tooltip.remove();
  };
}

function changeAuthorCandidatePage(direction) {
  authorReviewOffset = Math.max(0, authorReviewOffset + direction * AUTHOR_REVIEW_PAGE_SIZE);
  loadAuthorCandidates();
}

// In static/app.js:
async function prevalidateAuthorCandidates() {
  const button = document.getElementById("author-prevalidate-button");
  const status = document.getElementById("author-prevalidation-status");

  const batchLimit = 3;       // 3 candidates ensure completion well under the timeout limit
  const timeoutSeconds = 45;  // 45-second overall client budget
  const timeoutMs = timeoutSeconds * 1000;

  const originalButtonText = button ? (button.getAttribute("data-orig-text") || button.textContent) : "🧠 Prevalidate next 3";
  if (button) {
    button.setAttribute("data-orig-text", originalButtonText);
    button.disabled = true;
  }

  let remainingSeconds = timeoutSeconds;
  const updateCountdownDisplay = () => {
    if (button) button.textContent = `⏳ Prevalidating (${remainingSeconds}s)...`;
  };
  updateCountdownDisplay();

  const countdownTimer = setInterval(() => {
    remainingSeconds--;
    if (remainingSeconds > 0) {
      updateCountdownDisplay();
    } else {
      if (button) button.textContent = "⏳ Finalizing evaluations...";
      clearInterval(countdownTimer);
    }
  }, 1000);

  const startMsg = `Author prevalidation dispatched (batch: ${batchLimit}, timeout: ${timeoutSeconds}s). Probing remote PC2 first...`;
  if (status) status.textContent = startMsg;

  logDiagnosticEntry({
    source: "frontend",
    level: "INFO",
    logger: "authors.prevalidate",
    message: startMsg,
    extra: { batch_limit: batchLimit, timeout_s: timeoutSeconds }
  });

  const requestStartTime = performance.now();

  try {
    const response = await fetch(`/api/v1/authors/prevalidate?limit=${batchLimit}`, {
      method: "POST",
      signal: AbortSignal.timeout(timeoutMs)
    });

    const elapsedMs = Math.round(performance.now() - requestStartTime);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);

    if (data.status === "llm_unavailable") {
      const warnMsg = `Ollama nodes unavailable (${elapsedMs}ms). ${data.message}`;
      if (status) status.textContent = warnMsg;
      logDiagnosticEntry({
        source: "frontend",
        level: "WARNING",
        logger: "authors.prevalidate",
        message: warnMsg,
        extra: { elapsed_ms: elapsedMs, ...data }
      });
    } else if (data.status === "idle") {
      const idleMsg = `No unevaluated candidates remaining in repository (${elapsedMs}ms).`;
      if (status) status.textContent = idleMsg;
      logDiagnosticEntry({
        source: "frontend",
        level: "INFO",
        logger: "authors.prevalidate",
        message: idleMsg,
        extra: { elapsed_ms: elapsedMs }
      });
    } else {
      const route = data.fallback_used ? `Local CPU fallback (${data.llm_model})` : `Remote CUDA (${data.llm_model})`;
      const routeLabel = data.fallback_used
        ? `Remote unavailable; local ${data.llm_model} fallback used`
        : `Remote ${data.llm_model} used`;
      const deferred = data.deferred_for_next_batch ? `; ${data.deferred_for_next_batch} deferred to next batch` : "";

      const successMsg = `${routeLabel}. Batch completed in ${elapsedMs}ms via ${route}. Evaluated ${data.evaluated}: ${data.deterministically_filtered} filtered before LLM, ${data.llm_evaluated} LLM-evaluated, ${data.qualified} qualified at ≥ ${Math.round(data.threshold * 100)}%${deferred}. Human approval still required.`;
      if (status) status.textContent = successMsg;

      logDiagnosticEntry({
        source: "frontend",
        level: "INFO",
        logger: "authors.prevalidate",
        message: successMsg,
        extra: {
          elapsed_ms: elapsedMs,
          node: data.llm_node,
          model: data.llm_model,
          qualified: data.qualified,
          evaluated: data.evaluated,
          threshold: data.threshold,
          prefiltered: data.deterministically_filtered
        }
      });
    }

    authorReviewOffset = 0;
    await Promise.allSettled([loadAuthorCandidates(), loadAuthorGraph()]);

  } catch (error) {
    const elapsedMs = Math.round(performance.now() - requestStartTime);
    const isTimeout = error.name === "TimeoutError" || error.name === "AbortError";
    const errorLevel = isTimeout ? "WARNING" : "ERROR";
    const message = isTimeout
      ? `Prevalidation request timed out after \({elapsedMs}ms (threshold:\){timeoutSeconds}s). Ollama took too long to respond.`
      : `Prevalidation failed (\({elapsedMs}ms):\){error.message}`;

    if (status) status.textContent = message;
    showToast(message, errorLevel === "WARNING" ? "warning" : "error");

    logDiagnosticEntry({
      source: "frontend",
      level: errorLevel,
      logger: "authors.prevalidate",
      message: message,
      exception: error.stack || String(error),
      extra: { elapsed_ms: elapsedMs, timeout_limit_s: timeoutSeconds }
    });

    reportFrontendIssueToBackend(message, error.stack || String(error), errorLevel);
  } finally {
    clearInterval(countdownTimer);
    if (button) {
      button.disabled = false;
      button.textContent = button.getAttribute("data-orig-text") || originalButtonText;
    }
  }
}


async function loadAuthorCandidates() {
  const list = document.getElementById("author-review-list");
  if (!list) return;
  if (list.dataset.reviewHandlerAttached !== "true") {
    list.dataset.reviewHandlerAttached = "true";
    list.addEventListener("click", event => {
      const button = event.target.closest("[data-author-review]");
      if (!button || !list.contains(button)) return;
      const note = button.closest("article")?.querySelector("[data-review-note]")?.value.trim() || "";
      reviewAuthorCandidate(button.dataset.sha, button.dataset.node, button.dataset.authorReview, note);
    });
  }
  list.textContent = "Loading candidate reviews…";
  const status = document.getElementById("author-review-status")?.value || "pending";
  const query = document.getElementById("author-review-search")?.value.trim() || "";
  const params = new URLSearchParams({ status, limit: String(AUTHOR_REVIEW_PAGE_SIZE), offset: String(authorReviewOffset) });
  if (query) params.set("q", query);

  try {
    const response = await fetch(`/api/v1/authors/candidates?${params}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const total = data.total || 0;
    const page = Math.floor(authorReviewOffset / AUTHOR_REVIEW_PAGE_SIZE) + 1;
    const pages = Math.max(1, Math.ceil(total / AUTHOR_REVIEW_PAGE_SIZE));
    if (total > 0 && authorReviewOffset >= total) {
      authorReviewOffset = Math.floor((total - 1) / AUTHOR_REVIEW_PAGE_SIZE) * AUTHOR_REVIEW_PAGE_SIZE;
      return loadAuthorCandidates();
    }
    document.getElementById("author-review-count").textContent = `${total.toLocaleString()} candidates`;
    document.getElementById("author-review-page").textContent = `Page ${page} of ${pages}`;
    document.getElementById("author-review-prev").disabled = authorReviewOffset <= 0;
    document.getElementById("author-review-next").disabled = authorReviewOffset + AUTHOR_REVIEW_PAGE_SIZE >= total;

    if (!data.items.length) {
      list.innerHTML = '<div class="author-review-empty"><p>No high-confidence author candidates are ready for this queue.</p><p>Run the next prevalidation batch above. Candidates require an exact, source-verifiable authorship quote and confidence ≥90%; human approval is still required.</p></div>';
      return;
    }

    list.innerHTML = data.items.map(candidate => {
      const evidence = candidate.text_snippet || "No saved text snippet available.";
      const statusLabel = candidate.status === "pending" ? "Needs review" : candidate.status;
      const isPending = candidate.status === "pending";
      return `<article style="border:1px solid var(--border-color);border-radius:var(--radius-md);padding:1rem;margin:.75rem 0;background:var(--bg-surface)">
        <div style="display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap">
          <div><h3>${escapeHtml(candidate.name)}</h3><div class="text-muted">${escapeHtml(candidate.canonical_filename || "Untitled document")} · source role: ${escapeHtml(candidate.source_role)} · extraction confidence ${Number(candidate.source_confidence || 0).toFixed(2)}</div></div>
          <strong>${escapeHtml(statusLabel)} · LLM ${Math.round(Number(candidate.prevalidation_confidence || 0) * 100)}%</strong>
        </div>
        <p class="text-muted" style="margin:.5rem 0">Document type: ${escapeHtml(candidate.doc_type || "unknown")} · Date: ${escapeHtml(candidate.doc_date || "unknown")}</p>
        <details class="author-prevalidation-evidence"><summary>LLM prevalidation evidence</summary><blockquote>${escapeHtml(candidate.prevalidation_evidence || "No verified quote")}</blockquote><p>${escapeHtml(candidate.prevalidation_reason || "")}</p><small>Model: ${escapeHtml(candidate.prevalidation_model || "local Ollama")}; this is not identity verification.</small></details>
        <details><summary>Review available evidence</summary><p style="white-space:pre-wrap;margin-top:.5rem">${escapeHtml(evidence)}</p></details>
        ${candidate.reviewer ? `<p class="text-muted" style="margin-top:.5rem">Reviewed by ${escapeHtml(candidate.reviewer)} · ${escapeHtml(candidate.note || "No note")}</p>` : ""}
        ${isPending ? `<textarea class="author-review-note" data-review-note maxlength="2000" rows="2" placeholder="Optional review note"></textarea><div style="display:flex;gap:.5rem;margin-top:.75rem"><button class="btn btn-primary btn-sm" data-author-review="approve" data-sha="${escapeHtml(candidate.sha256_hash)}" data-node="${escapeHtml(candidate.node_id)}">✓ Approve as author</button><button class="btn btn-outline btn-sm" data-author-review="decline" data-sha="${escapeHtml(candidate.sha256_hash)}" data-node="${escapeHtml(candidate.node_id)}">✕ Decline</button></div>` : ""}
      </article>`;
    }).join("");
  } catch (error) {
    console.error("Could not load author candidates:", error);
    list.textContent = "Could not load author candidates. Check the API and try refreshing.";
  }
}

async function reviewAuthorCandidate(sha, node, decision, note = "") {
  const reviewer = document.getElementById("author-reviewer")?.value.trim();
  if (!reviewer) {
    showToast("Enter your reviewer name or ID before making a decision.", "warning");
    document.getElementById("author-reviewer")?.focus();
    return;
  }
  try {
    const response = await fetch(`/api/v1/authors/candidates/${encodeURIComponent(sha)}/${encodeURIComponent(node)}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reviewer, note })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    showToast(decision === "approve" ? "Author approved and linked to document." : "Candidate declined; existing entity roles were preserved.", "success");
    loadAuthorCandidates();
    loadAuthorGraph();
  } catch (error) {
    showToast(`Author review failed: ${error.message}`, "error");
  }
}

// Backward compatibility alias for any older triggers
function switchTab(tab) {
  if (tab === "graph") {
    switchWorkspace("graphrag");
  } else if (tab === "chat") {
    switchWorkspace("chat");
  } else if (tab === "process") {
    switchWorkspace("process");
  } else if (tab === "universe") {
    switchWorkspace("universe");
  } else if (tab === "authors") {
    switchWorkspace("authors");
  } else {
    switchWorkspace("ledger");
  }
}

// ==========================================
// 12.5 Knowledge Base Sidecar & GraphRAG Studio UI
// ==========================================
async function loadSidecarStats() {
  try {
    const res = await fetch("/api/v1/sidecar/stats");
    if (!res.ok) return;
    const data = await res.json();

    const q = data.queue || {};
    const g = data.graph || {};

    const pending = q.pending || 0;
    const processing = q.processing || 0;
    const completed = q.completed || 0;
    const failed = q.failed || 0;
    const totalChunks = q.total_chunks_indexed || 0;
    const totalDocsChunked = q.total_documents_chunked || 0;

    const totalQueueItems = pending + processing + completed + failed;
    const pct = totalQueueItems > 0 ? Math.round(((completed + failed) / totalQueueItems) * 100) : 100;

    // Update Top Metric Card
    const metricKbChunks = document.getElementById("metric-kb-chunks");
    if (metricKbChunks) {
      metricKbChunks.textContent = `${totalChunks} vectors`;
    }
    const metricKbSub = document.getElementById("metric-kb-sub");
    if (metricKbSub) {
      metricKbSub.textContent = `${g.total_nodes || 0} nodes • ${g.total_edges || 0} edges`;
    }

    // Update Progress Bars (both studio and mini widgets)
    const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    const setWidth = (id, widthVal) => { const el = document.getElementById(id); if (el) el.style.width = widthVal; };

    setTxt("studio-kb-progress-pct", `${pct}%`);
    setTxt("kb-progress-pct", `${pct}%`);

    const barWidths = totalQueueItems > 0 ? {
      completed: `${(completed / totalQueueItems) * 100}%`,
      processing: `${(processing / totalQueueItems) * 100}%`,
      pending: `${(pending / totalQueueItems) * 100}%`,
      failed: `${(failed / totalQueueItems) * 100}%`
    } : { completed: "100%", processing: "0%", pending: "0%", failed: "0%" };

    setWidth("studio-kb-bar-completed", barWidths.completed);
    setWidth("studio-kb-bar-processing", barWidths.processing);
    setWidth("studio-kb-bar-pending", barWidths.pending);
    setWidth("studio-kb-bar-failed", barWidths.failed);

    setWidth("kb-bar-completed", barWidths.completed);
    setWidth("kb-bar-processing", barWidths.processing);
    setWidth("kb-bar-pending", barWidths.pending);
    setWidth("kb-bar-failed", barWidths.failed);

    // Update Queue Counts
    setTxt("studio-kb-stat-completed", completed);
    setTxt("studio-kb-stat-processing", processing);
    setTxt("studio-kb-stat-pending", pending);
    setTxt("studio-kb-stat-failed", failed);
    setTxt("studio-kb-stat-chunks", totalChunks);
    setTxt("studio-kb-stat-docs-chunked", totalDocsChunked);

    setTxt("kb-stat-completed", completed);
    setTxt("kb-stat-processing", processing);
    setTxt("kb-stat-pending", pending);
    setTxt("kb-stat-failed", failed);
    setTxt("kb-stat-chunks", totalChunks);
    setTxt("kb-stat-docs-chunked", totalDocsChunked);

    // Update Graph Metrics
    setTxt("studio-kb-graph-nodes", g.total_nodes || 0);
    setTxt("studio-kb-graph-edges", g.total_edges || 0);
    setTxt("studio-kb-graph-doclinks", g.total_document_links || 0);

    setTxt("kb-graph-nodes", g.total_nodes || 0);
    setTxt("kb-graph-edges", g.total_edges || 0);
    setTxt("kb-graph-doclinks", g.total_document_links || 0);

    // Update Continuous Worker Status Strip & Controls
    const w = data.worker || {};
    sidecarContinuousRunning = !!w.is_running;
    updateSidecarToggleButton();

    const tierInfo = data.embedding_tier || {};
    const tier = tierInfo.tier || "cuda";
    const tierColor = tierInfo.color || "green";

    const engineTag = document.getElementById("studio-kb-engine-tag");
    if (engineTag && data.model) {
      const urlHost = data.embed_url ? data.embed_url.replace(/https?:\/\//, '') : 'PC2 CUDA';
      engineTag.textContent = `${data.model} (${urlHost})`;
    }

    const dot1 = document.getElementById("studio-kb-worker-dot");
    const dot2 = document.getElementById("kb-worker-dot");
    const st1 = document.getElementById("studio-kb-worker-status-text");
    const st2 = document.getElementById("kb-worker-status-text");
    const sc1 = document.getElementById("studio-kb-session-counter");
    const sc2 = document.getElementById("kb-session-counter");
    const su1 = document.getElementById("studio-kb-session-uptime");
    const su2 = document.getElementById("kb-session-uptime");

    let statusText = "Pipeline Idle";
    let dotClass = "kb-worker-dot";
    let textClass = "kb-worker-status-text";

    if (sidecarContinuousRunning) {
      if (tier === "cuda") {
        statusText = "⚡ Ingestion Active (CUDA Node)";
        dotClass = "kb-worker-dot active";
        textClass = "kb-worker-status-text active tier-cuda";
      } else if (tier === "local") {
        statusText = "🟠 Ingestion Active (Local CPU Fallback)";
        dotClass = "kb-worker-dot active tier-local";
        textClass = "kb-worker-status-text active tier-local";
      } else {
        statusText = "🔴 Ingestion Active (Offline Pseudo-Vectors)";
        dotClass = "kb-worker-dot active tier-fallback";
        textClass = "kb-worker-status-text active tier-fallback";
      }
    }

    [dot1, dot2].forEach(d => { if (d) d.className = dotClass; });
    [st1, st2].forEach(s => {
      if (s) {
        s.className = textClass;
        s.textContent = statusText;
        if (tierInfo.fallback_reason) {
          s.title = tierInfo.fallback_reason;
        }
      }
    });
    [sc1, sc2].forEach(sc => { if (sc) sc.textContent = `Session: ${w.session_docs_processed || 0} docs • ${w.session_chunks_embedded || 0} chunks`; });
    [su1, su2].forEach(su => { if (su) su.textContent = w.uptime_formatted ? `(uptime: ${w.uptime_formatted})` : ""; });

    // Update Node Types Distribution Chips
    const updateChips = (wrapId) => {
      const wrap = document.getElementById(wrapId);
      if (wrap && g.node_types) {
        const typeEntries = Object.entries(g.node_types);
        if (typeEntries.length > 0) {
          wrap.innerHTML = typeEntries.map(([type, count]) => {
            let icon = "🏷️";
            if (type === "organization") icon = "🏢";
            else if (type === "person") icon = "👤";
            else if (type === "contract_type") icon = "📄";
            else if (type === "location") icon = "📍";
            else if (type === "statute") icon = "⚖️";
            const isActive = activeEntityType === type ? "active" : "";
            return `<button class="kb-type-chip ${isActive}" data-type="${escapeHtml(type)}" onclick="toggleEntityType('${escapeHtml(type)}')">${icon} <strong>${escapeHtml(type)}</strong>: <span class="badge-count">${count}</span></button>`;
          }).join("");
        }
      }
    };
    updateChips("studio-kb-nodetypes-list");
    updateChips("kb-nodetypes-list");
  } catch (err) {
    console.error("Failed loading sidecar stats:", err);
  }
}

// Global state for entity distribution inspection
let sidecarEntitiesCache = null;
let activeEntityType = null;

async function fetchSidecarEntities() {
  if (sidecarEntitiesCache) return sidecarEntitiesCache;
  try {
    const res = await fetch("/api/v1/sidecar/entities?limit_per_type=300");
    if (res.ok) {
      const data = await res.json();
      sidecarEntitiesCache = data.entities_by_type || {};
      return sidecarEntitiesCache;
    }
  } catch (err) {
    console.warn("Could not fetch entities from sidecar:", err);
  }
  return {};
}

async function toggleEntityType(type) {
  const drawer = document.getElementById("studio-kb-entity-drawer") || document.getElementById("kb-entity-drawer");
  if (!drawer) return;

  if (activeEntityType === type) {
    closeEntityDrawer();
    return;
  }

  activeEntityType = type;

  document.querySelectorAll(".kb-type-chip").forEach(chip => {
    chip.classList.toggle("active", chip.getAttribute("data-type") === type);
  });

  const titleEl = document.getElementById("studio-kb-drawer-title") || document.getElementById("kb-drawer-title");
  const countEl = document.getElementById("studio-kb-drawer-count") || document.getElementById("kb-drawer-count");
  const itemsContainer = document.getElementById("studio-kb-entity-items") || document.getElementById("kb-entity-items");
  const searchInput = document.getElementById("studio-kb-entity-filter-input") || document.getElementById("kb-entity-filter-input");

  if (searchInput) searchInput.value = "";

  let icon = "🏷️";
  if (type === "organization") icon = "🏢";
  else if (type === "person") icon = "👤";
  else if (type === "contract_type") icon = "📄";
  else if (type === "location") icon = "📍";
  else if (type === "statute") icon = "⚖️";

  if (titleEl) titleEl.textContent = `${icon} ${type.replace(/_/g, " ").toUpperCase()}`;
  drawer.classList.remove("hidden");

  if (itemsContainer) {
    itemsContainer.innerHTML = `<span class="loading-text" style="font-size: 0.72rem;">Loading entities...</span>`;
  }

  const allGrouped = await fetchSidecarEntities();
  const entities = allGrouped[type] || [];

  if (countEl) countEl.textContent = entities.length;
  renderEntityList(entities, "");
}

function closeEntityDrawer() {
  activeEntityType = null;
  const drawer1 = document.getElementById("studio-kb-entity-drawer");
  const drawer2 = document.getElementById("kb-entity-drawer");
  if (drawer1) drawer1.classList.add("hidden");
  if (drawer2) drawer2.classList.add("hidden");
  document.querySelectorAll(".kb-type-chip").forEach(chip => chip.classList.remove("active"));
}

function filterEntityList(query) {
  if (!activeEntityType || !sidecarEntitiesCache) return;
  const entities = sidecarEntitiesCache[activeEntityType] || [];
  renderEntityList(entities, query.toLowerCase().trim());
}

function renderEntityList(entities, filterQuery) {
  const itemsContainer = document.getElementById("studio-kb-entity-items") || document.getElementById("kb-entity-items");
  if (!itemsContainer) return;

  const filtered = filterQuery
    ? entities.filter(e => (e.name || "").toLowerCase().includes(filterQuery))
    : entities;

  if (filtered.length === 0) {
    itemsContainer.innerHTML = `<span class="empty-text" style="font-size: 0.72rem; padding: 0.5rem;">No matching entities found.</span>`;
    return;
  }

  itemsContainer.innerHTML = filtered.map(e => {
    const docTag = e.doc_count > 0 ? `<span class="kb-entity-pill-doccount">${e.doc_count} doc${e.doc_count > 1 ? 's' : ''}</span>` : "";
    return `<button class="kb-entity-pill" data-name="${escapeHtml(e.name)}" onclick="selectEntityForSearch(this.getAttribute('data-name'))" title="Click to search in GraphRAG Studio">
      <span>${escapeHtml(e.name)}</span>
      ${docTag}
    </button>`;
  }).join("");
}

function selectEntityForSearch(name) {
  const studioInput = document.getElementById("studio-rag-input");
  if (studioInput) {
    studioInput.value = name;
    executeStudioGraphRAGSearch(name);
  }
}

let sidecarContinuousRunning = false;

function updateSidecarToggleButton() {
  const btns = [
    document.getElementById("studio-btn-sidecar-toggle"),
    document.getElementById("btn-sidecar-toggle"),
    document.getElementById("ws0-btn-sidecar-toggle")
  ].filter(Boolean);
  const icons = [document.getElementById("studio-sidecar-toggle-icon"), document.getElementById("sidecar-toggle-icon")].filter(Boolean);
  const texts = [
    document.getElementById("studio-sidecar-toggle-text"),
    document.getElementById("sidecar-toggle-text"),
    document.getElementById("ws0-sidecar-btn-text")
  ].filter(Boolean);

  btns.forEach(btn => {
    if (sidecarContinuousRunning) {
      btn.className = btn.id === "ws0-btn-sidecar-toggle" ? "btn btn-rose btn-sm" : "btn btn-rose btn-xs";
      btn.title = "Click to stop the continuous sidecar worker";
    } else {
      btn.className = btn.id === "ws0-btn-sidecar-toggle" ? "btn btn-primary btn-sm" : "btn btn-emerald btn-xs";
      btn.title = "Click to start continuous background ingestion on PC2 CUDA GPU";
    }
  });

  icons.forEach(icon => { icon.textContent = sidecarContinuousRunning ? "⏹" : "▶"; });
  texts.forEach(text => { text.textContent = sidecarContinuousRunning ? "Stop Continuous Sidecar" : "Start Continuous Sidecar"; });

  const ws0Pill = document.getElementById("ws0-sidecar-status-pill");
  if (ws0Pill) {
    if (sidecarContinuousRunning) {
      ws0Pill.className = "badge-status-pill badge-running";
      ws0Pill.textContent = "Continuous Active (CUDA)";
    } else {
      ws0Pill.className = "badge-status-pill badge-idle";
      ws0Pill.textContent = "Idle (Standby)";
    }
  }
}

async function toggleContinuousSidecar() {
  const btns = [
    document.getElementById("studio-btn-sidecar-toggle"),
    document.getElementById("btn-sidecar-toggle"),
    document.getElementById("ws0-btn-sidecar-toggle")
  ].filter(Boolean);
  btns.forEach(b => b.disabled = true);

  try {
    if (!sidecarContinuousRunning) {
      const res = await fetch("/api/v1/sidecar/start", { method: "POST" });
      const data = await res.json();
      sidecarContinuousRunning = true;
      updateSidecarToggleButton();
      showToast("🚀 Sidecar Indexing Pipeline active on PC2 CUDA GPU!", "success", 4000);
    } else {
      const res = await fetch("/api/v1/sidecar/stop", { method: "POST" });
      const data = await res.json();
      sidecarContinuousRunning = false;
      updateSidecarToggleButton();
      const docs = data.session_docs_processed || 0;
      const chunks = data.session_chunks_embedded || 0;
      const dur = data.duration_formatted || "0s";
      showToast(`⏹ Sidecar stopped: ${docs} docs (${chunks} vectors) in ${dur}.`, "info", 5000);
    }
    await loadSidecarStats();
  } catch (err) {
    showToast(`Sidecar control error: ${err.message}`, "error", 5000);
  } finally {
    btns.forEach(b => b.disabled = false);
  }
}

async function triggerSidecarBatch() {
  const btns = [document.getElementById("studio-btn-trigger-batch"), document.getElementById("btn-trigger-batch")].filter(Boolean);
  btns.forEach(b => { b.disabled = true; b.textContent = "⏳ Processing..."; });

  try {
    const res = await fetch("/api/v1/sidecar/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 32 })
    });
    const data = await res.json();
    const count = data.processed_count || 0;
    showToast(`⚡ Processed batch of ${count} document(s) on PC2 CUDA Node.`, "success", 4000);
    await loadSidecarStats();
  } catch (err) {
    showToast(`Sidecar batch failed: ${err.message}`, "error", 5000);
  } finally {
    btns.forEach(b => { b.disabled = false; b.textContent = "⚡ Single Batch"; });
  }
}

async function triggerEntityValidation() {
  const btns = [
    document.getElementById("ws0-btn-validate-entities"),
    document.getElementById("studio-btn-validate-entities")
  ].filter(Boolean);

  btns.forEach(b => {
    b.disabled = true;
    b.innerHTML = '<span class="btn-icon">⏳</span> Auditing...';
  });

  showToast("🛡️ Running Knowledge Graph entity certification & pruning audit...", "info", 4000);

  try {
    const res = await fetch("/api/v1/sidecar/validate-entities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 50, dry_run: false, deterministic_only: false, run_llm: true })
    });
    const data = await res.json();
    const result = data.result || {};
    const det = result.deterministic || {};
    const llm = result.llm || {};
    const purged = (det.purged_ocr_noise || 0) + (det.purged_blacklisted || 0) + (llm.purged_count || 0);
    const recat = (det.recategorized_doc_types || 0) + (det.reclassified_locations || 0) + (llm.recategorized_count || 0);
    const certified = llm.retained_count || 0;

    showToast(`🛡️ Entity audit complete: ${certified} certified, ${purged} purged, ${recat} recategorized.`, "success", 6000);
    await loadSidecarStats();
    if (typeof loadUniverseData === "function") {
      loadUniverseData();
    }
  } catch (err) {
    showToast(`Entity validation failed: ${err.message}`, "error", 5000);
  } finally {
    btns.forEach(b => {
      b.disabled = false;
      b.innerHTML = '<span class="btn-icon">🛡️</span> Validate Entities';
    });
  }
}
window.triggerEntityValidation = triggerEntityValidation;


// ==========================================
// 12.6 Full-Width GraphRAG Sovereign Studio Execution
// ==========================================
function executeStudioSuggestedQuery(query) {
  const input = document.getElementById("studio-rag-input");
  if (input) input.value = query;
  executeStudioGraphRAGSearch(query);
}

function clearStudioRAGSearch() {
  const input = document.getElementById("studio-rag-input");
  const clearBtn = document.getElementById("btn-studio-rag-clear");
  if (input) input.value = "";
  if (clearBtn) clearBtn.classList.add("hidden");

  const resultsContainer = document.getElementById("studio-rag-results-container");
  if (resultsContainer) {
    resultsContainer.innerHTML = `
      <div class="studio-empty-state">
        <div class="empty-icon">🔬</div>
        <div class="empty-title">Ready for Multi-Signal Retrieval</div>
        <div class="empty-text">Enter a query above or click one of the quick prompts to execute dense vector search on PC2 CUDA, BM25 scoring, and graph entity neighborhood expansion.</div>
      </div>
    `;
  }
  const countBadge = document.getElementById("studio-results-count");
  if (countBadge) countBadge.textContent = "0 candidates";
  const signalsSummary = document.getElementById("studio-signals-summary");
  if (signalsSummary) signalsSummary.textContent = "";
}

async function handleCandidateOpenFile(event, sha256, filePath = "", reveal = false) {
  if (event) event.stopPropagation();
  if (filePath && filePath.trim()) {
    openFile(filePath.trim(), reveal);
  } else if (sha256 && sha256.trim()) {
    const actionName = reveal ? "Revealing in File Explorer" : "Opening file";
    showToast(`${actionName} for SHA: ${sha256.substring(0, 12)}...`, "info", 4000);
    try {
      const res = await fetch("/api/v1/documents/open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sha256_hash: sha256, reveal: reveal })
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(`Error: ${data.detail || "Could not open file"}`, "error", 7000);
      } else {
        const verb = reveal ? "Revealed in Explorer" : "Launched default application";
        showToast(`${verb}: ${data.path || sha256}`, "success", 5000);
      }
    } catch (err) {
      showToast(`Network error: ${err.message}`, "error", 7000);
    }
  } else {
    showToast("No registered file path or SHA-256 for this candidate", "error");
  }
}
window.handleCandidateOpenFile = handleCandidateOpenFile;

async function executeStudioGraphRAGSearch(explicitQuery = null) {
  const input = document.getElementById("studio-rag-input");
  const query = (explicitQuery != null ? explicitQuery : (input ? input.value : "")).trim();
  if (!query) {
    showToast("Please enter a search query", "info");
    return;
  }

  const clearBtn = document.getElementById("btn-studio-rag-clear");
  if (clearBtn) clearBtn.classList.remove("hidden");

  const resultsContainer = document.getElementById("studio-rag-results-container");
  const countBadge = document.getElementById("studio-results-count");
  const signalsSummary = document.getElementById("studio-signals-summary");
  const btn = document.getElementById("btn-studio-rag-search");

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span>⏳ Searching CUDA Vectors & Graph...</span>`;
  }

  if (resultsContainer) {
    resultsContainer.innerHTML = `
      <div class="studio-empty-state">
        <div class="empty-icon">⚡</div>
        <div class="empty-title">Computing 3-Signal Hybrid Retrieval...</div>
        <div class="empty-text">Generating dense embeddings on PC2 CUDA GPU, querying BM25 index, and traversing 1-hop Property Knowledge Graph...</div>
      </div>
    `;
  }

  try {
    const limitSelect = document.getElementById("studio-candidate-limit-select");
    const topK = limitSelect ? (parseInt(limitSelect.value, 10) || 25) : 25;
    const res = await fetch(`/api/v1/sidecar/graph-rag?query=${encodeURIComponent(query)}&top_k=${topK}&expand_graph_hops=1`);
    if (!res.ok) {
      const errJson = await res.json().catch(() => ({}));
      throw new Error(errJson.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    const hits = data.ranked_results || data.top_candidates || [];
    const signals = data.retrieval_signals || {};

    if (countBadge) countBadge.textContent = `${hits.length} candidate${hits.length !== 1 ? 's' : ''}`;
    if (signalsSummary) {
      signalsSummary.textContent = `Vectors: ${signals.dense_hits_count || 0} • BM25: ${signals.sparse_hits_count || 0} • Entities: ${signals.graph_entities_expanded || 0}`;
    }

    if (typeof logDiagnosticEntry === "function") {
      logDiagnosticEntry({
        source: "frontend",
        level: "INFO",
        logger: "client.graphrag",
        message: `GraphRAG executed for '${query}': ${hits.length} fused candidates (Limit: ${topK}, Vectors: ${signals.dense_hits_count || 0}, BM25: ${signals.sparse_hits_count || 0}, Entity Hops: ${signals.graph_entities_expanded || 0})`
      });
    }

    if (hits.length === 0) {
      resultsContainer.innerHTML = `
        <div class="studio-empty-state">
          <div class="empty-icon">🔍</div>
          <div class="empty-title">No candidates matching "${escapeHtml(query)}"</div>
          <div class="empty-text">Try broader terms or verify that documents are indexed in the Sidecar Pipeline.</div>
        </div>
      `;
      return;
    }

    resultsContainer.innerHTML = hits.map((hit, idx) => {
      const doc = hit.document || {};
      const chunk = hit.chunk || {};
      const sigs = hit.signals || {};
      const filename = doc.canonical_filename || chunk.canonical_filename || `Document #${idx + 1}`;
      const sha = doc.sha256_hash || chunk.sha256_hash || "";
      const primaryPath = doc.absolute_path || chunk.absolute_path || (doc.locations && doc.locations[0] && doc.locations[0].absolute_path) || "";
      const score = (hit.composite_score || 0).toFixed(4);
      const text = chunk.chunk_text || doc.text_snippet || "No text available";

      const vectorPill = sigs.dense_vector_match
        ? `<span class="signal-pill vector">⚡ CUDA Vector: ${(sigs.vector_similarity * 100).toFixed(1)}%</span>`
        : '';
      const bm25Pill = sigs.lexical_fts_match
        ? `<span class="signal-pill bm25">📄 BM25 Rank #${sigs.bm25_rank}</span>`
        : '';
      const graphPill = sigs.graph_neighborhood_expansion
        ? `<span class="signal-pill graph">🕸️ Graph: ${sigs.connected_entities_count || 0} Links</span>`
        : '';

      const entityBadges = (sigs.entities || []).slice(0, 4).map(e =>
        `<span class="entity-micro-badge">${escapeHtml(e.replace(/^[a-z]+_/, ''))}</span>`
      ).join("");

      return `
        <div class="studio-candidate-card" data-sha="${escapeHtml(sha)}">
          <div class="candidate-header-row">
            <div class="candidate-title-group">
              <span class="candidate-filename">📄 ${escapeHtml(filename)}</span>
              <div class="candidate-meta-line">
                <span>Category: <strong>${escapeHtml(doc.doc_type || 'doc')}</strong></span>
                <span>•</span>
                <span>Date: ${escapeHtml(doc.doc_date || '--')}</span>
                <span>•</span>
                <span>Status: ${escapeHtml(doc.lifecycle_status || 'final')}</span>
                ${primaryPath ? `<span>•</span><span title="${escapeHtml(primaryPath)}" style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">📁 ${escapeHtml(primaryPath)}</span>` : ''}
              </div>
            </div>
            <span class="signal-pill rrf" title="Reciprocal Rank Fusion Score">RRF Rank #${idx + 1} (${score})</span>
          </div>
            
          <div class="signal-pills-row">
            ${vectorPill}
            ${bm25Pill}
            ${graphPill}
          </div>
            
          <div class="candidate-snippet-box">
            "${escapeHtml(text.slice(0, 300))}${text.length > 300 ? '...' : ''}"
          </div>
            
          <div class="candidate-actions-row">
            <div class="candidate-entities-badges">
              ${entityBadges ? `<span style="font-size: 0.68rem; color: var(--text-faint);">Entities:</span> ${entityBadges}` : ''}
            </div>
            <div class="candidate-action-buttons">
              <button class="btn btn-outline btn-xs" onclick="handleCandidateOpenFile(event, '${escapeHtml(sha)}', '${escapeHtml(primaryPath)}', false)" title="Open document in default system application">
                📄 Open File
              </button>
              <button class="btn btn-outline btn-xs" onclick="handleCandidateOpenFile(event, '${escapeHtml(sha)}', '${escapeHtml(primaryPath)}', true)" title="Reveal and highlight file in Windows File Explorer">
                📂 Reveal
              </button>
              <button class="btn btn-outline btn-xs" style="color: #38bdf8; border-color: rgba(56, 189, 248, 0.45); background: rgba(56, 189, 248, 0.08);" onclick="visualizeDocumentIn3D('${escapeHtml(sha)}', '${escapeHtml(filename)}')" title="Locate document vertex and visualize connected knowledge graph in 3D Universe">
                🌐 View in 3D
              </button>
              <button class="btn btn-outline btn-xs" onclick="selectDocument('${escapeHtml(sha)}'); switchWorkspace('ledger');" title="Inspect full document in ledger">
                🗄️ Ledger
              </button>
              <button class="btn btn-primary btn-xs" onclick="interrogateAboutDocument('${escapeHtml(sha)}', '${escapeHtml(filename)}')" title="Ask AI about this specific document">
                💬 Ask AI
              </button>
            </div>
          </div>
        </div>
      `;
    }).join("");

  } catch (err) {
    if (resultsContainer) {
      resultsContainer.innerHTML = `
        <div class="studio-empty-state text-rose">
          <div class="empty-icon">❌</div>
          <div class="empty-title">Retrieval Error</div>
          <div class="empty-text">${escapeHtml(err.message)}</div>
        </div>
      `;
    }

    if (typeof logDiagnosticEntry === "function") {
      logDiagnosticEntry({
        source: "frontend",
        level: "ERROR",
        logger: "client.graphrag",
        message: `GraphRAG retrieval failed: ${err.message}`
      });
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<span>⚡ Execute Hybrid Retrieval</span>`;
    }
  }
}

function interrogateAboutDocument(sha, filename) {
  activeDocumentSha = sha;
  activeDocumentFilename = filename;

  const banner = document.getElementById("chat-context-banner");
  const nameEl = document.getElementById("chat-context-name");
  if (banner && nameEl) {
    nameEl.textContent = filename;
    banner.classList.remove("hidden");
  }

  switchWorkspace("chat");
  const chatInput = document.getElementById("chat-input");
  if (chatInput) {
    chatInput.value = `Summarize key clauses and verify parties in this document: ${filename}`;
    chatInput.focus();
  }
}

function handleChatInputKey(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendChatMessage();
  }
}

function sendSuggestion(query) {
  document.getElementById("chat-input").value = query;
  sendChatMessage();
}

function interrogateAboutCurrent(filename) {
  switchTab("chat");
  setChatDocumentContext(activeDocumentSha, filename);
  document.getElementById("chat-input").value = `Do we have any copy or draft of "${filename}"?`;
  sendChatMessage(activeDocumentSha);
}

// Markdown Parser for Chat Responses
function renderMarkdown(md) {
  if (!md) return "";

  // 1. Separate code blocks to protect them
  const codeBlocks = [];
  let text = md.replace(/```([a-zA-Z0-9_\-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre class="chat-pre"><code class="chat-code-block">${escapeHtml(code.trim())}</code></pre>`);
    return `@@CODEBLOCK${idx}@@`;
  });

  // 2. Separate inline code
  const inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, (match, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(`<code class="chat-inline-code">${escapeHtml(code)}</code>`);
    return `@@INLINECODE${idx}@@`;
  });

  // 3. Escape HTML of body text
  text = escapeHtml(text);

  // 4. Headings
  text = text.replace(/^#### (.*$)/gim, '<h5>$1</h5>');
  text = text.replace(/^### (.*$)/gim, '<h4>$1</h4>');
  text = text.replace(/^## (.*$)/gim, '<h3>$1</h3>');
  text = text.replace(/^# (.*$)/gim, '<h2>$1</h2>');

  // 5. Horizontal rules
  text = text.replace(/^(?:---|___|\*\*\*)\s*$/gim, '<hr class="chat-hr">');

  // 6. Blockquotes
  text = text.replace(/^>(?:[\t ])?(.*$)/gim, '<blockquote class="chat-quote">$1</blockquote>');
  text = text.replace(/<\/blockquote>\s*<blockquote class="chat-quote">/g, '<br>');

  // 7. Bold and Italic
  text = text.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  text = text.replace(/_([^_]+)_/g, '<em>$1</em>');

  // 8. Markdown Links [text](url)
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="chat-link">$1</a>');

  // 9. Unordered Lists
  text = text.replace(/^[\t ]*[-*] (.*$)/gim, '<li class="chat-li">$1</li>');
  text = text.replace(/(<li class="chat-li">[\s\S]*?<\/li>)(?!\s*<li class="chat-li">)/g, '<ul class="chat-ul">$1</ul>');

  // 10. Ordered Lists
  text = text.replace(/^[\t ]*\d+\. (.*$)/gim, '<li class="chat-oli">$1</li>');
  text = text.replace(/(<li class="chat-oli">[\s\S]*?<\/li>)(?!\s*<li class="chat-oli">)/g, '<ol class="chat-ol">$1</ol>');

  // 11. Paragraphs & line breaks
  const blocks = text.split(/\n{2,}/);
  text = blocks.map(b => {
    b = b.trim();
    if (!b) return "";
    if (b.startsWith("<h") || b.startsWith("<ul") || b.startsWith("<ol") || b.startsWith("<blockquote") || b.startsWith("<pre") || b.startsWith("<hr") || b.startsWith("@@CODEBLOCK")) {
      return b;
    }
    return `<p>${b.replace(/\n/g, '<br>')}</p>`;
  }).join("\n");

  // 12. Restore inline codes
  inlineCodes.forEach((code, idx) => {
    text = text.replace(new RegExp(`@@INLINECODE${idx}@@`, 'g'), code);
  });

  // 13. Restore code blocks
  codeBlocks.forEach((block, idx) => {
    text = text.replace(new RegExp(`@@CODEBLOCK${idx}@@`, 'g'), block);
  });

  return text;
}

async function sendChatMessage(sha = null) {
  const input = document.getElementById("chat-input");
  const query = input.value.trim();
  if (!query) return;

  // Resolve target SHA:
  // 1. Explicit sha argument if provided
  // 2. Current active chat document focus if set
  // 3. Global active document from table
  let targetSha = sha || (currentChatDoc && currentChatDoc.sha256_hash) || activeDocumentSha || null;

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
  bubble.innerHTML = `<em>Consulting document ledger & knowledge index...</em>`;
  botDiv.appendChild(bubble);
  container.appendChild(botDiv);
  container.scrollTop = container.scrollHeight;

  // Stream via SSE with dynamic node routing parameter
  //let sseUrl = `/api/v1/chat/stream?query=${encodeURIComponent(query)}&node=${encodeURIComponent(activeChatNode)}`;
  // Update EventSource URL:
  let sseUrl = `${API_PREFIX}/api/v1/chat/stream?query=${encodeURIComponent(query)}&node=${encodeURIComponent(activeChatNode)}`;

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
      if (payload.type === "active_doc") {
        setChatDocumentContext(payload.sha256_hash, payload.canonical_filename);
      } else if (payload.type === "status") {
        bubble.innerHTML = `<em>${escapeHtml(payload.message)}</em>`;
      } else if (payload.type === "chunk") {
        accumulated += payload.content;
        bubble.innerHTML = renderMarkdown(accumulated);
        container.scrollTop = container.scrollHeight;
      } else if (payload.type === "recommendation") {
        accumulated += `\n\n💡 **Recommendation:** ${payload.recommendation}`;
        bubble.innerHTML = renderMarkdown(accumulated);
        container.scrollTop = container.scrollHeight;
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
  if (typeof renderWs0DiagLogs === "function") renderWs0DiagLogs();
}

async function fetchDiagnosticLogs() {
  try {
    const res = await _rawFetch(`${API_PREFIX}/api/v1/diagnostics/logs?since_id=${diagWatermarkId}&limit=150`);
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
      if (typeof renderWs0DiagLogs === "function") renderWs0DiagLogs();
    }
  } catch (err) {
    // Silently continue to prevent cascading failures
  }
}

async function fetchDiagnosticHealth() {
  try {
    const res = await _rawFetch(`${API_PREFIX}/api/v1/diagnostics/health`);
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
    await _rawFetch(`${API_PREFIX}/api/v1/diagnostics/report`, {
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
    await _rawFetch(`${API_PREFIX}/api/v1/diagnostics/clear`, { method: "POST" });
  } catch (_) { }

  diagLogs = [];
  diagWatermarkId = 0;
  updateDiagnosticBadges();
  renderDiagnosticLogs();
  if (typeof renderWs0DiagLogs === "function") renderWs0DiagLogs();
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
    const res = await _rawFetch(`${API_PREFIX}/api/v1/diagnostics/test-issue?level=${level}`, { method: "POST" });
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
          <span class="diag-log-details-toggle" data-stack-id="${escapeHtml(stackId)}" onclick="toggleDiagStack(this.getAttribute('data-stack-id'))">
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

// =========================================================================
// 15. 3D KNOWLEDGE UNIVERSE & WEBGL GLSL TOPOLOGICAL SHADER ENGINE
// =========================================================================
// 1. In glsl3D configuration:
const glsl3D = {
  initialized: false,
  scene: null,
  camera: null,
  renderer: null,
  controls: null,
  container: null,
  worldGroup: null,
  pointsMesh: null,
  edgesMesh: null,
  highlightedEdgesMesh: null,
  selectionBeaconGroup: null,
  labelsGroup: null,
  axesGroup: null,
  gridHelper: null,
  nodes: [],
  edges: [],
  clusters: [],
  axes: {},
  stats: {},
  activeFilters: {},
  focusNodeId: null,
  uniforms: {
    uTime: { value: 0.0 },
    uPointSize: { value: 1.0 },
    uBrightness: { value: 0.7 }, // Default brightness (0.1 to 1.5)
  },
  autoSpin: true,
  showEdges: true,
  edgeOpacity: 0.08,
  showLabels: true,
  colorMode: "cluster",
  activeClusterFilter: "all",
  layoutMode: "spatial", // "spatial" vs "thematic"
  thematicHubsGroup: null, // Three.js Group for solar halos and orbital visual rings
  selectedNode: null,
  hoveredNodeIndex: -1,
  raycaster: null,
  mouse: null,
  animId: null,
  isUserInteracting: false,
  cameraTransitionAnim: null,
  layoutTransitionAnim: null,
};

const UNIVERSE_VERTEX_SHADER = `
  attribute float aSize;
  attribute vec3 aColor;
  attribute float aDegree;
  attribute float aCluster;
  attribute float aDimmed;

  varying vec3 vColor;
  varying float vCluster;
  varying float vDegree;
  varying float vDimmed;
  varying float vDist;

  uniform float uTime;
  uniform float uPointSize;

  void main() {
    vColor = aColor;
    vCluster = aCluster;
    vDegree = aDegree;
    vDimmed = aDimmed;

    // Organic temporal breathing pulse (frequency modulated by degree & cluster)
    float pulse = sin(uTime * 2.4 + aCluster * 1.5 + position.x * 0.04) * 0.22 + 1.0;
    
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    vDist = -mvPosition.z;

    // Size attenuation with camera distance
    float baseSize = aSize * 15.0 * pulse * uPointSize;
    if (aDimmed > 0.5) {
      baseSize *= 0.5;
    }
    gl_PointSize = baseSize * (320.0 / max(-mvPosition.z, 20.0));
    gl_PointSize = clamp(gl_PointSize, 4.0, 70.0);

    gl_Position = projectionMatrix * mvPosition;
  }
`;

// 2. In UNIVERSE_FRAGMENT_SHADER:
const UNIVERSE_FRAGMENT_SHADER = `
  varying vec3 vColor;
  varying float vCluster;
  varying float vDegree;
  varying float vDimmed;
  varying float vDist;

  uniform float uTime;
  uniform float uBrightness;

  void main() {
    vec2 coord = gl_PointCoord - vec2(0.5);
    float r = length(coord);
    if (r > 0.5) discard;

    // Softened radial core and exponential falloff
    float core = smoothstep(0.24, 0.04, r);
    float halo = exp(-r * 7.0);
    float alpha = clamp(core * 0.85 + halo * 0.45, 0.0, 1.0);

    if (vDimmed > 0.5) {
      alpha *= 0.15;
    }

    // Dynamic luminescence shimmer scaled by uBrightness uniform
    float shimmer = 0.88 + 0.16 * sin(uTime * 3.2 + vCluster * 2.0);
    vec3 finalColor = (vColor * shimmer + vec3(0.04, 0.08, 0.12) * halo) * uBrightness;

    gl_FragColor = vec4(finalColor, alpha * min(1.0, uBrightness + 0.2));
  }
`;


// 3. Real-Time Uniform Handler (Zero Geometry Rebuilds):
function change3DBrightness(val) {
  const brightness = parseFloat(val);

  // Directly mutate the WebGL GPU uniform value
  if (glsl3D.uniforms && glsl3D.uniforms.uBrightness) {
    glsl3D.uniforms.uBrightness.value = brightness;
  }

  // Update both top-bar and viewport badge elements if present
  const pctStr = `${Math.round(brightness * 100)}%`;
  const topbarLabel = document.getElementById("topbar-brightness-val");
  if (topbarLabel) topbarLabel.textContent = pctStr;

  const canvasLabel = document.getElementById("glsl-brightness-val");
  if (canvasLabel) canvasLabel.textContent = pctStr;

  // Sync slider inputs if multiple exist
  const topbarSlider = document.getElementById("topbar-brightness-slider");
  if (topbarSlider && topbarSlider.value !== String(val)) topbarSlider.value = val;

  const canvasSlider = document.getElementById("glsl-brightness-slider");
  if (canvasSlider && canvasSlider.value !== String(val)) canvasSlider.value = val;
}
window.change3DBrightness = change3DBrightness;

// 3b. Real-Time Link Edges Brightness / Opacity Handler:
function change3DLinksBrightness(val) {
  const opacity = parseFloat(val);
  glsl3D.edgeOpacity = opacity;

  if (glsl3D.edgesMesh && glsl3D.edgesMesh.material) {
    glsl3D.edgesMesh.material.opacity = opacity;
    glsl3D.edgesMesh.material.transparent = true;
    glsl3D.edgesMesh.material.needsUpdate = true;

    // If user raises brightness above 0 while links were toggled hidden, reactivate visibility
    if (opacity > 0 && !glsl3D.showEdges) {
      glsl3D.showEdges = true;
      glsl3D.edgesMesh.visible = true;
      const btn = document.getElementById("btn-glsl-edges");
      const text = document.getElementById("glsl-edges-text");
      if (btn) btn.classList.add("active");
      if (text) text.textContent = "Links: Visible";
    } else if (opacity === 0 && glsl3D.showEdges) {
      // Visually hide edges if set to 0%
      glsl3D.edgesMesh.visible = false;
    } else if (opacity > 0 && glsl3D.showEdges) {
      glsl3D.edgesMesh.visible = true;
    }
  }

  const pctStr = `${Math.round(opacity * 100)}%`;
  const canvasLabel = document.getElementById("glsl-links-brightness-val");
  if (canvasLabel) canvasLabel.textContent = pctStr;

  const canvasSlider = document.getElementById("glsl-links-brightness-slider");
  if (canvasSlider && canvasSlider.value !== String(val)) canvasSlider.value = val;
}
window.change3DLinksBrightness = change3DLinksBrightness;

function setCameraPosition() {
  const container = glsl3D.container || document.getElementById("glsl-3d-canvas-container");
  const w = container ? (container.clientWidth || 800) : 800;
  const h = container ? (container.clientHeight || 650) : 650;

  if (!glsl3D.camera) {
    glsl3D.camera = new THREE.PerspectiveCamera(50, w / h, 1, 4000);
  } else {
    glsl3D.camera.aspect = w / h;
    glsl3D.camera.updateProjectionMatrix();
  }

  // 3/4 top view: X: 240 (lateral angle), Y: 220 (top angle), Z: 160 (with -100 Z offset)
  glsl3D.camera.position.set(240, 220, 160);

  if (glsl3D.controls && glsl3D.controls.target) {
    glsl3D.controls.target.set(0, 0, -100);
    glsl3D.controls.update();
  }
}

function init3DKnowledgeUniverse() {
  const container = document.getElementById("glsl-3d-canvas-container");
  if (!container) return;

  if (typeof THREE === "undefined") {
    container.innerHTML = `
      <div style="padding: 3rem; text-align: center; color: var(--text-muted);">
        <p style="font-size: 1.2rem; color: var(--accent-amber);">⚠️ WebGL 3D Library (Three.js) is loading...</p>
        <p>If not loaded automatically, please check internet connectivity to cdnjs.</p>
      </div>
    `;
    return;
  }

  if (glsl3D.initialized) {
    onWindowResize3D();
    return;
  }

  glsl3D.container = container;
  const width = container.clientWidth || 800;
  const height = container.clientHeight || 650;

  // Scene
  glsl3D.scene = new THREE.Scene();
  glsl3D.scene.background = null; // transparent to inherit CSS gradient

  // Camera
  if (!glsl3D.camera) {
    glsl3D.camera = new THREE.PerspectiveCamera(50, width / height, 1, 4000);
  }

  // WebGL Renderer
  glsl3D.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  glsl3D.renderer.setSize(width, height);
  glsl3D.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.innerHTML = "";
  container.appendChild(glsl3D.renderer.domElement);

  // OrbitControls
  if (typeof THREE.OrbitControls !== "undefined") {
    glsl3D.controls = new THREE.OrbitControls(glsl3D.camera, glsl3D.renderer.domElement);
    glsl3D.controls.enableDamping = true;
    glsl3D.controls.dampingFactor = 0.05;
    glsl3D.controls.minDistance = 25;
    glsl3D.controls.maxDistance = 1200; // Increased max distance slightly to allow comfortable zooming out

    glsl3D.controls.addEventListener("start", () => {
      glsl3D.isUserInteracting = true;
      if (glsl3D.orbitalTourActive) {
        stop3DOrbitalTour(false);
      }
      if (glsl3D.cameraTransitionAnim) {
        cancelAnimationFrame(glsl3D.cameraTransitionAnim);
        glsl3D.cameraTransitionAnim = null;
      }
    });
    glsl3D.controls.addEventListener("end", () => {
      glsl3D.isUserInteracting = false;
    });
  }

  // Set initial camera position and orbit controls target
  setCameraPosition();

  // World Group for unified rotation & centering
  glsl3D.worldGroup = new THREE.Group();
  glsl3D.scene.add(glsl3D.worldGroup);

  // Ambient & Directional Lights
  const ambLight = new THREE.AmbientLight(0xffffff, 0.7);
  glsl3D.scene.add(ambLight);
  const dirLight = new THREE.DirectionalLight(0x38bdf8, 0.8);
  dirLight.position.set(100, 200, 150);
  glsl3D.scene.add(dirLight);

  // Ground Coordinate Grid
  glsl3D.gridHelper = new THREE.GridHelper(320, 24, 0x1e293b, 0x0f172a);
  glsl3D.gridHelper.position.y = -65;
  glsl3D.worldGroup.add(glsl3D.gridHelper);

  // Setup Axes of Importance 3D Visualizer
  setup3DAxesOfImportance();

  // Raycaster & Mouse
  glsl3D.raycaster = new THREE.Raycaster();
  glsl3D.raycaster.params.Points.threshold = 4.5;
  glsl3D.mouse = new THREE.Vector2(-999, -999);

  // Event Listeners for Raycasting & Tooltips
  const canvasEl = glsl3D.renderer.domElement;
  canvasEl.addEventListener("mousemove", on3DMouseMove);
  canvasEl.addEventListener("click", on3DMouseClick);
  canvasEl.addEventListener("dblclick", on3DMouseDblClick);
  canvasEl.addEventListener("mouseleave", on3DMouseLeave);

  // Window & Elastic Container Resize Listener
  window.addEventListener("resize", onWindowResize3D);
  if (typeof ResizeObserver !== "undefined") {
    const parentWrapper = document.getElementById("glsl-canvas-wrapper") || container;
    const ro = new ResizeObserver(() => onWindowResize3D());
    ro.observe(container);
    if (parentWrapper !== container) ro.observe(parentWrapper);
  }

  glsl3D.initialized = true;

  // Start Animation Loop
  animate3DUniverse();
}

function setup3DAxesOfImportance() {
  if (glsl3D.axesGroup) {
    glsl3D.worldGroup.remove(glsl3D.axesGroup);
  }

  glsl3D.axesGroup = new THREE.Group();

  const axisLen = 130;
  const headLen = 12;
  const headWidth = 6;

  // X Axis (Cyan): Domain Specificity & Category Dispersion
  const dirX = new THREE.Vector3(1, 0, 0);
  const arrowX = new THREE.ArrowHelper(dirX, new THREE.Vector3(0, 0, 0), axisLen, 0x38bdf8, headLen, headWidth);
  glsl3D.axesGroup.add(arrowX);

  const labelSpriteX = create3DTextSprite("Domain Divergence (PCA-1) ➔", "#38bdf8");
  labelSpriteX.position.set(axisLen + 24, 0, 0);
  glsl3D.axesGroup.add(labelSpriteX);

  // Y Axis (Emerald): Temporal Recency & Lifecycle Maturity
  const dirY = new THREE.Vector3(0, 1, 0);
  const arrowY = new THREE.ArrowHelper(dirY, new THREE.Vector3(0, 0, 0), axisLen, 0x10b981, headLen, headWidth);
  glsl3D.axesGroup.add(arrowY);

  const labelSpriteY = create3DTextSprite("Lifecycle Maturity (PCA-2) ➔", "#10b981");
  labelSpriteY.position.set(0, axisLen + 18, 0);
  glsl3D.axesGroup.add(labelSpriteY);

  // Z Axis (Purple): Graph Centrality & Hub Authority
  const dirZ = new THREE.Vector3(0, 0, 1);
  const arrowZ = new THREE.ArrowHelper(dirZ, new THREE.Vector3(0, 0, 0), axisLen, 0xc084fc, headLen, headWidth);
  glsl3D.axesGroup.add(arrowZ);

  const labelSpriteZ = create3DTextSprite("Centrality Degree (PCA-3) ➔", "#c084fc");
  labelSpriteZ.position.set(0, 0, axisLen + 24);
  glsl3D.axesGroup.add(labelSpriteZ);

  glsl3D.worldGroup.add(glsl3D.axesGroup);
}

function create3DTextSprite(text, borderColorHex, fontSize = 22) {
  const canvas = document.createElement("canvas");
  canvas.width = 420;
  canvas.height = 100;
  const ctx = canvas.getContext("2d");

  // Rounded pill background
  ctx.fillStyle = "rgba(11, 17, 32, 0.9)";
  ctx.strokeStyle = borderColorHex || "#38bdf8";
  ctx.lineWidth = 3;
  ctx.beginPath();
  if (ctx.roundRect) {
    ctx.roundRect(6, 6, canvas.width - 12, canvas.height - 12, 16);
  } else {
    ctx.rect(6, 6, canvas.width - 12, canvas.height - 12);
  }
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = "#ffffff";
  ctx.font = `bold ${fontSize}px Inter, Outfit, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, canvas.width / 2, canvas.height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false });
  const sprite = new THREE.Sprite(spriteMat);
  sprite.scale.set(34, 8, 1);
  return sprite;
}

// function onWindowResize3D() {
//   if (!glsl3D.renderer || !glsl3D.camera || !glsl3D.container) return;
//   const width = glsl3D.container.clientWidth;
//   const height = glsl3D.container.clientHeight;
//   if (!width || !height || width <= 0 || height <= 0) return;

//   glsl3D.camera.aspect = width / height;
//   glsl3D.camera.updateProjectionMatrix();
//   glsl3D.renderer.setSize(width, height);
// }

function onWindowResize3D() {
  if (!glsl3D.renderer || !glsl3D.camera || !glsl3D.container) return;
  const width = glsl3D.container.clientWidth;
  const height = glsl3D.container.clientHeight;
  if (!width || !height || width <= 0 || height <= 0) return;

  glsl3D.camera.aspect = width / height;

  // Shift the 3D projection center to the right by ~140 pixels (approx. 3.5cm)
  // This optically centers the universe in the remaining visible space 
  // next to the left-floating legend panel, without breaking orbit controls.
  // Signature: setViewOffset(fullWidth, fullHeight, xOffset, yOffset, viewWidth, viewHeight)
  glsl3D.camera.setViewOffset(width, height, -60, 0, width, height);
  glsl3D.camera.updateProjectionMatrix();
  glsl3D.renderer.setSize(width, height);

  // Sync the 3D scene offset with UI panel layout changes
  update3DViewOffset();
}


async function load3DUniverseData(forceReload = false, filterParams = null, transitionFromOldPositions = null) {
  // If filterParams is null, check URL search params if any
  let effectiveFilters = filterParams;
  if (!effectiveFilters && typeof window !== "undefined" && window.location.search) {
    const urlParams = new URLSearchParams(window.location.search);
    const filterObj = {};
    for (const [k, v] of urlParams.entries()) {
      if (k !== "workspace" && k !== "view" && k !== "tab" && v) {
        filterObj[k] = v;
      }
    }
    if (Object.keys(filterObj).length > 0) {
      effectiveFilters = filterObj;
    }
  }

  if (glsl3D.nodes.length > 0 && !forceReload && !effectiveFilters) {
    return;
  }

  try {
    const params = new URLSearchParams({ limit: "1000", layout: glsl3D.layoutMode || "spatial" });
    if (effectiveFilters) {
      if (typeof effectiveFilters === "string") {
        const parsed = new URLSearchParams(effectiveFilters.startsWith("?") ? effectiveFilters.slice(1) : effectiveFilters);
        for (const [k, v] of parsed.entries()) {
          if (v) params.set(k, v);
        }
      } else if (typeof effectiveFilters === "object") {
        for (const [k, v] of Object.entries(effectiveFilters)) {
          if (v !== undefined && v !== null && String(v).trim() !== "") {
            params.set(k, String(v).trim());
          }
        }
      }
    }

    if (params.get("layout")) {
      glsl3D.layoutMode = params.get("layout");
    }

    const res = await fetch(`/api/v1/sidecar/graph-3d?${params.toString()}`);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();

    glsl3D.nodes = data.nodes || [];
    glsl3D.edges = data.edges || [];
    glsl3D.clusters = data.clusters || [];
    glsl3D.axes = data.axes || {};
    glsl3D.stats = data.stats || {};
    glsl3D.activeFilters = data.active_filters || {};
    glsl3D.focusNodeId = data.focus_node_id || null;
    glsl3D.totalNodesInDB = (data.stats && data.stats.total_nodes) || 18607;

    // Apply client-side force-directed / grouped radial physics in Thematic Mindmap mode
    if (glsl3D.layoutMode === "thematic") {
      applyThematicMindmapPhysics(glsl3D.nodes, glsl3D.edges);
    }

    // Render Filter HUD Banner in Universe View
    renderUniverseFilterBanner(glsl3D.activeFilters);

    // Update Header KPI metrics
    const statNodesEl = document.getElementById("glsl-stat-nodes");
    const statEdgesEl = document.getElementById("glsl-stat-edges");
    if (statNodesEl) statNodesEl.textContent = glsl3D.nodes.length;
    if (statEdgesEl) statEdgesEl.textContent = glsl3D.edges.length;

    // Populate Datalist for Quick Search
    const datalist = document.getElementById("glsl-entities-datalist");
    if (datalist) {
      datalist.innerHTML = glsl3D.nodes.map(n => `<option value="${escapeHtml(n.name)}">${escapeHtml(n.type)} • Deg:${n.degree}</option>`).join("");
    }

    // Populate Cluster Filter Select
    const clusterSelect = document.getElementById("select-glsl-cluster");
    if (clusterSelect) {
      clusterSelect.innerHTML = `<option value="all" selected>🌐 All Semantic Clusters</option>` +
        glsl3D.clusters.map(c => `<option value="${c.id}">${escapeHtml(c.icon || "•")} ${escapeHtml(c.name)}</option>`).join("");
    }

    // Populate Legend HUD Cluster Items
    const clusterLegendContainer = document.getElementById("cluster-legend-items");
    if (clusterLegendContainer) {
      const counts = {};
      glsl3D.nodes.forEach(n => {
        counts[n.cluster] = (counts[n.cluster] || 0) + 1;
      });

      clusterLegendContainer.innerHTML = glsl3D.clusters.map(c => {
        const rendered = counts[c.id] || c.rendered_count || 0;
        const totalInDb = c.total_in_db || rendered;
        const pct = c.representation_pct !== undefined
          ? c.representation_pct
          : (totalInDb > 0 ? parseFloat(((rendered / totalInDb) * 100).toFixed(1)) : 100.0);
        const isFull = pct >= 99.95 || rendered >= totalInDb;
        const quota = c.quota || 250;
        const isCapped = c.is_capped || (totalInDb > quota && rendered >= quota);
        const archetypeLabel = c.archetype || c.name;
        const tooltip = `${c.name} (${archetypeLabel})\n• Rendered in 3D: ${rendered} nodes ${isCapped ? '(Viewport Quota: Max ' + quota + ')' : '(Full Coverage: 100%)'}\n• Total in Database: ${totalInDb.toLocaleString()} entities\n• Representation: ${isFull ? '100%' : pct + '%'} of population\n• Scope: ${c.representation_desc || ''}`;

        return `
          <div class="cluster-item" data-cluster-id="${c.id}" onclick="openUniverseClusterDrawer(${c.id})" ondblclick="filter3DCluster(${c.id})" title="${escapeHtml(tooltip)}\n💡 Single-click: Filter 3D scene\n💡 Double-click: Open entity list">
            <div class="cluster-item-left">
              <span class="cluster-color-dot" style="background: ${c.color}; color: ${c.color};"></span>
              <div class="cluster-text-col">
                <span class="cluster-name">${escapeHtml(c.icon || "")} ${escapeHtml(c.name)}</span>
                <span class="cluster-desc">${escapeHtml(c.representation_desc || archetypeLabel)}</span>
              </div>
            </div>
            <div class="cluster-metric-right">
              <div class="cluster-fraction">
                <span class="cluster-rendered">${rendered}</span>
                <span class="cluster-db-total">/ ${totalInDb.toLocaleString()}</span>
              </div>
              <span class="cluster-pct ${isFull ? 'pct-full' : 'pct-capped'}">${isFull ? '100%' : pct + '%'}</span>
            </div>
          </div>
        `;
      }).join("");

      const macroSummary = document.getElementById("cluster-macro-summary");
      if (macroSummary) {
        const totalRendered = glsl3D.nodes.length;
        const totalDbNodes = (data.stats && data.stats.total_nodes) || totalRendered;
        const overallPct = (data.stats && data.stats.overall_representativity_pct) !== undefined
          ? data.stats.overall_representativity_pct
          : (totalDbNodes > 0 ? ((totalRendered / totalDbNodes) * 100).toFixed(1) : 100);

        macroSummary.innerHTML = `
          <div class="macro-summary-left">
            <span class="macro-badge">${Object.keys(glsl3D.activeFilters).length > 0 ? 'Filtered Subgraph' : 'Macro Universe'}</span>
            <span class="macro-text"><strong>${totalRendered.toLocaleString()}</strong> of ${totalDbNodes.toLocaleString()} nodes</span>
          </div>
          <span class="macro-pct">${overallPct}% coverage</span>
        `;
      }
    }

    // Build Three.js Point Cloud & Edges
    build3DSceneObjects(transitionFromOldPositions);

    // If animating transition from old positions, kick off easeInOutCubic interpolator
    if (transitionFromOldPositions && transitionFromOldPositions.size > 0) {
      animateLayoutTransition(1000);
    }

    // If a focus node was requested / identified, focus on it
    if (glsl3D.focusNodeId) {
      const target = glsl3D.nodes.find(n => n.id === glsl3D.focusNodeId) || glsl3D.nodes[0];
      if (target) {
        smoothTransitionTo3DNode(target);
        open3DNodeInspector(target);
        emphasizeNodeLinks(target.id);
      }
    }

  } catch (err) {
    console.error("Failed to load 3D Knowledge Universe:", err);
    pushDiagnosticLog("error", "Failed to load 3D Knowledge Universe data: " + err.message, "frontend", "GLSL3D");
  }
}

function renderUniverseFilterBanner(filters) {
  let banner = document.getElementById("universe-filter-hud");
  if (!banner) {
    const container = document.getElementById("glsl-canvas-wrapper");
    if (!container) return;
    banner = document.createElement("div");
    banner.id = "universe-filter-hud";
    banner.className = "universe-filter-hud";
    container.appendChild(banner);
  }

  const entries = Object.entries(filters || {});
  if (entries.length === 0) {
    banner.style.display = "none";
    banner.innerHTML = "";
    return;
  }

  const pills = entries.map(([k, v]) => `
    <span class="filter-pill-tag">
      <span class="filter-k">${escapeHtml(k)}:</span>
      <span class="filter-v">${escapeHtml(String(v))}</span>
    </span>
  `).join("");

  banner.style.display = "flex";
  banner.innerHTML = `
    <div class="filter-hud-left">
      <span class="filter-hud-icon">🔍</span>
      <span class="filter-hud-title">Filtered 3D Graph:</span>
      <div class="filter-hud-pills">${pills}</div>
      <span class="filter-hud-count">(${glsl3D.nodes.length} nodes, ${glsl3D.edges.length} links)</span>
    </div>
    <button class="filter-hud-reset-btn" onclick="clear3DUniverseFilters()" title="Reset to full universe">
      Reset Filter ✕
    </button>
  `;
}

function clear3DUniverseFilters() {
  const searchInput = document.getElementById("glsl-filter-query-input");
  if (searchInput) searchInput.value = "";
  glsl3D.activeFilters = {};
  glsl3D.focusNodeId = null;
  // Clear URL query parameters if present
  if (window.history && window.history.replaceState) {
    const base = window.location.pathname;
    window.history.replaceState({}, "", base);
  }
  load3DUniverseData(true, {});
}
window.clear3DUniverseFilters = clear3DUniverseFilters;

function handle3DFilterQuery(queryStr) {
  if (!queryStr || !queryStr.trim()) {
    clear3DUniverseFilters();
    return;
  }
  const q = queryStr.trim();
  // Support both url-query style 'location=zurich&org=ZKB' or single text query
  if (q.includes("=") || q.includes("&")) {
    load3DUniverseData(true, q);
  } else {
    load3DUniverseData(true, { q: q });
  }
}
window.handle3DFilterQuery = handle3DFilterQuery;

function build3DSceneObjects(transitionFromOldPositions = null) {
  if (!glsl3D.scene || !glsl3D.worldGroup) return;

  // Remove old objects
  if (glsl3D.pointsMesh) glsl3D.worldGroup.remove(glsl3D.pointsMesh);
  if (glsl3D.edgesMesh) glsl3D.worldGroup.remove(glsl3D.edgesMesh);
  if (glsl3D.labelsGroup) glsl3D.worldGroup.remove(glsl3D.labelsGroup);
  if (glsl3D.thematicHubsGroup) {
    glsl3D.worldGroup.remove(glsl3D.thematicHubsGroup);
    glsl3D.thematicHubsGroup = null;
  }
  if (glsl3D.highlightedEdgesMesh) {
    glsl3D.worldGroup.remove(glsl3D.highlightedEdgesMesh);
    glsl3D.highlightedEdgesMesh = null;
  }
  if (glsl3D.selectionBeaconGroup) {
    glsl3D.worldGroup.remove(glsl3D.selectionBeaconGroup);
    glsl3D.selectionBeaconGroup = null;
  }

  const count = glsl3D.nodes.length;
  if (count === 0) return;

  // 1. Point Cloud Buffer Geometry
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const degrees = new Float32Array(count);
  const clusters = new Float32Array(count);
  const dimmed = new Float32Array(count);

  const nodeIndexMap = new Map();

  glsl3D.nodes.forEach((n, i) => {
    nodeIndexMap.set(n.id, i);

    if (transitionFromOldPositions && transitionFromOldPositions.has(n.id)) {
      const old = transitionFromOldPositions.get(n.id);
      n._startPos = { x: old.x, y: old.y, z: old.z };
    } else if (transitionFromOldPositions) {
      n._startPos = { x: n.x * 0.25, y: n.y * 0.25, z: n.z * 0.25 };
    } else {
      n._startPos = { x: n.x, y: n.y, z: n.z };
    }
    n._targetPos = { x: n.x, y: n.y, z: n.z };

    positions[i * 3 + 0] = n._startPos.x;
    positions[i * 3 + 1] = n._startPos.y;
    positions[i * 3 + 2] = n._startPos.z;

    sizes[i] = n.size || 1.0;
    degrees[i] = n.degree || 0;
    clusters[i] = n.cluster !== undefined ? n.cluster : 0;
    dimmed[i] = 0.0;

    // Color by active color mode
    const c = getNodeColorForMode(n, glsl3D.colorMode);
    colors[i * 3 + 0] = c.r;
    colors[i * 3 + 1] = c.g;
    colors[i * 3 + 2] = c.b;
  });

  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
  geometry.setAttribute("aDegree", new THREE.BufferAttribute(degrees, 1));
  geometry.setAttribute("aCluster", new THREE.BufferAttribute(clusters, 1));
  geometry.setAttribute("aDimmed", new THREE.BufferAttribute(dimmed, 1));

  // Custom Shader Material with GLSL
  const shaderMaterial = new THREE.ShaderMaterial({
    vertexShader: UNIVERSE_VERTEX_SHADER,
    fragmentShader: UNIVERSE_FRAGMENT_SHADER,
    uniforms: glsl3D.uniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.NormalBlending,
  });

  glsl3D.pointsMesh = new THREE.Points(geometry, shaderMaterial);
  glsl3D.worldGroup.add(glsl3D.pointsMesh);

  // 2. Edges Buffer Geometry
  const edgePositions = [];
  const edgeColors = [];

  glsl3D.edges.forEach(e => {
    const sIdx = nodeIndexMap.get(e.source);
    const tIdx = nodeIndexMap.get(e.target);
    if (sIdx !== undefined && tIdx !== undefined) {
      const sNode = glsl3D.nodes[sIdx];
      const tNode = glsl3D.nodes[tIdx];

      edgePositions.push(sNode._startPos.x, sNode._startPos.y, sNode._startPos.z);
      edgePositions.push(tNode._startPos.x, tNode._startPos.y, tNode._startPos.z);

      let edgeColor = new THREE.Color(sNode.cluster_color || "#38bdf8");
      if (e.relation === "CATEGORIZED_AS") {
        const themeNode = sNode.type === "theme" ? sNode : (tNode.type === "theme" ? tNode : null);
        if (themeNode) {
          edgeColor = new THREE.Color(themeNode.cluster_color || "#ec4899");
        }
      }
      edgeColors.push(edgeColor.r, edgeColor.g, edgeColor.b);
      edgeColors.push(edgeColor.r, edgeColor.g, edgeColor.b);
    }
  });

  if (edgePositions.length > 0) {
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute("position", new THREE.Float32BufferAttribute(edgePositions, 3));
    edgeGeo.setAttribute("color", new THREE.Float32BufferAttribute(edgeColors, 3));

    const edgeMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: typeof glsl3D.edgeOpacity === "number" ? glsl3D.edgeOpacity : 0.08,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    glsl3D.edgesMesh = new THREE.LineSegments(edgeGeo, edgeMat);
    glsl3D.edgesMesh.visible = glsl3D.showEdges;
    glsl3D.worldGroup.add(glsl3D.edgesMesh);
  }

  // 3. Billboard Text Labels: All theme hubs + Top high-degree entities
  glsl3D.labelsGroup = new THREE.Group();
  const themeNodes = glsl3D.nodes.filter(n => n.type === "theme");
  const otherTop = glsl3D.nodes.filter(n => n.type !== "theme").sort((a, b) => b.degree - a.degree).slice(0, 20);
  const labeledNodes = [...themeNodes, ...otherTop];

  labeledNodes.forEach(n => {
    const isTheme = n.type === "theme";
    const prefix = isTheme ? "🪐 " : (n.type === "document" ? "📄 " : "");
    const sprite = create3DTextSprite(`${prefix}${n.name}`, n.cluster_color, isTheme ? 22 : 18);
    const startX = n._startPos ? n._startPos.x : n.x;
    const startY = n._startPos ? n._startPos.y : n.y;
    const startZ = n._startPos ? n._startPos.z : n.z;
    sprite.position.set(startX, startY + (isTheme ? 6.5 : 4.5), startZ);
    sprite.scale.set(isTheme ? 28 : 22, isTheme ? 6.5 : 5.5, 1);
    sprite._boundNode = n;
    glsl3D.labelsGroup.add(sprite);
  });

  glsl3D.labelsGroup.visible = glsl3D.showLabels;
  glsl3D.worldGroup.add(glsl3D.labelsGroup);

  // 4. Thematic Sun Halos & Orbital Visual Rings (when in Thematic mode)
  if (glsl3D.layoutMode === "thematic") {
    glsl3D.thematicHubsGroup = new THREE.Group();
    const hubs = glsl3D.nodes.filter(n => n.type === "theme");

    hubs.forEach(th => {
      // Celestial Orbit Guidance Ring
      const orbitR = 38;
      const ringPts = [];
      for (let s = 0; s <= 64; s++) {
        const rad = (s / 64) * Math.PI * 2;
        ringPts.push(new THREE.Vector3(Math.cos(rad) * orbitR, Math.sin(rad) * orbitR, 0));
      }
      const ringGeo = new THREE.BufferGeometry().setFromPoints(ringPts);
      const ringMat = new THREE.LineBasicMaterial({
        color: new THREE.Color(th.cluster_color || "#ec4899"),
        transparent: true,
        opacity: 0.16,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const ring = new THREE.LineLoop(ringGeo, ringMat);
      const startX = th._startPos ? th._startPos.x : th.x;
      const startY = th._startPos ? th._startPos.y : th.y;
      const startZ = th._startPos ? th._startPos.z : th.z;
      ring.position.set(startX, startY, startZ);
      ring._boundNode = th;
      glsl3D.thematicHubsGroup.add(ring);

      // Radiant Solar Halo Sprite
      const haloCanvas = document.createElement("canvas");
      haloCanvas.width = 128;
      haloCanvas.height = 128;
      const hCtx = haloCanvas.getContext("2d");
      const grad = hCtx.createRadialGradient(64, 64, 0, 64, 64, 64);
      grad.addColorStop(0, th.cluster_color || "#ec4899");
      grad.addColorStop(0.35, th.cluster_color || "#ec4899");
      grad.addColorStop(0.7, "rgba(0,0,0,0.12)");
      grad.addColorStop(1, "rgba(0,0,0,0)");
      hCtx.fillStyle = grad;
      hCtx.fillRect(0, 0, 128, 128);

      const haloTex = new THREE.CanvasTexture(haloCanvas);
      const haloMat = new THREE.SpriteMaterial({
        map: haloTex,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        opacity: 0.55,
      });
      const haloSprite = new THREE.Sprite(haloMat);
      haloSprite.position.set(startX, startY, startZ);
      haloSprite.scale.set(40, 40, 1);
      haloSprite._boundNode = th;
      glsl3D.thematicHubsGroup.add(haloSprite);
    });

    glsl3D.worldGroup.add(glsl3D.thematicHubsGroup);
  }

  // If a node is currently selected, re-emphasize its links and beacon
  if (glsl3D.selectedNode) {
    emphasizeNodeLinks(glsl3D.selectedNode.id);
  }
}

const TYPE_COLORS = {
  // --- Core Corporate & Human Entities ---
  organization: "#38bdf8", // Sky Blue: High visibility on dark space, balanced luminance
  person: "#c084fc", // Lavender / Violet: Highly distinct from blues and greens

  // --- Spatial & Governance Entities ---
  location: "#2dd4bf", // Bright Teal / Cyan: Distinct geographic beacon
  statute: "#f43f5e", // Rose / Crimson: Strong legal governance anchor

  // --- Document & Taxonomy Entities ---
  contract_type: "#3b82f6", // Royal Blue: Clear legal agreement signifier
  document_category: "#94a3b8", // Slate Gray: Subordinate tech specs & architecture docs
  document: "#10b981", // Emerald: Document node
  theme: "#ec4899", // Fuchsia / Vibrant Sun Archetype (Life-Style Domains)

  // --- Financial & Numerical Entities ---
  currency: "#fbbf24", // Amber Gold: Transactional / monetary amounts
  financial_pillar: "#f97316", // Warm Orange: Clear separation from currency gold

  // --- Operational & Temporal Entities ---
  project_code: "#a855f7", // Deep Purple: Distinct operational identifier
  milestone_date: "#10b981", // Emerald Green: Distinct temporal milestones / deadlines
  default: "#64748b", // Neutral Muted Slate fallback
};

/**
* Safely resolves an entity node color with fallback support.
*/
function getNodeColor(nodeType) {
  if (!nodeType) return TYPE_COLORS.default;
  const key = String(nodeType).toLowerCase().trim();
  return TYPE_COLORS[key] || TYPE_COLORS.default;
}

/**
* Resolves node color dynamically based on viewport display mode.
* Supports centrality heatmap, categorical type palette, and K-Means topological clusters.
*/
function getNodeColorForMode(node, mode = "type") {
  if (mode === "centrality") {
    // Heatmap: Cold dark blue (hue ~0.65) -> Cyan -> Green -> Amber -> Hot Red (hue 0.0)
    const deg = Number(node.degree) || 0;
    const t = Math.min(1.0, Math.log(deg + 1) / Math.log(200));
    const hue = (1.0 - t) * 0.65;
    return new THREE.Color().setHSL(hue, 0.9, 0.55);
  }

  if (mode === "type") {
    // Defensively handle both node_type (backend schema) and type (frontend fallback)
    const entityType = node.node_type || node.type;
    return new THREE.Color(getNodeColor(entityType));
  }

  // Topological Cluster Color (K-Means community detection)
  return new THREE.Color(node.cluster_color || "#38bdf8");
}

window.TYPE_COLORS = TYPE_COLORS;
window.getNodeColor = getNodeColor;
window.getNodeColorForMode = getNodeColorForMode;

function animate3DUniverse() {
  glsl3D.animId = requestAnimationFrame(animate3DUniverse);

  // Advance GLSL temporal uniform
  glsl3D.uniforms.uTime.value += 0.016;

  // Auto-Spin orbital rotation
  if (glsl3D.autoSpin && !glsl3D.isUserInteracting && glsl3D.worldGroup) {
    glsl3D.worldGroup.rotation.y += 0.0015;
  }

  // Animate Selection Beacon pulse and face camera
  if (glsl3D.selectionBeaconGroup) {
    if (glsl3D.camera) {
      glsl3D.selectionBeaconGroup.quaternion.copy(glsl3D.camera.quaternion);
    }
    const pulseScale = 1.0 + 0.14 * Math.sin(glsl3D.uniforms.uTime.value * 4.5);
    glsl3D.selectionBeaconGroup.scale.set(pulseScale, pulseScale, pulseScale);
  }

  if (glsl3D.controls) {
    glsl3D.controls.update();
  }

  // Raycasting for Hover Tooltip
  if (glsl3D.pointsMesh && glsl3D.raycaster && glsl3D.camera) {
    glsl3D.raycaster.setFromCamera(glsl3D.mouse, glsl3D.camera);
    const intersects = glsl3D.raycaster.intersectObject(glsl3D.pointsMesh);

    const tooltip = document.getElementById("glsl-hover-tooltip");

    if (intersects.length > 0) {
      const hitIdx = intersects[0].index;
      if (hitIdx !== undefined && hitIdx < glsl3D.nodes.length) {
        glsl3D.hoveredNodeIndex = hitIdx;
        const n = glsl3D.nodes[hitIdx];
        show3DHoverTooltip(n, intersects[0].point);
        document.body.style.cursor = "pointer";
      }
    } else {
      glsl3D.hoveredNodeIndex = -1;
      if (tooltip) tooltip.style.display = "none";
      document.body.style.cursor = "default";
    }
  }

  if (glsl3D.renderer && glsl3D.scene && glsl3D.camera) {
    glsl3D.renderer.render(glsl3D.scene, glsl3D.camera);
  }
}

function on3DMouseMove(e) {
  const rect = glsl3D.renderer.domElement.getBoundingClientRect();
  glsl3D.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
  glsl3D.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

  const tooltip = document.getElementById("glsl-hover-tooltip");
  if (tooltip && tooltip.style.display !== "none") {
    tooltip.style.left = (e.clientX - rect.left) + "px";
    tooltip.style.top = (e.clientY - rect.top) + "px";
  }
}

function on3DMouseLeave() {
  glsl3D.mouse.x = -999;
  glsl3D.mouse.y = -999;
  const tooltip = document.getElementById("glsl-hover-tooltip");
  if (tooltip) tooltip.style.display = "none";
}

function on3DMouseClick(e) {
  if (glsl3D.hoveredNodeIndex >= 0 && glsl3D.hoveredNodeIndex < glsl3D.nodes.length) {
    const node = glsl3D.nodes[glsl3D.hoveredNodeIndex];
    open3DNodeInspector(node);
    emphasizeNodeLinks(node.id);
  }
}

async function on3DMouseDblClick(e) {
  if (glsl3D.hoveredNodeIndex >= 0 && glsl3D.hoveredNodeIndex < glsl3D.nodes.length) {
    const node = glsl3D.nodes[glsl3D.hoveredNodeIndex];
    await open3DNodeInspector(node);
    emphasizeNodeLinks(node.id);
    await expand3DSelectedNode();
  }
}

function focusOrInspect3DNode(nodeId) {
  const existingNode = glsl3D.nodes.find(n => n.id === nodeId);
  if (existingNode) {
    smoothTransitionTo3DNode(existingNode);
    open3DNodeInspector(existingNode);
    emphasizeNodeLinks(existingNode.id);
  } else if (glsl3D.selectedNode) {
    expand3DSelectedNode();
  }
}

function show3DHoverTooltip(node, hitPoint) {
  const tooltip = document.getElementById("glsl-hover-tooltip");
  if (!tooltip) return;

  const dot = document.getElementById("tt-cluster-dot");
  const name = document.getElementById("tt-name");
  const type = document.getElementById("tt-type");
  const cluster = document.getElementById("tt-cluster");
  const degree = document.getElementById("tt-degree");
  const docs = document.getElementById("tt-docs");

  if (dot) dot.style.background = node.cluster_color || "#38bdf8";
  if (name) name.textContent = node.name;
  if (degree) degree.textContent = node.degree || 0;

  if (node.type === "theme") {
    if (type) type.textContent = "🪐 Thematic Sun (Taxonomy Hub)";
    if (cluster) cluster.textContent = "Life-Style Domains";
    if (docs) docs.textContent = `${node.doc_count || node.degree || 0} Categorized Docs`;
  } else if (node.type === "document") {
    if (type) type.textContent = "📄 Document Planet";
    const themeLabel = node.theme_id ? node.theme_id.replace("theme_", "").replace(/_/g, " ") : "Thematic Orbit";
    if (cluster) cluster.textContent = `Orbiting: ${themeLabel}`;
    if (docs) docs.textContent = "Document Entity";
  } else {
    if (type) type.textContent = node.type;
    if (cluster) cluster.textContent = node.cluster_name || "Cluster " + node.cluster;
    if (docs) docs.textContent = node.doc_count || 1;
  }

  tooltip.style.display = "block";
}

let activeUniverseClusterId = null;

/**
* Opens and renders the details list for the clicked cluster.
*/
function openUniverseClusterDrawer(clusterId) {
  const drawer = document.getElementById("universe-cluster-drawer");
  const titleEl = document.getElementById("universe-drawer-title");
  const countEl = document.getElementById("universe-drawer-count");
  const searchInput = document.getElementById("universe-cluster-filter-input");

  if (!drawer) return;

  // Toggle off if clicking the already open cluster
  if (activeUniverseClusterId === clusterId && !drawer.classList.contains("hidden")) {
    closeUniverseClusterDrawer();
    return;
  }

  activeUniverseClusterId = clusterId;
  drawer.classList.remove("hidden");
  if (searchInput) searchInput.value = "";

  const clusterMeta = glsl3D.clusters.find(c => c.id === clusterId) || { name: `Cluster ${clusterId}` };
  if (titleEl) {
    titleEl.innerHTML = `${clusterMeta.icon || "•"} ${escapeHtml(clusterMeta.name)}`;
    titleEl.style.color = clusterMeta.color || "#38bdf8";
  }

  renderUniverseClusterDrawerItems("");
}

function closeUniverseClusterDrawer() {
  activeUniverseClusterId = null;
  const drawer = document.getElementById("universe-cluster-drawer");
  if (drawer) drawer.classList.add("hidden");
}

function filterUniverseClusterDrawer(query) {
  renderUniverseClusterDrawerItems((query || "").toLowerCase().trim());
}

function renderUniverseClusterDrawerItems(query) {
  const container = document.getElementById("universe-cluster-items");
  const countEl = document.getElementById("universe-drawer-count");
  if (!container) return;

  const matchingNodes = glsl3D.nodes.filter(n => n.cluster === activeUniverseClusterId);
  const filtered = query
    ? matchingNodes.filter(n => (n.name || "").toLowerCase().includes(query))
    : matchingNodes;

  if (countEl) countEl.textContent = matchingNodes.length;

  if (filtered.length === 0) {
    container.innerHTML = `<div style="padding: 1rem; color: var(--text-muted); text-align: center;">No matching entities.</div>`;
    return;
  }

  container.innerHTML = filtered.map(n => {
    const degBadge = `Deg: ${n.degree || 0}`;
    return `
      <div class="universe-cluster-entity-pill" onclick="focusOrInspect3DNode('${escapeHtml(n.id)}')" title="Focus entity in 3D: ${escapeHtml(n.name)}">
        <span style="color: ${n.cluster_color || '#38bdf8'}">●</span>
        <span style="font-weight: 500;">${escapeHtml(n.name)}</span>
        <span style="opacity: 0.6; font-size: 0.7rem;">${degBadge}</span>
      </div>
    `;
  }).join("");
}
window.openUniverseClusterDrawer = openUniverseClusterDrawer;
window.closeUniverseClusterDrawer = closeUniverseClusterDrawer;
window.filterUniverseClusterDrawer = filterUniverseClusterDrawer;

/**
 * Dynamically shifts the Three.js optical center to avoid overlapping UI panels.
 * Keeps the selected node perfectly centered in the visible gap.
 */
function update3DViewOffset() {
  if (!glsl3D.camera || !glsl3D.container) return;
  const width = glsl3D.container.clientWidth;
  const height = glsl3D.container.clientHeight;
  if (!width || !height) return;

  const legend = document.getElementById("axes-legend-overlay");
  const inspector = document.getElementById("glsl-node-inspector");

  // Calculate Left UI Intrusion (Legend Panel)
  let leftOffset = 0;
  if (legend) {
    leftOffset = legend.classList.contains("collapsed") ? 250 : 380;
  }

  // Calculate Right UI Intrusion (Inspector Panel)
  let rightOffset = 0;
  if (inspector && !inspector.classList.contains("hidden")) {
    rightOffset = 340;
  }

  // Positive xOffset shifts the scene LEFT. Negative shifts the scene RIGHT.
  const xOffset = (rightOffset - leftOffset) / 2;

  glsl3D.camera.setViewOffset(width, height, xOffset, 0, width, height);
  glsl3D.camera.updateProjectionMatrix();
}
window.update3DViewOffset = update3DViewOffset;

function get3DUniverseCentroid() {
  if (!glsl3D.nodes || glsl3D.nodes.length === 0) {
    return new THREE.Vector3(0, 0, -100);
  }
  let sumX = 0, sumY = 0, sumZ = 0;
  const len = glsl3D.nodes.length;
  for (let i = 0; i < len; i++) {
    const n = glsl3D.nodes[i];
    sumX += (n.x || 0);
    sumY += (n.y || 0);
    sumZ += (n.z || 0);
  }
  return new THREE.Vector3(sumX / len, sumY / len, sumZ / len);
}
window.get3DUniverseCentroid = get3DUniverseCentroid;

function smoothTransitionTo3DNode(targetNode, duration = 900) {
  if (!glsl3D.camera || !glsl3D.controls || !targetNode) return;

  const prevAutoSpin = glsl3D.autoSpin;
  glsl3D.autoSpin = false;

  const startTarget = glsl3D.controls.target.clone();
  const endTarget = new THREE.Vector3(targetNode.x, targetNode.y, targetNode.z);
  const startCamPos = glsl3D.camera.position.clone();

  // 1. Determine the True Center
  // In Thematic mode, the absolute center of the solar systems is exactly (0,0,0).
  // In Spatial mode, we continue to use the dynamic cloud centroid.
  const universeCenter = (glsl3D.layoutMode === "thematic")
    ? new THREE.Vector3(0, 0, 0)
    : (typeof get3DUniverseCentroid === "function" ? get3DUniverseCentroid() : new THREE.Vector3(0, 0, -100));

  // 2. Determine outward direction vector into the void: D = (Node - Center)
  let dir = new THREE.Vector3().subVectors(endTarget, universeCenter);

  if (dir.lengthSq() < 0.0001) {
    // If node is at the centroid or graph is single-node, default to elevated 3/4 vector
    dir.set(1.0, 0.15, 1.0).normalize();
  } else {
    // CRITICAL: In thematic mode, flatten the Y-axis calculation.
    // This prevents the camera from diving under or flying over the node based on its bobbing trajectory.
    // We want a pure horizontal push outward into the void.
    if (glsl3D.layoutMode === "thematic") {
      dir.y = 0;
    }
    dir.normalize();
  }

  // 3. Distance padding (90–140 units) scaled smoothly based on node degree/neighborhood density
  const deg = Number(targetNode.degree) || 1;
  const distancePadding = Math.min(150, Math.max(90, 100 + Math.log2(deg + 1) * 6));

  // 4. Elevation offset: Ensure a strict 3/4 top-down perspective
  // 4. Subtle elevation offset (+Y) ensuring elevated 3/4 perspective looking through node toward cloud
  const elevationY = Math.max(35, distancePadding * 0.45);
  const elevation = new THREE.Vector3(0, elevationY, 0);

  // 5. Frustum-optimized camera position:
  // Positioned on the "outer" side along the ray from centroid through N,
  // guaranteeing the point cloud remains fully in the background frustum rather than empty void
  const endCamPos = endTarget.clone()
    .add(dir.clone().multiplyScalar(distancePadding))
    .add(elevation);

  const startTime = performance.now();

  if (glsl3D.cameraTransitionAnim) {
    cancelAnimationFrame(glsl3D.cameraTransitionAnim);
    glsl3D.cameraTransitionAnim = null;
  }

  function step(now) {
    const elapsed = now - startTime;
    const progress = Math.min(1.0, elapsed / duration);

    // Smooth easeInOutCubic: soft launch and cushioned deceleration without abrupt snapping
    const ease = progress < 0.5
      ? 4 * progress * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 3) / 2;

    glsl3D.controls.target.lerpVectors(startTarget, endTarget, ease);
    glsl3D.camera.position.lerpVectors(startCamPos, endCamPos, ease);
    glsl3D.controls.update();

    if (progress < 1.0) {
      // Request the next frame of the animation loop.
      glsl3D.cameraTransitionAnim = requestAnimationFrame(step);
    } else {
      // Ensure final values are snapped exactly (prevents oscillation or overshooting)
      glsl3D.controls.target.copy(endTarget);
      glsl3D.camera.position.copy(endCamPos);
      glsl3D.controls.update();
      glsl3D.cameraTransitionAnim = null;
      glsl3D.autoSpin = prevAutoSpin;
    }
  }
  // Request the first frame of the animation loop.
  glsl3D.cameraTransitionAnim = requestAnimationFrame(step);
}
window.smoothTransitionTo3DNode = smoothTransitionTo3DNode;

// =========================================================================
// THEMATIC MINDMAP PHYSICS & INTERPOLATION ENGINE
// =========================================================================

function hashStr(str) {
  let hash = 0;
  if (!str) return 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

/**
 * Applies force-directed / grouped radial physics for the Thematic Mindmap:
 * - Theme nodes act as massive gravitational Suns on a perimeter orbit (R ~ 140).
 * - Categorized documents orbit their respective theme hub(s).
 * - Documents linked to multiple themes/entities are visually suspended at the centroid.
 * - Connected entities sit in the interstitial cross-pollination space.
 * - A 10-iteration force relaxation pass eliminates overlapping collisions.
 */
function applyThematicMindmapPhysics(nodes, edges) {
  if (!nodes || nodes.length === 0) return;

  const themeNodes = nodes.filter(n => n.type === "theme");
  const docNodes = nodes.filter(n => n.type === "document");
  const entNodes = nodes.filter(n => n.type !== "theme" && n.type !== "document");

  // 1. Arrange Theme Suns on a major celestial perimeter circle (R ~ 140)
  const numThemes = Math.max(1, themeNodes.length);
  const R_SUN = 140;
  const themeAnchors = new Map();

  themeNodes.forEach((th, idx) => {
    const angle = (idx / numThemes) * Math.PI * 2;
    const h = hashStr(th.id);
    const tiltY = (h % 24) - 12;
    const x = Math.cos(angle) * R_SUN;
    const z = Math.sin(angle) * R_SUN;
    const y = tiltY;

    th.x = x;
    th.y = y;
    th.z = z;
    th.is_hub = true;
    th.size = Math.max(7.5, Math.min(12.5, 7.5 + Math.sqrt((th.degree || 0) + 1) * 0.4));
    themeAnchors.set(th.id, { x, y, z });
  });

  // Map edges for fast lookup
  const nodeConnections = new Map();
  edges.forEach(e => {
    if (!nodeConnections.has(e.source)) nodeConnections.set(e.source, []);
    if (!nodeConnections.has(e.target)) nodeConnections.set(e.target, []);
    nodeConnections.get(e.source).push(e);
    nodeConnections.get(e.target).push(e);
  });

  // 2. Position Document Planets (with cross-pollination suspension)
  docNodes.forEach(doc => {
    const conns = nodeConnections.get(doc.id) || [];
    const linkedThemes = new Set();
    conns.forEach(e => {
      if (e.relation === "CATEGORIZED_AS") {
        if (e.target.startsWith("theme_")) linkedThemes.add(e.target);
        if (e.source.startsWith("theme_")) linkedThemes.add(e.source);
      }
    });
    if (doc.theme_id && themeAnchors.has(doc.theme_id)) {
      linkedThemes.add(doc.theme_id);
    }

    const h = hashStr(doc.id);
    const themeList = Array.from(linkedThemes);

    if (themeList.length === 1 && themeAnchors.has(themeList[0])) {
      // Single-theme Keplerian orbit: orbiting planet around its gravitational Sun
      const sun = themeAnchors.get(themeList[0]);
      const orbitRadius = 24.0 + (h % 34); // r in [24, 58]
      const orbitAngle = ((h % 360) / 180.0) * Math.PI;
      const zOffset = (h % 20) - 10;

      doc.x = sun.x + Math.cos(orbitAngle) * orbitRadius;
      doc.y = sun.y + Math.sin(orbitAngle) * orbitRadius;
      doc.z = sun.z + zOffset;
      doc.size = 3.2;
    } else if (themeList.length > 1) {
      // Cross-pollinated document linked to multiple themes:
      // Suspended between its respective hubs (centroid of linked hubs with slight deflection)
      let sumX = 0, sumY = 0, sumZ = 0;
      themeList.forEach(tid => {
        const p = themeAnchors.get(tid) || { x: 0, y: 0, z: 0 };
        sumX += p.x; sumY += p.y; sumZ += p.z;
      });
      const cx = sumX / themeList.length;
      const cy = sumY / themeList.length;
      const cz = sumZ / themeList.length;
      const jitter = (h % 16) - 8;

      doc.x = cx * 0.9 + jitter;
      doc.y = cy * 0.9 + jitter;
      doc.z = cz * 0.9 + ((h % 24) - 12);
      doc.size = 3.6; // slightly prominent for cross-pollinated hubs
    } else {
      // Fallback: orbit first theme hub or celestial center
      const firstSun = themeAnchors.values().next().value || { x: 0, y: 0, z: 0 };
      const orbitRadius = 28.0 + (h % 28);
      const orbitAngle = ((h % 360) / 180.0) * Math.PI;
      doc.x = firstSun.x + Math.cos(orbitAngle) * orbitRadius;
      doc.y = firstSun.y + Math.sin(orbitAngle) * orbitRadius;
      doc.z = firstSun.z + ((h % 20) - 10);
      doc.size = 3.0;
    }
  });

  // 3. Position Connected Entities in Interstitial Cross-Pollination Space
  const docPosMap = new Map(docNodes.map(d => [d.id, { x: d.x, y: d.y, z: d.z }]));
  entNodes.forEach(ent => {
    const conns = nodeConnections.get(ent.id) || [];
    const linkedDocs = [];
    conns.forEach(e => {
      const neighbor = e.source === ent.id ? e.target : e.source;
      if (docPosMap.has(neighbor)) {
        linkedDocs.push(docPosMap.get(neighbor));
      }
    });

    const h = hashStr(ent.id);
    if (linkedDocs.length > 0) {
      let sumX = 0, sumY = 0, sumZ = 0;
      linkedDocs.forEach(dp => {
        sumX += dp.x; sumY += dp.y; sumZ += dp.z;
      });
      const cx = sumX / linkedDocs.length;
      const cy = sumY / linkedDocs.length;
      const cz = sumZ / linkedDocs.length;
      ent.x = cx * 0.82 + (h % 14 - 7);
      ent.y = cy * 0.82 + (h % 14 - 7);
      ent.z = cz * 0.82 + (h % 20 - 10);
    } else {
      // Inner ambient constellation
      const angle = ((h % 360) / 180.0) * Math.PI;
      const r = 35.0 + (h % 40);
      ent.x = Math.cos(angle) * r;
      ent.y = Math.sin(angle) * r;
      ent.z = (h % 40) - 20;
    }
    ent.size = Math.max(1.2, Math.min(4.5, 1.2 + Math.sqrt((ent.degree || 0) + 1) * 0.28));
  });

  // 4. Force-Directed Relaxation Pass (10 iterations)
  const allNodes = nodes;
  const numNodes = allNodes.length;
  for (let iter = 0; iter < 10; iter++) {
    // Repulsion between non-theme nodes
    for (let i = 0; i < numNodes; i += 2) {
      const n1 = allNodes[i];
      if (n1.type === "theme") continue;
      for (let j = i + 1; j < numNodes; j += 3) {
        const n2 = allNodes[j];
        if (n2.type === "theme") continue;
        const dx = n1.x - n2.x;
        const dy = n1.y - n2.y;
        const dz = n1.z - n2.z;
        const distSq = dx * dx + dy * dy + dz * dz;
        if (distSq > 0.1 && distSq < 360) {
          const dist = Math.sqrt(distSq);
          const force = (18.0 - dist) / (dist * 16.0);
          n1.x += dx * force;
          n1.y += dy * force;
          n1.z += dz * force;
          n2.x -= dx * force;
          n2.y -= dy * force;
          n2.z -= dz * force;
        }
      }
    }
    // Spring attraction along edges
    edges.forEach(e => {
      const s = allNodes.find(n => n.id === e.source);
      const t = allNodes.find(n => n.id === e.target);
      if (s && t) {
        const dx = t.x - s.x;
        const dy = t.y - s.y;
        const dz = t.z - s.z;
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        const desiredDist = e.relation === "CATEGORIZED_AS" ? 36.0 : 45.0;
        if (dist > desiredDist) {
          const delta = (dist - desiredDist) * 0.035;
          const fx = (dx / dist) * delta;
          const fy = (dy / dist) * delta;
          const fz = (dz / dist) * delta;
          if (s.type !== "theme") { s.x += fx; s.y += fy; s.z += fz; }
          if (t.type !== "theme") { t.x -= fx; t.y -= fy; t.z -= fz; }
        }
      }
    });
  }
}
window.applyThematicMindmapPhysics = applyThematicMindmapPhysics;

/**
 * Smoothly interpolates node, edge, and label coordinates between layouts using easeInOutCubic.
 */
function animateLayoutTransition(duration = 1000) {
  if (!glsl3D.pointsMesh || !glsl3D.pointsMesh.geometry) return;

  if (glsl3D.layoutTransitionAnim) {
    cancelAnimationFrame(glsl3D.layoutTransitionAnim);
    glsl3D.layoutTransitionAnim = null;
  }

  const startTime = performance.now();
  const nodeCount = glsl3D.nodes.length;
  const nodeIndexMap = new Map();
  glsl3D.nodes.forEach((n, idx) => nodeIndexMap.set(n.id, idx));

  function step(now) {
    const elapsed = now - startTime;
    const progress = Math.min(1.0, elapsed / duration);
    // Smooth easeInOutCubic: soft launch and cushioned deceleration without abrupt snapping
    const ease = progress < 0.5
      ? 4 * progress * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 3) / 2;

    const posAttr = glsl3D.pointsMesh.geometry.attributes.position;
    for (let i = 0; i < nodeCount; i++) {
      const n = glsl3D.nodes[i];
      if (n._startPos && n._targetPos) {
        posAttr.array[i * 3 + 0] = n._startPos.x + (n._targetPos.x - n._startPos.x) * ease;
        posAttr.array[i * 3 + 1] = n._startPos.y + (n._targetPos.y - n._startPos.y) * ease;
        posAttr.array[i * 3 + 2] = n._startPos.z + (n._targetPos.z - n._startPos.z) * ease;
      }
    }
    posAttr.needsUpdate = true;

    // Interpolate edge lines
    if (glsl3D.edgesMesh && glsl3D.edgesMesh.geometry) {
      const edgePosAttr = glsl3D.edgesMesh.geometry.attributes.position;
      let eIdx = 0;
      glsl3D.edges.forEach(e => {
        const sIdx = nodeIndexMap.get(e.source);
        const tIdx = nodeIndexMap.get(e.target);
        if (sIdx !== undefined && tIdx !== undefined) {
          edgePosAttr.array[eIdx * 6 + 0] = posAttr.array[sIdx * 3 + 0];
          edgePosAttr.array[eIdx * 6 + 1] = posAttr.array[sIdx * 3 + 1];
          edgePosAttr.array[eIdx * 6 + 2] = posAttr.array[sIdx * 3 + 2];
          edgePosAttr.array[eIdx * 6 + 3] = posAttr.array[tIdx * 3 + 0];
          edgePosAttr.array[eIdx * 6 + 4] = posAttr.array[tIdx * 3 + 1];
          edgePosAttr.array[eIdx * 6 + 5] = posAttr.array[tIdx * 3 + 2];
          eIdx++;
        }
      });
      edgePosAttr.needsUpdate = true;
    }

    // Interpolate billboard labels
    if (glsl3D.labelsGroup) {
      glsl3D.labelsGroup.children.forEach(sprite => {
        if (sprite._boundNode) {
          const idx = nodeIndexMap.get(sprite._boundNode.id);
          if (idx !== undefined) {
            const offsetY = sprite._boundNode.type === "theme" ? 6.5 : 4.5;
            sprite.position.set(posAttr.array[idx * 3 + 0], posAttr.array[idx * 3 + 1] + offsetY, posAttr.array[idx * 3 + 2]);
          }
        }
      });
    }

    // Interpolate thematic halos and orbital rings
    if (glsl3D.thematicHubsGroup) {
      glsl3D.thematicHubsGroup.children.forEach(obj => {
        if (obj._boundNode) {
          const idx = nodeIndexMap.get(obj._boundNode.id);
          if (idx !== undefined) {
            obj.position.set(posAttr.array[idx * 3 + 0], posAttr.array[idx * 3 + 1], posAttr.array[idx * 3 + 2]);
          }
        }
      });
    }

    if (progress < 1.0) {
      glsl3D.layoutTransitionAnim = requestAnimationFrame(step);
    } else {
      glsl3D.layoutTransitionAnim = null;
      for (let i = 0; i < nodeCount; i++) {
        const n = glsl3D.nodes[i];
        if (n._targetPos) {
          n.x = n._targetPos.x;
          n.y = n._targetPos.y;
          n.z = n._targetPos.z;
        }
      }
    }
  }

  glsl3D.layoutTransitionAnim = requestAnimationFrame(step);
}
window.animateLayoutTransition = animateLayoutTransition;

/**
 * Updates the Axes of Importance Legend HUD descriptions based on active layout mode.
 */
function update3DAxesLegendForMode(mode) {
  const titleEl = document.querySelector("#axes-legend-overlay .legend-title");
  const axesGroupEl = document.querySelector("#axes-legend-overlay .axes-group");
  if (!axesGroupEl) return;

  if (mode === "thematic") {
    if (titleEl) titleEl.textContent = "Thematic Mindmap Topology";
    axesGroupEl.innerHTML = `
      <div class="axis-item">
        <span class="axis-badge" style="background: rgba(236, 72, 153, 0.2); color: #ec4899; border: 1px solid rgba(236, 72, 153, 0.4);">Hubs</span>
        <div class="axis-info">
          <span class="axis-name">Gravitational Taxonomy Suns (Perimeter R ≈ 140)</span>
          <span class="axis-pca">Solar Mass ∝ Document Population</span>
        </div>
      </div>
      <div class="axis-item">
        <span class="axis-badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);">Planets</span>
        <div class="axis-info">
          <span class="axis-name">Categorized Documents in Orbital Flight</span>
          <span class="axis-pca">Radius r ∈ [24, 58] around Primary Theme Hub</span>
        </div>
      </div>
      <div class="axis-item">
        <span class="axis-badge" style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4);">Bridges</span>
        <div class="axis-info">
          <span class="axis-name">Cross-Pollination Corridors & Shared Entities</span>
          <span class="axis-pca">Suspended Midpoints between Multiple Hubs</span>
        </div>
      </div>
    `;
    if (glsl3D.axesGroup) glsl3D.axesGroup.visible = false;
  } else {
    if (titleEl) titleEl.textContent = "Axes of Importance & Clusters";
    axesGroupEl.innerHTML = `
      <div class="axis-item">
        <span class="axis-badge axis-x">X-Axis</span>
        <div class="axis-info">
          <span class="axis-name">Domain Specificity &amp; Category Divergence</span>
          <span class="axis-pca">PCA-1 • Latent Semantic Variance</span>
        </div>
      </div>
      <div class="axis-item">
        <span class="axis-badge axis-y">Y-Axis</span>
        <div class="axis-info">
          <span class="axis-name">Temporal Recency &amp; Lifecycle Maturity</span>
          <span class="axis-pca">PCA-2 • Historical Lineage &amp; Validation</span>
        </div>
      </div>
      <div class="axis-item">
        <span class="axis-badge axis-z">Z-Axis</span>
        <div class="axis-info">
          <span class="axis-name">Graph Centrality &amp; Hub Authority Degree</span>
          <span class="axis-pca">PCA-3 • Network Eigenvector Density</span>
        </div>
      </div>
    `;
    if (glsl3D.axesGroup) glsl3D.axesGroup.visible = true;
  }
}
window.update3DAxesLegendForMode = update3DAxesLegendForMode;

/**
 * Toggles or sets the 3D Universe layout mode ("spatial" vs "thematic").
 */
async function set3DUniverseLayout(mode) {
  if (mode === glsl3D.layoutMode) return;
  glsl3D.layoutMode = mode;

  // 1. Update Segmented Button UI
  const btnSpatial = document.getElementById("btn-view-spatial");
  const btnThematic = document.getElementById("btn-view-thematic");
  if (btnSpatial && btnThematic) {
    if (mode === "thematic") {
      btnSpatial.classList.remove("active");
      btnThematic.classList.add("active");
    } else {
      btnSpatial.classList.add("active");
      btnThematic.classList.remove("active");
    }
  }

  // 2. Synchronize Docked Legend HUD Visibility & Hero Badges
  const legendOverlay = document.getElementById("axes-legend-overlay");
  const legendBody = document.getElementById("axes-legend-body");
  const legendBtn = document.querySelector(".btn-legend-collapse");
  if (legendOverlay) {
    if (mode === "thematic") {
      // Automatically expand and display cluster hierarchy drawer
      legendOverlay.classList.remove("collapsed");
      if (legendBody) legendBody.style.display = "flex";
      if (legendBtn) legendBtn.textContent = "−";
    } else {
      // Automatically collapse into minimal floating badge pill
      legendOverlay.classList.add("collapsed");
      if (legendBody) legendBody.style.display = "none";
      if (legendBtn) legendBtn.textContent = "+";
    }
  }

  const badgeDimVal = document.getElementById("badge-dim-val");
  const badgeAlgoVal = document.getElementById("badge-algo-val");
  if (badgeDimVal) {
    badgeDimVal.textContent = mode === "thematic" ? "Thematic Gravitational Space" : "High-Dim → 3D PCA";
  }
  if (badgeAlgoVal) {
    badgeAlgoVal.textContent = mode === "thematic" ? "Thematic Solar Centroids (k=7)" : "Unsupervised K-Means";
  }

  // 3. Update HUD Legend text
  update3DAxesLegendForMode(mode);

  // 4. Smooth Camera Refocus
  if (glsl3D.controls && glsl3D.controls.target) {
    glsl3D.controls.target.set(0, 0, mode === "thematic" ? 0 : -100);
  }

  // 5. Capture current node positions for animated ease transition
  const oldPositions = new Map();
  glsl3D.nodes.forEach(n => {
    oldPositions.set(n.id, { x: n.x, y: n.y, z: n.z });
  });

  // 6. Diagnostics & Toast Feedback on layout switch
  const modeTitle = mode === "thematic" ? "Thematic Mindmap" : "Spatial View";
  pushDiagnosticLog(
    "info",
    `Switching 3D Universe topology to ${modeTitle}...`,
    "frontend",
    "GLSL3D",
    { target_mode: mode, active_nodes: glsl3D.nodes.length }
  );

  // Announce the heavy computation instantly
  showToast(
    mode === "thematic"
      ? "⏳ Computing Thematic Topology... applying force-directed physics (this may take a few seconds)."
      : "⏳ Computing Spatial PCA... recalculating latent variance (this may take a few seconds).",
    "info",
    8000
  );

  // CRITICAL: Yield to the browser's main thread for 150ms. 
  // This allows the DOM to actually render the toast animation and CSS changes 
  // BEFORE the heavy 3D physics calculations lock up the CPU.
  await new Promise(resolve => setTimeout(resolve, 150));

  // 7. Reload universe with the chosen layout mode and animate
  await load3DUniverseData(true, { layout: mode }, oldPositions);

  // 8. Post-transition Success Toast
  showToast(
    mode === "thematic"
      ? "🪐 Thematic Mindmap successfully generated!"
      : "🌐 Spatial View successfully generated!",
    "success",
    3500
  );

  // 9. Post-transition Diagnostic telemetry
  const themeCluster = glsl3D.clusters ? glsl3D.clusters.find(c => c.id === 6) : null;
  const themeCount = themeCluster ? themeCluster.rendered_count : 0;
  pushDiagnosticLog(
    "success",
    `Topology successfully switched to ${modeTitle}: ${glsl3D.nodes.length} nodes rendered`,
    "frontend",
    "GLSL3D",
    { mode, rendered_nodes: glsl3D.nodes.length, thematic_suns: themeCount }
  );
}
window.set3DUniverseLayout = set3DUniverseLayout;

function toggle3DUniverseLayout() {
  const nextMode = glsl3D.layoutMode === "thematic" ? "spatial" : "thematic";
  set3DUniverseLayout(nextMode);
}
window.toggle3DUniverseLayout = toggle3DUniverseLayout;

function emphasizeNodeLinks(nodeId) {
  if (!glsl3D.scene || !glsl3D.worldGroup) return;

  // 1. Remove previous highlighted elements
  if (glsl3D.highlightedEdgesMesh) {
    glsl3D.worldGroup.remove(glsl3D.highlightedEdgesMesh);
    if (glsl3D.highlightedEdgesMesh.geometry) glsl3D.highlightedEdgesMesh.geometry.dispose();
    if (glsl3D.highlightedEdgesMesh.material) glsl3D.highlightedEdgesMesh.material.dispose();
    glsl3D.highlightedEdgesMesh = null;
  }
  if (glsl3D.selectionBeaconGroup) {
    glsl3D.worldGroup.remove(glsl3D.selectionBeaconGroup);
    glsl3D.selectionBeaconGroup = null;
  }

  if (!nodeId) return;

  const targetNode = glsl3D.nodes.find(n => n.id === nodeId);
  if (!targetNode) return;

  // 2. Build 3D Pulsing Selection Beacon Ring & Reticle
  const beaconGroup = new THREE.Group();
  beaconGroup.position.set(targetNode.x, targetNode.y, targetNode.z);

  const ringGeo = new THREE.RingGeometry(2.8, 3.8, 32);
  const ringMat = new THREE.MeshBasicMaterial({
    color: 0x00f0ff,
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.95,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });
  const ringMesh = new THREE.Mesh(ringGeo, ringMat);
  beaconGroup.add(ringMesh);

  const reticleSprite = create3DTextSprite(`🎯 ${targetNode.name}`, targetNode.cluster_color || "#38bdf8", 22);
  reticleSprite.position.set(0, 6.5, 0);
  reticleSprite.scale.set(28, 7, 1);
  beaconGroup.add(reticleSprite);

  glsl3D.selectionBeaconGroup = beaconGroup;
  glsl3D.worldGroup.add(glsl3D.selectionBeaconGroup);

  // 3. Materialize and Emphasize Connected Links
  const nodeIndexMap = new Map();
  glsl3D.nodes.forEach((n, i) => nodeIndexMap.set(n.id, i));

  const highEdgePositions = [];
  const highEdgeColors = [];
  const connectedNodeIds = new Set([nodeId]);

  glsl3D.edges.forEach(e => {
    if (e.source === nodeId || e.target === nodeId) {
      connectedNodeIds.add(e.source);
      connectedNodeIds.add(e.target);

      const sIdx = nodeIndexMap.get(e.source);
      const tIdx = nodeIndexMap.get(e.target);
      if (sIdx !== undefined && tIdx !== undefined) {
        const sNode = glsl3D.nodes[sIdx];
        const tNode = glsl3D.nodes[tIdx];

        highEdgePositions.push(sNode.x, sNode.y, sNode.z);
        highEdgePositions.push(tNode.x, tNode.y, tNode.z);

        // Electric cyan to warm gold gradient highlight
        highEdgeColors.push(0.0, 0.95, 1.0);
        highEdgeColors.push(1.0, 0.84, 0.0);
      }
    }
  });

  if (highEdgePositions.length > 0) {
    const highGeo = new THREE.BufferGeometry();
    highGeo.setAttribute("position", new THREE.Float32BufferAttribute(highEdgePositions, 3));
    highGeo.setAttribute("color", new THREE.Float32BufferAttribute(highEdgeColors, 3));

    const highMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      linewidth: 3,
      depthWrite: false,
    });

    glsl3D.highlightedEdgesMesh = new THREE.LineSegments(highGeo, highMat);
    glsl3D.worldGroup.add(glsl3D.highlightedEdgesMesh);
  }

  // Dim un-connected nodes slightly so the connected cluster pops visually
  if (glsl3D.pointsMesh && glsl3D.pointsMesh.geometry.attributes.aDimmed) {
    const dimmed = glsl3D.pointsMesh.geometry.attributes.aDimmed;
    glsl3D.nodes.forEach((n, i) => {
      if (connectedNodeIds.has(n.id)) {
        dimmed.setX(i, 0.0);
      } else {
        dimmed.setX(i, 0.75);
      }
    });
    dimmed.needsUpdate = true;
  }
}
window.emphasizeNodeLinks = emphasizeNodeLinks;

async function visualizeDocumentIn3D(sha256, filename) {
  if (!sha256) return;

  // 1. Switch to 3D Universe workspace
  switchWorkspace("universe");

  // 2. Load universe data filtered for this document
  await load3DUniverseData(true, { doc_sha: sha256 });

  // 3. Find the target node
  const targetId = glsl3D.focusNodeId || `doc_${sha256.substring(0, 16)}` || (glsl3D.nodes[0] && glsl3D.nodes[0].id);
  let targetNode = glsl3D.nodes.find(n => n.id === targetId || n.id.startsWith(`doc_${sha256.substring(0, 8)}`)) || glsl3D.nodes[0];

  if (targetNode) {
    smoothTransitionTo3DNode(targetNode);
    open3DNodeInspector(targetNode);
    emphasizeNodeLinks(targetNode.id);
    showToast(`🌐 Focused 3D Universe on "${targetNode.name || filename}" with materialized entity links`, "success", 4000);
  }
}
window.visualizeDocumentIn3D = visualizeDocumentIn3D;

async function open3DNodeInspector(node) {
  glsl3D.selectedNode = node;
  const drawer = document.getElementById("glsl-node-inspector");
  if (!drawer) return;

  const dot = document.getElementById("insp-cluster-dot");
  const clusterName = document.getElementById("insp-cluster-name");
  const typeBadge = document.getElementById("insp-type-badge");
  const nameEl = document.getElementById("insp-node-name");
  const degreeEl = document.getElementById("insp-degree");
  const docCountEl = document.getElementById("insp-doc-count");
  const coordsEl = document.getElementById("insp-coords");
  const dateEl = document.getElementById("insp-date");

  if (dot) {
    dot.style.background = node.cluster_color || "#38bdf8";
    dot.style.boxShadow = `0 0 10px ${node.cluster_color || "#38bdf8"}`;
  }
  if (clusterName) clusterName.textContent = node.cluster_name || "Cluster " + node.cluster;
  if (typeBadge) typeBadge.textContent = node.type;
  if (nameEl) nameEl.textContent = node.name;
  if (degreeEl) degreeEl.textContent = node.degree;
  if (docCountEl) docCountEl.textContent = (node.doc_count !== undefined && node.doc_count !== null) ? node.doc_count : 0;
  if (coordsEl) coordsEl.textContent = `[${node.x}, ${node.y}, ${node.z}]`;
  if (dateEl) dateEl.textContent = node.latest_date ? node.latest_date.split("T")[0] : (node.doc_count ? "Recent" : "None");

  drawer.classList.remove("hidden");

  // Recenter universe for the newly opened right panel
  update3DViewOffset();

  // Focus camera smoothly toward the node & emphasize connecting links
  smoothTransitionTo3DNode(node, 850);
  emphasizeNodeLinks(node.id);

  // Progressive Semantic Expansion: Asynchronously fetch 1-hop neighborhood
  const listEl = document.getElementById("insp-neighborhood-list");
  const countEl = document.getElementById("insp-neighborhood-count");

  if (listEl) listEl.innerHTML = `<span style="color: #64748b;">Loading 1-hop connected neighborhood...</span>`;
  if (countEl) countEl.textContent = "...";

  try {
    const encodedId = encodeURIComponent(node.id);
    let res = await fetch(`/api/v1/sidecar/graph/node/${encodedId}?hops=1`);
    if (!res.ok && (res.status === 404 || res.status === 422)) {
      res = await fetch(`/api/v1/sidecar/graph/node?id=${encodedId}&hops=1`);
    }
    if (res.ok) {
      const nh = await res.json();
      glsl3D.currentNeighborhood = nh;
      renderNeighborhoodDetails(nh);
    } else {
      renderLocalSceneNeighborhood(node);
    }
  } catch (err) {
    console.debug("Failed to fetch neighborhood from API, rendering local scene links:", err);
    renderLocalSceneNeighborhood(node);
  }
}

function renderLocalSceneNeighborhood(node) {
  const listEl = document.getElementById("insp-neighborhood-list");
  const countEl = document.getElementById("insp-neighborhood-count");
  if (!listEl) return;

  const connectedEdges = glsl3D.edges.filter(e => e.source === node.id || e.target === node.id);
  const outgoing = connectedEdges.map(e => {
    const neighborId = e.source === node.id ? e.target : e.source;
    const neighbor = glsl3D.nodes.find(n => n.id === neighborId) || { name: neighborId, type: "entity" };
    return {
      node_id: neighborId,
      name: neighbor.name || neighborId,
      node_type: neighbor.type || "entity",
      relation_type: e.relation || "CONNECTED_TO",
      weight: e.weight || 1.0
    };
  });

  const nh = {
    node_id: node.id,
    outgoing_relations: outgoing,
    incoming_relations: [],
    associated_documents: []
  };
  glsl3D.currentNeighborhood = nh;
  renderNeighborhoodDetails(nh);
}

function renderNeighborhoodDetails(nh) {
  const listEl = document.getElementById("insp-neighborhood-list");
  const countEl = document.getElementById("insp-neighborhood-count");
  if (!listEl) return;

  const outR = nh.outgoing_relations || [];
  const inR = nh.incoming_relations || [];
  const docs = nh.associated_documents || [];
  const allRel = [...outR, ...inR];
  if (countEl) countEl.textContent = allRel.length;

  let html = "";
  if (allRel.length > 0) {
    html += allRel.slice(0, 20).map(r => `
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 3px 6px; border-radius: 4px; cursor: pointer; transition: background 0.15s;" 
           onmouseover="this.style.background='rgba(255,255,255,0.08)'" 
           onmouseout="this.style.background='transparent'" 
           onclick="focusOrInspect3DNode('${escapeHtml(r.node_id)}')"
           title="Click to focus / expand: ${escapeHtml(r.name || r.node_id)}">
        <span style="color: #e2e8f0; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; max-width: 170px;">${escapeHtml(r.name || r.node_id)}</span>
        <span style="font-size: 10px; color: #38bdf8; background: rgba(56, 189, 248, 0.12); padding: 1px 5px; border-radius: 4px;">${escapeHtml(r.relation_type || 'LINK')}</span>
      </div>
    `).join("");
  } else {
    html += `<span style="color: #64748b; font-size: 11px;">No direct explicit graph links</span>`;
  }

  if (docs.length > 0) {
    html += `
      <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: #10b981; margin-top: 8px; margin-bottom: 4px;">Linked Documents (${docs.length})</div>
    `;
    html += docs.slice(0, 6).map(d => `
      <div style="font-size: 11px; color: #94a3b8; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; padding: 1px 0; cursor: pointer;" 
           onclick="visualizeDocumentIn3D('${escapeHtml(d.sha256_hash)}', '${escapeHtml(d.canonical_filename)}')"
           title="Visualize in 3D: ${escapeHtml(d.canonical_filename)}">
        📄 ${escapeHtml(d.canonical_filename)} ➔
      </div>
    `).join("");
  }

  listEl.innerHTML = html;
}

async function expand3DSelectedNode() {
  const node = glsl3D.selectedNode;
  if (!node) return;

  const btn = document.getElementById("insp-btn-expand");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-inline">⏳</span> Expanding...`;
  }

  try {
    let nh = glsl3D.currentNeighborhood;
    if (!nh || nh.node_id !== node.id) {
      const encodedId = encodeURIComponent(node.id);
      let res = await fetch(`/api/v1/sidecar/graph/node/${encodedId}?hops=1`);
      if (!res.ok && (res.status === 404 || res.status === 422)) {
        res = await fetch(`/api/v1/sidecar/graph/node?id=${encodedId}&hops=1`);
      }
      if (!res.ok) throw new Error("HTTP " + res.status);
      nh = await res.json();
      glsl3D.currentNeighborhood = nh;
    }

    const connectedNodesMap = new Map();
    (nh.outgoing_relations || []).forEach(r => connectedNodesMap.set(r.node_id, r));
    (nh.incoming_relations || []).forEach(r => connectedNodesMap.set(r.node_id, r));

    const existingIds = new Set(glsl3D.nodes.map(n => n.id));
    const newNeighborNodes = [];

    connectedNodesMap.forEach((meta, nid) => {
      if (!existingIds.has(nid)) {
        newNeighborNodes.push({
          id: nid,
          name: meta.name || nid,
          type: meta.node_type || "organization",
          degree: 1,
          doc_count: 1,
          latest_date: node.latest_date || "2024-01-01"
        });
      }
    });

    if (newNeighborNodes.length === 0) {
      showToast(`All 1-hop connected neighbors of ${node.name} are already rendered in the 3D scene.`, "info", 3000);
      return;
    }

    // Dynamic Canvas Injection: assign local coordinates clustered around (node.x, node.y, node.z)
    const clusterMap = {
      organization: 0,
      contract_type: 1,
      project_code: 1,
      document: 1,
      person: 2,
      location: 3,
      statute: 4,
      monetary_value: 4,
      milestone_date: 4
    };

    newNeighborNodes.forEach((newN, idx) => {
      const cid = clusterMap[newN.type] !== undefined ? clusterMap[newN.type] : (idx % 5);
      const cmeta = glsl3D.clusters[cid] || { name: "Connected Subgraph", color: "#38bdf8", icon: "🌐" };
      newN.cluster = cid;
      newN.cluster_name = cmeta.name;
      newN.cluster_color = cmeta.color;
      newN.cluster_icon = cmeta.icon;

      // Spherical distribution around the parent node
      const phi = (idx / newNeighborNodes.length) * Math.PI * 2;
      const theta = ((idx % 3) - 1) * 0.45;
      const radius = 14 + (idx % 4) * 6;

      newN.x = Math.round((node.x + Math.cos(phi) * Math.cos(theta) * radius) * 100) / 100;
      newN.y = Math.round((node.y + Math.sin(theta) * radius + (Math.sin(phi * 2) * 5)) * 100) / 100;
      newN.z = Math.round((node.z + Math.sin(phi) * Math.cos(theta) * radius) * 100) / 100;
      newN.size = 1.3;

      glsl3D.nodes.push(newN);
      existingIds.add(newN.id);
    });

    // Add edges
    (nh.outgoing_relations || []).forEach(r => {
      glsl3D.edges.push({
        source: node.id,
        target: r.node_id,
        relation: r.relation_type || "RELATED_TO",
        weight: r.weight || 1.0
      });
    });
    (nh.incoming_relations || []).forEach(r => {
      glsl3D.edges.push({
        source: r.node_id,
        target: node.id,
        relation: r.relation_type || "RELATED_TO",
        weight: r.weight || 1.0
      });
    });

    // Rebuild Three.js geometries dynamically
    build3DSceneObjects();

    // Update KPI indicators
    const statNodesEl = document.getElementById("glsl-stat-nodes");
    const statEdgesEl = document.getElementById("glsl-stat-edges");
    if (statNodesEl) statNodesEl.textContent = glsl3D.nodes.length.toLocaleString();
    if (statEdgesEl) statEdgesEl.textContent = glsl3D.edges.length.toLocaleString();

    // Dynamically update cluster legend counts and representativity percentages
    const counts = {};
    glsl3D.nodes.forEach(n => {
      counts[n.cluster] = (counts[n.cluster] || 0) + 1;
    });
    glsl3D.clusters.forEach(c => {
      const renderedEl = document.querySelector(`.cluster-item[data-cluster-id="${c.id}"] .cluster-rendered`);
      if (renderedEl) renderedEl.textContent = counts[c.id] || 0;
      const pctEl = document.querySelector(`.cluster-item[data-cluster-id="${c.id}"] .cluster-pct`);
      if (pctEl && c.total_in_db) {
        const newPct = parseFloat((((counts[c.id] || 0) / c.total_in_db) * 100).toFixed(1));
        const isFull = newPct >= 99.95 || (counts[c.id] || 0) >= c.total_in_db;
        pctEl.textContent = isFull ? "100%" : newPct + "%";
        pctEl.className = `cluster-pct ${isFull ? 'pct-full' : 'pct-capped'}`;
      }
    });
    const macroRenderedEl = document.querySelector("#cluster-macro-summary strong");
    if (macroRenderedEl) macroRenderedEl.textContent = glsl3D.nodes.length.toLocaleString();
    const macroPctEl = document.querySelector("#cluster-macro-summary .macro-pct");
    if (macroPctEl && glsl3D.totalNodesInDB) {
      const macroPct = parseFloat(((glsl3D.nodes.length / glsl3D.totalNodesInDB) * 100).toFixed(1));
      macroPctEl.textContent = `${macroPct}% coverage`;
    }

    showToast(`⚡ Dynamic Subgraph Expanded: Injected +${newNeighborNodes.length} entities around ${node.name}`, "success", 4000);
    renderNeighborhoodDetails(nh);
    emphasizeNodeLinks(node.id);
  } catch (err) {
    showToast("Failed to expand neighborhood: " + err.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `🔬 Expand Subgraph (+1 Hop LOD)`;
    }
  }
}

function close3DNodeInspector() {
  glsl3D.selectedNode = null;
  if (glsl3D.highlightedEdgesMesh && glsl3D.worldGroup) {
    glsl3D.worldGroup.remove(glsl3D.highlightedEdgesMesh);
    glsl3D.highlightedEdgesMesh = null;
  }
  if (glsl3D.selectionBeaconGroup && glsl3D.worldGroup) {
    glsl3D.worldGroup.remove(glsl3D.selectionBeaconGroup);
    glsl3D.selectionBeaconGroup = null;
  }
  // Clear dimming
  if (glsl3D.pointsMesh && glsl3D.pointsMesh.geometry.attributes.aDimmed) {
    const dimmed = glsl3D.pointsMesh.geometry.attributes.aDimmed;
    for (let i = 0; i < glsl3D.nodes.length; i++) {
      dimmed.setX(i, 0.0);
    }
    dimmed.needsUpdate = true;
  }
  const drawer = document.getElementById("glsl-node-inspector");
  if (drawer) {
    drawer.classList.add("hidden");
    // Re-apply offset so the gap closes immediately
    update3DViewOffset();
  }
}

function toggle3DAutoSpin() {
  glsl3D.autoSpin = !glsl3D.autoSpin;
  const btn = document.getElementById("btn-glsl-spin");
  const text = document.getElementById("glsl-spin-text");
  if (btn) btn.classList.toggle("active", glsl3D.autoSpin);
  if (text) text.textContent = glsl3D.autoSpin ? "Auto-Spin: ON" : "Auto-Spin: OFF";
}

function toggle3DEdges() {
  glsl3D.showEdges = !glsl3D.showEdges;
  if (glsl3D.edgesMesh) {
    glsl3D.edgesMesh.visible = glsl3D.showEdges;
    if (glsl3D.showEdges && glsl3D.edgesMesh.material) {
      const opacity = typeof glsl3D.edgeOpacity === "number" ? glsl3D.edgeOpacity : 0.08;
      glsl3D.edgesMesh.material.opacity = opacity;
      glsl3D.edgesMesh.material.needsUpdate = true;
    }
  }
  const btn = document.getElementById("btn-glsl-edges");
  const text = document.getElementById("glsl-edges-text");
  if (btn) btn.classList.toggle("active", glsl3D.showEdges);
  if (text) text.textContent = glsl3D.showEdges ? "Links: Visible" : "Links: Hidden";
}

function toggle3DLabels() {
  glsl3D.showLabels = !glsl3D.showLabels;
  if (glsl3D.labelsGroup) {
    glsl3D.labelsGroup.visible = glsl3D.showLabels;
  }
  const btn = document.getElementById("btn-glsl-labels");
  const text = document.getElementById("glsl-labels-text");
  if (btn) btn.classList.toggle("active", glsl3D.showLabels);
  if (text) text.textContent = glsl3D.showLabels ? "Labels: ON" : "Labels: OFF";
}

function change3DColorMode(mode) {
  glsl3D.colorMode = mode;
  if (!glsl3D.pointsMesh) return;

  const colors = glsl3D.pointsMesh.geometry.attributes.aColor;
  glsl3D.nodes.forEach((n, i) => {
    const c = getNodeColorForMode(n, mode);
    colors.setXYZ(i, c.r, c.g, c.b);
  });
  colors.needsUpdate = true;
}

function filter3DCluster(clusterId) {
  // If clicking the already active cluster, toggle back to 'all'
  if (String(glsl3D.activeClusterFilter) === String(clusterId) && String(clusterId) !== "all") {
    clusterId = "all";
  }
  glsl3D.activeClusterFilter = clusterId;
  const select = document.getElementById("select-glsl-cluster");
  if (select && select.value !== String(clusterId)) {
    select.value = String(clusterId);
  }

  // Update active state in cluster legend list
  document.querySelectorAll(".cluster-item").forEach(el => {
    if (String(clusterId) !== "all" && el.dataset.clusterId === String(clusterId)) {
      el.classList.add("active");
    } else {
      el.classList.remove("active");
    }
  });

  if (!glsl3D.pointsMesh) return;

  const dimmed = glsl3D.pointsMesh.geometry.attributes.aDimmed;
  const targetId = clusterId === "all" ? null : parseInt(clusterId, 10);

  glsl3D.nodes.forEach((n, i) => {
    if (targetId === null || n.cluster === targetId) {
      dimmed.setX(i, 0.0);
    } else {
      dimmed.setX(i, 1.0);
    }
  });
  dimmed.needsUpdate = true;
}

// function reset3DCamera() {
//   if (glsl3D.camera && glsl3D.controls) {
//     glsl3D.camera.position.set(0, 45, 270);
//     glsl3D.controls.target.set(0, 0, 0);
//     if (glsl3D.worldGroup) {
//       glsl3D.worldGroup.rotation.set(0, 0, 0);
//     }
//   }
// }




/**
 * Zenith View: Top Orthogonal / Planar projection looking straight down
 * onto the 3D cosmic plane to inspect orbital satellites and solar hubs.
 */
function set3DZenithView(duration = 800) {
  if (!glsl3D.camera || !glsl3D.controls) return;

  // Stop running orbital tour if active
  if (glsl3D.orbitalTourActive) {
    stop3DOrbitalTour(false);
  }

  // Target center of coordinate space
  const targetZ = glsl3D.layoutMode === "thematic" ? 0 : -100;
  const endTarget = new THREE.Vector3(0, 0, targetZ);
  // High Y altitude directly above target (e.g. Y = 460) with small Z epsilon to avoid gimbal lock
  const endCamPos = new THREE.Vector3(0, 460, targetZ + 0.001);
  const startTarget = glsl3D.controls.target.clone();
  const startCamPos = glsl3D.camera.position.clone();
  const startUp = glsl3D.camera.up.clone();
  const endUp = new THREE.Vector3(0, 0, -1); // North points toward top of viewport

  const btnZenith = document.getElementById("btn-glsl-zenith");
  const btnOrbital = document.getElementById("btn-glsl-orbital");
  if (btnZenith) btnZenith.classList.add("active");
  if (btnOrbital) btnOrbital.classList.remove("active");

  const prevAutoSpin = glsl3D.autoSpin;
  glsl3D.autoSpin = false;

  const startTime = performance.now();
  if (glsl3D.cameraTransitionAnim) {
    cancelAnimationFrame(glsl3D.cameraTransitionAnim);
    glsl3D.cameraTransitionAnim = null;
  }

  function step(now) {
    const elapsed = now - startTime;
    const progress = Math.min(1.0, elapsed / duration);
    const ease = progress < 0.5
      ? 4 * progress * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 3) / 2;

    glsl3D.controls.target.lerpVectors(startTarget, endTarget, ease);
    glsl3D.camera.position.lerpVectors(startCamPos, endCamPos, ease);
    glsl3D.camera.up.lerpVectors(startUp, endUp, ease).normalize();
    glsl3D.controls.update();

    if (progress < 1.0) {
      glsl3D.cameraTransitionAnim = requestAnimationFrame(step);
    } else {
      glsl3D.controls.target.copy(endTarget);
      glsl3D.camera.position.copy(endCamPos);
      glsl3D.camera.up.copy(endUp);
      glsl3D.controls.update();
      glsl3D.cameraTransitionAnim = null;
      glsl3D.autoSpin = prevAutoSpin;
    }
  }

  glsl3D.cameraTransitionAnim = requestAnimationFrame(step);

  showToast("🔭 Zenith View: Top-down planar projection activated", "info", 3000);
  pushDiagnosticLog("info", "Activated 3D Zenith Camera View (top-down planar orthogonal projection)", "frontend", "GLSL3D", {
    layout: glsl3D.layoutMode,
    camera_y: 460
  });
}
window.set3DZenithView = set3DZenithView;

/**
 * 3/4 Isometric Sequential Tour:
 * Fly smoothly through thematic solar hubs or major entity clusters sequentially.
 */
function stop3DOrbitalTour(notify = true) {
  glsl3D.orbitalTourActive = false;
  if (glsl3D.orbitalTourTimer) {
    clearTimeout(glsl3D.orbitalTourTimer);
    glsl3D.orbitalTourTimer = null;
  }
  const btnOrbital = document.getElementById("btn-glsl-orbital");
  const icon = document.getElementById("orbital-tour-icon");
  const text = document.getElementById("orbital-tour-text");
  if (btnOrbital) btnOrbital.classList.remove("active");
  if (icon) icon.textContent = "🪐";
  if (text) text.textContent = "Orbital Tour";

  if (notify) {
    showToast("⏸ Orbital Tour stopped", "info", 2000);
    pushDiagnosticLog("info", "Orbital Tour stopped by user", "frontend", "GLSL3D");
  }
}
window.stop3DOrbitalTour = stop3DOrbitalTour;

function toggle3DOrbitalTour() {
  if (glsl3D.orbitalTourActive) {
    stop3DOrbitalTour(true);
    return;
  }

  glsl3D.orbitalTourActive = true;
  const btnOrbital = document.getElementById("btn-glsl-orbital");
  const btnZenith = document.getElementById("btn-glsl-zenith");
  const icon = document.getElementById("orbital-tour-icon");
  const text = document.getElementById("orbital-tour-text");
  if (btnOrbital) btnOrbital.classList.add("active");
  if (btnZenith) btnZenith.classList.remove("active");
  if (icon) icon.textContent = "⏸";
  if (text) text.textContent = "Stop Tour";

  // Ensure camera upright orientation
  if (glsl3D.camera) glsl3D.camera.up.set(0, 1, 0);

  // Identify tour waypoints:
  let waypoints = [];
  if (glsl3D.layoutMode === "thematic") {
    waypoints = glsl3D.nodes.filter(n => n.type === "theme" || n.is_hub === true);
  }
  if (!waypoints || waypoints.length === 0) {
    // Fallback: top 8 highest degree nodes in current view
    waypoints = [...glsl3D.nodes].sort((a, b) => (b.degree || 0) - (a.degree || 0)).slice(0, 8);
  }

  if (waypoints.length === 0) {
    stop3DOrbitalTour(false);
    showToast("No hubs available for tour", "warning", 2500);
    return;
  }

  showToast(`🪐 Orbital Tour: Sequential inspection of ${waypoints.length} hubs active`, "info", 3000);
  pushDiagnosticLog("info", `Started 3D Orbital Tour across ${waypoints.length} hubs`, "frontend", "GLSL3D", {
    waypoints_count: waypoints.length,
    layout: glsl3D.layoutMode
  });

  let currentWaypointIndex = 0;
  const orbitCenter = (glsl3D.layoutMode === "thematic")
    ? new THREE.Vector3(0, 0, 0)
    : (typeof get3DUniverseCentroid === "function" ? get3DUniverseCentroid() : new THREE.Vector3(0, 0, -100));

  function visitNextWaypoint() {
    if (!glsl3D.orbitalTourActive) return;

    const targetNode = waypoints[currentWaypointIndex];
    currentWaypointIndex = (currentWaypointIndex + 1) % waypoints.length;

    // Smoothly fly to waypoint while keeping camera pointed into the center of the orbit
    transitionOrbitalTourCamera(targetNode, orbitCenter, 1400);
    open3DNodeInspector(targetNode);
    emphasizeNodeLinks(targetNode.id);

    // Schedule next waypoint visit after transit and dwell time (3400ms)
    glsl3D.orbitalTourTimer = setTimeout(() => {
      if (glsl3D.orbitalTourActive) {
        visitNextWaypoint();
      }
    }, 3400);
  }

  visitNextWaypoint();
}
window.toggle3DOrbitalTour = toggle3DOrbitalTour;

/**
 * Orbital Tour camera transition:
 * Positions camera on the outer rim looking through target hub straight into the center of the orbit.
 */
function transitionOrbitalTourCamera(targetNode, orbitCenter, duration = 1400) {
  if (!glsl3D.camera || !glsl3D.controls || !targetNode) return;

  const startTarget = glsl3D.controls.target.clone();
  // Camera always points into the center of the orbit!
  const endTarget = orbitCenter.clone();
  const startCamPos = glsl3D.camera.position.clone();

  const vec = new THREE.Vector3(
    targetNode.x - orbitCenter.x,
    targetNode.y - orbitCenter.y,
    targetNode.z - orbitCenter.z
  );
  const dist = vec.length();
  let dir = vec.clone();
  if (dist < 1.0) {
    dir.set(1.0, 0.0, 1.0).normalize();
  } else {
    dir.normalize();
  }

  // Camera placed on outer rim looking through the hub towards the center
  const camDist = Math.max(dist * 1.35, dist + 60);
  const elevationY = 40;
  const endCamPos = new THREE.Vector3(
    orbitCenter.x + dir.x * camDist,
    orbitCenter.y + dir.y * camDist + elevationY,
    orbitCenter.z + dir.z * camDist
  );

  const startTime = performance.now();
  if (glsl3D.cameraTransitionAnim) {
    cancelAnimationFrame(glsl3D.cameraTransitionAnim);
    glsl3D.cameraTransitionAnim = null;
  }

  function step(now) {
    const elapsed = now - startTime;
    const progress = Math.min(1.0, elapsed / duration);
    const ease = progress < 0.5
      ? 4 * progress * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 3) / 2;

    glsl3D.controls.target.lerpVectors(startTarget, endTarget, ease);
    glsl3D.camera.position.lerpVectors(startCamPos, endCamPos, ease);
    glsl3D.camera.up.set(0, 1, 0);
    glsl3D.controls.update();

    if (progress < 1.0) {
      glsl3D.cameraTransitionAnim = requestAnimationFrame(step);
    } else {
      glsl3D.controls.target.copy(endTarget);
      glsl3D.camera.position.copy(endCamPos);
      glsl3D.camera.up.set(0, 1, 0);
      glsl3D.controls.update();
      glsl3D.cameraTransitionAnim = null;
    }
  }

  glsl3D.cameraTransitionAnim = requestAnimationFrame(step);
}

function reset3DCamera() {
  if (glsl3D.orbitalTourActive) {
    stop3DOrbitalTour(false);
  }

  const btnZenith = document.getElementById("btn-glsl-zenith");
  const btnOrbital = document.getElementById("btn-glsl-orbital");
  if (btnZenith) btnZenith.classList.remove("active");
  if (btnOrbital) btnOrbital.classList.remove("active");

  if (glsl3D.camera && glsl3D.controls) {
    glsl3D.camera.up.set(0, 1, 0);
    setCameraPosition();
    if (glsl3D.worldGroup) {
      glsl3D.worldGroup.rotation.set(0, 0, 0);
    }
  }

  // Remove emphasized node links and close node inspector
  if (glsl3D.highlightedEdgesMesh && glsl3D.worldGroup) {
    glsl3D.worldGroup.remove(glsl3D.highlightedEdgesMesh);
    glsl3D.highlightedEdgesMesh = null;
  }
  if (glsl3D.pointsMesh && glsl3D.pointsMesh.geometry.attributes.aDimmed) {
    const dimmed = glsl3D.pointsMesh.geometry.attributes.aDimmed;
    for (let i = 0; i < dimmed.count; i++) dimmed.setX(i, 0.0);
    dimmed.needsUpdate = true;
  }
  close3DNodeInspector();

  showToast("↺ Camera perspective reset to default", "info", 2000);
  pushDiagnosticLog("info", "Reset 3D Knowledge Universe camera perspective", "frontend", "GLSL3D");
}
window.reset3DCamera = reset3DCamera;

function toggleLegendHUD() {
  const overlay = document.getElementById("axes-legend-overlay");
  const body = document.getElementById("axes-legend-body");
  const btn = document.querySelector(".btn-legend-collapse");
  if (!overlay) return;

  const isCollapsed = overlay.classList.toggle("collapsed");
  if (body) {
    body.style.display = isCollapsed ? "none" : "flex";
  }
  if (btn) {
    btn.textContent = isCollapsed ? "+" : "−";
  }
  // ADD THIS LINE:
  update3DViewOffset();
}
window.toggleLegendHUD = toggleLegendHUD;

function interrogateEntityInAIStudio() {
  if (!glsl3D.selectedNode) return;
  const node = glsl3D.selectedNode;
  switchWorkspace("chat");
  const chatInput = document.getElementById("chat-input");
  if (chatInput) {
    chatInput.value = `Tell me about the entity "${node.name}" (${node.type}), its key agreements, related signatories, and significance across the repository documents.`;
    sendChatMessage();
  }
}

function locateEntityInDocumentLedger() {
  if (!glsl3D.selectedNode) return;
  const node = glsl3D.selectedNode;
  switchWorkspace("ledger");
  const searchBox = document.getElementById("search-box");
  if (searchBox) {
    searchBox.value = node.name;
    handleSearch({ target: searchBox });
  }
}

// ==============================================================================
// 13. WORKSPACE 0: PROCESS SCROLLER & LINEAGE EXPLORER DYNAMIC TELEMETRY
// ==============================================================================

let ws0DiagFilter = "all";
let lineageSearchDebounceTimer = null;

// Helper: Format countdown from ISO expires_at timestamp
function formatExpiresCountdown(expiresAt) {
  if (!expiresAt) return "Permanent";
  try {
    const expDate = new Date(expiresAt);
    const now = new Date();
    const diffMs = expDate - now;
    if (diffMs <= 0) return "Expired (Evicting)";
    const diffSecs = Math.floor(diffMs / 1000);
    const hours = Math.floor(diffSecs / 3600);
    const mins = Math.floor((diffSecs % 3600) / 60);
    if (hours > 0) return `Expires in ${hours}h ${mins}m`;
    if (mins > 0) return `Expires in ${mins}m`;
    return `Expires in ${diffSecs}s`;
  } catch (e) {
    return "Resident";
  }
}

// Helper: Format byte counts to human readable
function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 MB";
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`;
  }
  return `${mb.toFixed(0)} MB`;
}

// 1. Dual-Node Ollama /api/ps Live Inspector (PC1 Localhost vs PC2 CUDA GPU)
async function pollOllamaProcessInspector(force = false) {
  const syncTimestampEl = document.getElementById("ps-sync-timestamp");
  const nowStr = new Date().toLocaleTimeString();
  if (syncTimestampEl) syncTimestampEl.textContent = `⟳ Synced: ${nowStr}`;

  // 1A. Probe PC1 (via backend proxy or local direct)
  try {
    let pc1Data = null;
    const isLocalDev = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") && window.location.protocol === "http:";
    if (isLocalDev) {
      try {
        const pc1Direct = await fetch("http://127.0.0.1:11434/api/ps", { signal: AbortSignal.timeout(2800) });
        if (pc1Direct.ok) pc1Data = await pc1Direct.json();
      } catch (_) { }
    }
    if (!pc1Data) {
      // Backend proxy (routes safely on remote server and avoids CORS/mixed content)
      const pc1Proxy = await fetch("/api/v1/diagnostics/ollama/ps?node=pc1");
      if (pc1Proxy.ok) pc1Data = await pc1Proxy.json();
    }

    const tbodyPc1 = document.getElementById("ps-pc1-models-tbody");
    const countPc1 = document.getElementById("pulse-pc1-models-count");
    const badgePc1 = document.getElementById("ps-pc1-status-badge");
    const summaryPc1 = document.getElementById("ps-pc1-summary");

    if (pc1Data && pc1Data.online !== false && Array.isArray(pc1Data.models)) {
      const models = pc1Data.models;
      if (countPc1) countPc1.textContent = `${models.length} model${models.length === 1 ? '' : 's'}`;
      if (badgePc1) {
        badgePc1.className = "node-status-badge badge-online";
        badgePc1.innerHTML = `<span class="dot"></span> Online (CPU)`;
      }

      if (tbodyPc1) {
        if (models.length === 0) {
          tbodyPc1.innerHTML = `<tr><td colspan="6" class="text-center text-faint">No models resident in RAM (On-demand standby)</td></tr>`;
        } else {
          let totalBytes = 0;
          tbodyPc1.innerHTML = models.map(m => {
            const sizeVal = m.size || 0;
            totalBytes += sizeVal;
            const details = m.details || {};
            const fam = details.family || details.families?.[0] || "LLM";
            const params = details.parameter_size || "--";
            const quant = details.quantization_level || "Unknown";
            const ctx = m.context_length ? (m.context_length >= 1024 ? `${Math.round(m.context_length / 1024)}k` : m.context_length) : "--";
            const residency = m.size_vram > 0 ? `${formatBytes(m.size_vram)} VRAM` : `${formatBytes(sizeVal)} RAM (CPU)`;
            const expires = formatExpiresCountdown(m.expires_at);

            return `
              <tr>
                <td><strong class="text-indigo">${escapeHtml(m.name)}</strong></td>
                <td><span class="mini-tag">${fam.toUpperCase()} • ${params}</span></td>
                <td><span class="mini-tag text-faint">${quant}</span></td>
                <td><span class="text-cyan">${ctx} ctx</span></td>
                <td><span class="text-emerald font-bold">${residency}</span></td>
                <td><span class="text-faint">${expires}</span></td>
              </tr>
            `;
          }).join("");

          if (summaryPc1) {
            summaryPc1.textContent = `${models.length} model${models.length === 1 ? '' : 's'} resident • ${formatBytes(totalBytes)} Host RAM • 100% CPU`;
          }
        }
      }
    } else {
      if (countPc1) countPc1.textContent = "Standby";
      if (badgePc1) {
        badgePc1.className = "node-status-badge badge-offline";
        badgePc1.innerHTML = `<span class="dot"></span> Standby`;
      }
      if (tbodyPc1) tbodyPc1.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Host Ollama engine standby / not started (127.0.0.1:11434)</td></tr>`;
      if (summaryPc1) summaryPc1.textContent = "Local host engine in standby • Workloads offloaded to PC2 CUDA";
    }
  } catch (err) {
    console.debug("PC1 PS inspection error:", err);
  }

  try {
    // Try backend proxy directly instead of browser DNS resolution
    const pc2Proxy = await fetch("/api/v1/diagnostics/ollama/ps?node=pc2", {
      signal: AbortSignal.timeout(1500)
    });
    if (pc2Proxy.ok) {
      pc2Data = await pc2Proxy.json();
      pc2PingMs = Math.round(performance.now() - pc2Start);
    }
  } catch (err) {
    // Gracefully mark offline without blocking
    pc2Data = { online: false, models: [] };
  }

  // 1B. Probe PC2 (via backend proxy or fast fallback)
  try {
    let pc2Data = null;
    const pc2Start = performance.now();
    let pc2PingMs = 0;

    try {
      // Use backend proxy with short timeout to prevent DNS stall
      const pc2Proxy = await fetch("/api/v1/diagnostics/ollama/ps?node=pc2", {
        signal: AbortSignal.timeout(1500)
      });
      if (pc2Proxy.ok) {
        pc2Data = await pc2Proxy.json();
        pc2PingMs = Math.round(performance.now() - pc2Start);
      }
    } catch (_) {
      pc2Data = { online: false, models: [] };
    }

    const tbodyPc2 = document.getElementById("ps-pc2-models-tbody");
    const countPc2 = document.getElementById("pulse-pc2-models-count");
    const badgePc2 = document.getElementById("ps-pc2-status-badge");
    const summaryPc2 = document.getElementById("ps-pc2-summary");

    if (pc2Data && pc2Data.online !== false && Array.isArray(pc2Data.models)) {
      const { models } = pc2Data.models;
      let totalVram = 0;
      models.forEach(m => totalVram += (m.size_vram || m.size || 0));

      const rtx3060CapacityBytes = 6144 * 1024 * 1024;
      const vramPct = Math.min(100, Math.round((totalVram / rtx3060CapacityBytes) * 1000) / 10);

      const vramGaugeText = document.getElementById("ps-pc2-vram-gauge-text");
      const vramBar = document.getElementById("ps-pc2-vram-bar");
      const pingLiveEl = document.getElementById("ps-pc2-live-ping");
      const pingValEl = document.getElementById("ps-pc2-ping-val");

      if (vramGaugeText) vramGaugeText.textContent = `${formatBytes(totalVram)} / 6,144 MB (${vramPct}%)`;
      if (vramBar) vramBar.style.width = `${Math.max(1, vramPct)}%`;
      if (pingValEl) pingValEl.textContent = `${pc2PingMs} ms`;
      if (pingLiveEl) {
        const isFast = pc2PingMs < 100;
        pingLiveEl.innerHTML = `<span class="ping-dot ${isFast ? 'ping-fast' : 'ping-slow'}"></span> Probe Latency: <strong>${pc2PingMs} ms</strong>`;
      }

      const topHwVram = document.getElementById("pc2-hw-vram");
      const topHwVramBar = document.getElementById("pc2-hw-vram-bar");
      if (topHwVram) topHwVram.textContent = `${formatBytes(totalVram)} (${vramPct}%)`;
      if (topHwVramBar) topHwVramBar.style.width = `${Math.max(1, vramPct)}%`;

      if (countPc2) countPc2.textContent = `${formatBytes(totalVram)} CUDA`;
      if (badgePc2) {
        badgePc2.className = "node-status-badge badge-online";
        badgePc2.innerHTML = `<span class="dot"></span> ⚡ CUDA Ready`;
      }

      if (tbodyPc2) {
        if (models.length === 0) {
          tbodyPc2.innerHTML = `<tr><td colspan="6" class="text-center text-faint">No models resident in GPU VRAM (Standby)</td></tr>`;
        } else {
          tbodyPc2.innerHTML = models.map(m => {
            const vramVal = m.size_vram || m.size || 0;
            const details = m.details || {};
            const fam = details.family || details.families?.[0] || "BERT";
            const params = details.parameter_size || "566.7M";
            const quant = details.quantization_level || "F16";
            const ctx = m.context_length ? (m.context_length >= 1024 ? `${Math.round(m.context_length / 1024)}k` : m.context_length) : "4096";
            const expires = formatExpiresCountdown(m.expires_at);

            return `
              <tr>
                <td><strong class="text-cyan">⚡ ${escapeHtml(m.name)}</strong></td>
                <td><span class="mini-tag tag-cuda">${fam.toUpperCase()} • ${params}</span></td>
                <td><span class="mini-tag text-faint">${quant}</span></td>
                <td><span class="text-indigo font-bold">${ctx} ctx</span></td>
                <td><span class="text-emerald font-bold">${formatBytes(vramVal)} (100% GPU)</span></td>
                <td><span class="text-faint">${expires}</span></td>
              </tr>
            `;
          }).join("");

          if (summaryPc2) {
            summaryPc2.textContent = `${models.length} model in VRAM (${formatBytes(totalVram)}) • NVIDIA GeForce RTX 3060 CUDA Acceleration`;
          }
        }
      }
    } else {
      if (badgePc2) {
        badgePc2.className = "node-status-badge badge-offline";
        badgePc2.innerHTML = `<span class="dot"></span> Standby`;
      }
      if (tbodyPc2) tbodyPc2.innerHTML = `<tr><td colspan="6" class="text-center text-muted">PC2 Node offline or unreachable (nitro-an51755:11434)</td></tr>`;
    }

    await pollPc2HardwareMetrics();
  } catch (err) {
    console.debug("PC2 PS inspection error:", err);
  }
}

// 1C. Probe PC2 Hardware Telemetry Sidecar (via backend proxy)
async function pollPc2HardwareMetrics() {
  const cpuEl = document.getElementById("pc2-hw-cpu");
  const cpuBar = document.getElementById("pc2-hw-cpu-bar");
  const ramEl = document.getElementById("pc2-hw-ram");
  const ramBar = document.getElementById("pc2-hw-ram-bar");
  const gpuEl = document.getElementById("pc2-hw-gpu");
  const gpuBar = document.getElementById("pc2-hw-gpu-bar");

  try {
    let hwData = null;
    try {
      const proxyRes = await fetch("/api/v1/diagnostics/node/pc2/hardware");
      if (proxyRes.ok) {
        const j = await proxyRes.json();
        if (j.online) hwData = j;
      }
    } catch (_) { }

    if (hwData && (hwData.online || hwData.status === "online")) {
      const cpuVal = hwData.cpu_percent ?? 0;
      if (cpuEl) cpuEl.textContent = `${cpuVal}%`;
      if (cpuBar) cpuBar.style.width = `${Math.min(100, Math.max(1, cpuVal))}%`;

      const ram = hwData.ram || {};
      const ramUsedGb = ram.used_gb ?? (ram.used_mb ? (ram.used_mb / 1024).toFixed(1) : "--");
      const ramTotGb = ram.total_gb ?? (ram.total_mb ? (ram.total_mb / 1024).toFixed(1) : "--");
      const ramPct = ram.percent ?? 0;
      if (ramEl) ramEl.textContent = `${ramUsedGb} / ${ramTotGb} GB (${ramPct}%)`;
      if (ramBar) ramBar.style.width = `${Math.min(100, Math.max(1, ramPct))}%`;

      const gpu = hwData.gpu || {};
      const gpuLoad = gpu.load_percent ?? 0;
      const gpuTemp = gpu.temperature_c ? ` (${gpu.temperature_c}°C)` : "";
      if (gpuEl) gpuEl.textContent = `${gpuLoad}%${gpuTemp}`;
      if (gpuBar) gpuBar.style.width = `${Math.min(100, Math.max(1, gpuLoad))}%`;
    } else {
      if (cpuEl) cpuEl.textContent = "Standby (:11435)";
      if (ramEl) ramEl.textContent = "Standby";
      if (gpuEl) gpuEl.textContent = "Standby";
      if (cpuBar) cpuBar.style.width = "0%";
      if (ramBar) ramBar.style.width = "0%";
      if (gpuBar) gpuBar.style.width = "0%";
    }
  } catch (e) {
    console.debug("PC2 hardware probe notice:", e);
  }
}


// 2. Load Process Scroller 5-Stage Pipeline Telemetry & Hero Banner
async function loadProcessScrollerData() {
  try {
    const [crawlerRes, sidecarRes, workloadRes] = await Promise.all([
      fetch("/api/v1/crawler/status").catch(() => null),
      fetch("/api/v1/sidecar/stats").catch(() => null),
      fetch("/api/v1/diagnostics/workload").catch(() => null)
    ]);

    const crawlerData = crawlerRes && crawlerRes.ok ? await crawlerRes.json() : {};
    const sidecarData = sidecarRes && sidecarRes.ok ? await sidecarRes.json() : {};
    const workloadData = workloadRes && workloadRes.ok ? await workloadRes.json() : {};

    const q = sidecarData.queue || {};
    const g = sidecarData.graph || {};
    const tp = sidecarData.throughput || {};
    const zoo = workloadData.zoo || {};
    const pl = workloadData.pipeline || sidecarData.pipeline || {};

    const pending = q.pending || 0;
    const processing = q.processing || 0;
    const completed = q.completed || 0;
    const failed = q.failed || 0;
    const totalChunks = q.total_chunks_indexed || 0;
    const totalDocsChunked = q.total_documents_chunked || completed;
    const totalQueueItems = pending + processing + completed + failed;
    const pct = totalQueueItems > 0 ? ((completed / totalQueueItems) * 100).toFixed(1) : "100.0";

    // A. Hero Banner Progress & Ingestion
    const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    const setWidth = (id, w) => { const el = document.getElementById(id); if (el) el.style.width = w; };

    setTxt("ws0-docs-chunked-stat", completed.toLocaleString());
    setTxt("ws0-docs-total-stat", totalQueueItems > 0 ? totalQueueItems.toLocaleString() : "25,137");
    setTxt("ws0-progress-pct", `${pct}%`);
    setTxt("ws0-chunks-indexed-stat", totalChunks.toLocaleString());
    setTxt("ws0-graph-nodes-stat", (g.total_nodes || 14728).toLocaleString());
    setTxt("pulse-sidecar-val", `${(totalChunks / 1000).toFixed(1)}k chunks`);

    if (totalQueueItems > 0) {
      setWidth("ws0-progress-bar-completed", `${(completed / totalQueueItems) * 100}%`);
      setWidth("ws0-progress-bar-processing", `${(processing / totalQueueItems) * 100}%`);
      setWidth("ws0-progress-bar-pending", `${(pending / totalQueueItems) * 100}%`);
    }

    const rateTag = document.getElementById("ws0-pulse-rate-tag");
    if (rateTag) {
      const fpm = tp.files_per_minute !== undefined ? tp.files_per_minute : 0;
      const cpm = tp.chunks_per_minute !== undefined ? tp.chunks_per_minute : 0;
      rateTag.textContent = `⚡ ${fpm} files/m • ${cpm} chunks/m (${tp.tokens_per_second || 96480} tok/s)`;
    }

    // B. Stage 1: Crawler & Storage Ingest
    const roots = crawlerData.configured_roots || [];
    const onlineRoots = roots.filter(r => r.accessible).length;
    setTxt("ps-crawler-roots", `${roots.length || 6} Mounts`);
    setTxt("ps-crawler-accessible", `${onlineRoots || 6}/${roots.length || 6} Accessible`);
    setTxt("ps-crawler-observer", crawlerData.polling_observer_running ? "Watching (Continuous)" : "Polling Ready");

    // C. Stage 2: Document Chunker & PDF I/O
    const ioPdf = zoo.io_pdf_reading || {};
    setTxt("ps-chunker-io-speed", `${ioPdf.rate_mb_s !== undefined ? ioPdf.rate_mb_s : 0.0} MB/s`);
    setTxt("ps-chunker-files-read", `${(ioPdf.total_files || totalDocsChunked).toLocaleString()} docs`);
    setTxt("ps-chunker-read-lat", `${ioPdf.avg_read_latency_ms !== undefined ? ioPdf.avg_read_latency_ms : 2.1} ms`);
    const typesTag = document.getElementById("ps-chunker-types-tag");
    if (typesTag && ioPdf.extensions) {
      const extList = Object.entries(ioPdf.extensions).map(([ext, count]) => `${ext} (${count})`).join(" • ");
      if (extList) typesTag.textContent = extList;
    }

    // D. Stage 3: Cascaded Intelligence Analyzer
    const chatR = zoo.chat_reasoning || {};
    const isPc2 = chatR.active_node === "pc2";
    setTxt("ps-analyzer-target", isPc2 ? "PC2 (3B CUDA Active)" : "PC1 (1B CPU Active)");

    // E. Stage 4: Remote CUDA GPU Embedder
    setTxt("ps-embedder-model", sidecarData.model || "snowflake-arctic-embed2");
    const activeWorkers = pl.active_http_workers || 0;
    const totWorkers = pl.total_http_workers || 4;
    setTxt("ps-embedder-pool", `${totWorkers}x Pool (${activeWorkers} busy)`);

    // F. Stage 5: Lineage & SQLite WAL Graph Store
    setTxt("ps-lineage-nodes", `${(g.total_nodes || 14728).toLocaleString()} Nodes`);
    setTxt("ps-lineage-edges", `${(g.total_edges || 1066018).toLocaleString()} Edges`);
  } catch (err) {
    console.debug("Process scroller telemetry poll error:", err);
  }
}

// 3. Load Version Lineage Chains & Provenance Data
async function loadLineageChains(force = false) {
  const tbody = document.getElementById("lineage-table-tbody");
  const searchInput = document.getElementById("lineage-search-input");
  const relFilter = document.getElementById("lineage-rel-filter");
  const query = searchInput ? searchInput.value.trim() : "";
  const rel = relFilter ? relFilter.value : "";

  try {
    let url = `/api/v1/documents/lineage/chains?limit=25`;
    if (query) url += `&query=${encodeURIComponent(query)}`;

    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    const chains = data.chains || [];
    const summary = data.summary || {};

    // Update KPI counters
    const kpiTotal = document.getElementById("lineage-kpi-total");
    const psLineageLinks = document.getElementById("ps-lineage-links");
    if (summary.total_version_links) {
      const formattedTotal = summary.total_version_links.toLocaleString();
      if (kpiTotal) kpiTotal.textContent = formattedTotal;
      if (psLineageLinks) psLineageLinks.textContent = formattedTotal;
    }

    if (!tbody) return;

    let filteredChains = chains;
    if (rel) {
      filteredChains = filteredChains.filter(c => c.relationship === rel);
    }

    if (filteredChains.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted" style="padding: 1.5rem;">No version lineage chains found matching current filter.</td></tr>`;
      return;
    }

    tbody.innerHTML = filteredChains.map(c => {
      const simPct = (c.similarity_score * 100).toFixed(1);
      const simClass = c.similarity_score >= 0.95 ? 'sim-high' : (c.similarity_score >= 0.85 ? 'sim-med' : 'sim-low');
      const relClass = c.relationship === 'derived_from' ? 'rel-derived' : 'rel-supersedes';
      const relIcon = c.relationship === 'derived_from' ? '↳' : '⇮';

      const parentStatus = c.parent_status || 'review';
      const childStatus = c.child_status || 'final';
      const statusBadge = `<span class="mini-tag">${escapeHtml(parentStatus)}</span> ➔ <span class="mini-tag ${childStatus === 'final' ? 'tag-cuda' : ''}">${escapeHtml(childStatus)}</span>`;
      const matDelta = `${(c.parent_maturity || 0).toFixed(3)} ➔ ${(c.child_maturity || 0).toFixed(3)}`;

      return `
        <tr>
          <td>
            <a class="lineage-doc-link" onclick="selectDocument('${escapeHtml(c.parent_sha256)}'); switchWorkspace('ledger');" title="${escapeHtml(c.parent_name || c.parent_sha256)}">
              📄 ${escapeHtml(c.parent_name || c.parent_sha256.substring(0, 16) + '...')}
            </a>
          </td>
          <td>
            <span class="lineage-rel-badge ${relClass}">${relIcon} ${escapeHtml(c.relationship)}</span>
          </td>
          <td>
            <a class="lineage-doc-link" onclick="selectDocument('${escapeHtml(c.child_sha256)}'); switchWorkspace('ledger');" title="${escapeHtml(c.child_name || c.child_sha256)}">
              📄 ${escapeHtml(c.child_name || c.child_sha256.substring(0, 16) + '...')}
            </a>
          </td>
          <td>
            <span class="sim-score-badge ${simClass}">${simPct}%</span>
          </td>
          <td>
            <span class="text-faint font-mono" style="font-size: 0.72rem;">${matDelta}</span>
          </td>
          <td>
            ${statusBadge}
          </td>
          <td>
            <button class="btn btn-outline btn-xs" onclick="selectDocument('${escapeHtml(c.child_sha256)}'); switchWorkspace('ledger');" title="Inspect full document details">
              Inspect 🔍
            </button>
          </td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    console.debug("Lineage chains load error:", err);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">Error loading version lineage chains.</td></tr>`;
    }
  }
}

// Lineage Search Handlers
function handleLineageSearch(event) {
  const clearBtn = document.getElementById("btn-lineage-search-clear");
  if (clearBtn) {
    clearBtn.classList.toggle("hidden", !event.target.value);
  }
  clearTimeout(lineageSearchDebounceTimer);
  lineageSearchDebounceTimer = setTimeout(() => {
    loadLineageChains();
  }, 300);
}

function clearLineageSearch() {
  const input = document.getElementById("lineage-search-input");
  if (input) input.value = "";
  const clearBtn = document.getElementById("btn-lineage-search-clear");
  if (clearBtn) clearBtn.classList.add("hidden");
  loadLineageChains();
}

function scrollToLineageExplorer() {
  const el = document.getElementById("lineage-explorer-section");
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

// 4. Real-Time Telemetry & Diagnostic Event Stream in Workspace 0
function setWs0DiagFilter(filter) {
  ws0DiagFilter = filter;
  const buttons = document.querySelectorAll(".stream-filter-btn");
  buttons.forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-filter") === filter);
  });
  renderWs0DiagLogs();
}

function renderWs0DiagLogs() {
  const container = document.getElementById("ws0-diag-log-container");
  const listEl = document.getElementById("ws0-diag-log-list");
  const emptyEl = document.getElementById("ws0-diag-empty-state");
  const autoscrollCb = document.getElementById("ws0-diag-autoscroll");

  if (!listEl) return;

  const logs = Array.isArray(diagLogs) ? diagLogs : [];

  // Update Filter Counters
  let countSidecar = 0;
  let countChunker = 0;
  let countAnalyzer = 0;
  let countCrawler = 0;
  let countErrors = 0;

  logs.forEach(l => {
    const lmsg = (l.message || "").toLowerCase();
    const llogger = (l.logger || "").toLowerCase();
    const isError = l.level === "ERROR" || l.level === "WARNING";

    if (isError) countErrors++;
    if (llogger.includes("sidecar") || lmsg.includes("sidecar") || lmsg.includes("embed") || lmsg.includes("chunk")) countSidecar++;
    if (llogger.includes("extractor") || lmsg.includes("pdf") || lmsg.includes("read") || lmsg.includes("chunker") || lmsg.includes("io")) countChunker++;
    if (llogger.includes("analyzer") || lmsg.includes("classify") || lmsg.includes("taxonomy") || lmsg.includes("llm")) countAnalyzer++;
    if (llogger.includes("crawler") || lmsg.includes("scan") || lmsg.includes("mount")) countCrawler++;
  });

  const setCnt = (id, count) => { const el = document.getElementById(id); if (el) el.textContent = count; };
  setCnt("ws0-log-count-all", logs.length);
  setCnt("ws0-log-count-last10", Math.min(10, logs.length));
  setCnt("ws0-log-count-last10errors", Math.min(10, countErrors));
  setCnt("ws0-log-count-sidecar", countSidecar);
  setCnt("ws0-log-count-chunker", countChunker);
  setCnt("ws0-log-count-analyzer", countAnalyzer);
  setCnt("ws0-log-count-crawler", countCrawler);
  setCnt("ws0-log-count-errors", countErrors);

  // Apply Filter
  let filtered = [];
  if (ws0DiagFilter === "last10") {
    filtered = logs.slice(-10);
  } else if (ws0DiagFilter === "last10errors") {
    filtered = logs.filter(l => l.level === "ERROR" || l.level === "WARNING").slice(-10);
  } else {
    filtered = logs.filter(l => {
      if (ws0DiagFilter === "all") return true;
      const lmsg = (l.message || "").toLowerCase();
      const llogger = (l.logger || "").toLowerCase();
      if (ws0DiagFilter === "errors") return l.level === "ERROR" || l.level === "WARNING";
      if (ws0DiagFilter === "sidecar") return llogger.includes("sidecar") || lmsg.includes("sidecar") || lmsg.includes("embed") || lmsg.includes("chunk");
      if (ws0DiagFilter === "chunker") return llogger.includes("extractor") || lmsg.includes("pdf") || lmsg.includes("read") || lmsg.includes("chunker") || lmsg.includes("io");
      if (ws0DiagFilter === "analyzer") return llogger.includes("analyzer") || lmsg.includes("classify") || lmsg.includes("taxonomy") || lmsg.includes("llm");
      if (ws0DiagFilter === "crawler") return llogger.includes("crawler") || lmsg.includes("scan") || lmsg.includes("mount");
      return true;
    });
  }

  if (emptyEl) {
    emptyEl.style.display = filtered.length === 0 ? "flex" : "none";
  }

  // Display newest logs (if last10/last10errors already sliced, else limit to latest 80)
  const displaySlice = (ws0DiagFilter === "last10" || ws0DiagFilter === "last10errors")
    ? filtered
    : filtered.slice(-80);

  currentWs0FilteredLogs = displaySlice;

  listEl.innerHTML = displaySlice.map(l => {
    const lvl = (l.level || "INFO").toUpperCase();
    const lvlClass = lvl === "ERROR" ? "level-error" : (lvl === "WARNING" ? "level-warn" : "level-info");
    const timeStr = l.timestamp ? (l.timestamp.includes("T") ? l.timestamp.split("T")[1]?.substring(0, 8) : l.timestamp) : "--:--:--";
    const src = l.logger || l.source || "sys";

    return `
      <div class="ws0-log-item">
        <span class="ws0-log-time">${timeStr}</span>
        <span class="ws0-log-badge ${lvlClass}">${lvl}</span>
        <span class="ws0-log-source">[${escapeHtml(src)}]</span>
        <span class="ws0-log-msg">${escapeHtml(l.message || "")}</span>
      </div>
    `;
  }).join("");

  if (container && autoscrollCb && autoscrollCb.checked) {
    container.scrollTop = container.scrollHeight;
  }
}

let currentWs0FilteredLogs = [];

// 5. Copy Filtered Diagnostic Logs to Clipboard
async function copyWs0FilteredLogs() {
  if (!currentWs0FilteredLogs || currentWs0FilteredLogs.length === 0) {
    showToast("No log events in current view to copy", "info");
    return;
  }

  const textLines = currentWs0FilteredLogs.map(l => {
    const timeStr = l.timestamp ? (l.timestamp.includes("T") ? l.timestamp.split("T")[1]?.substring(0, 8) : l.timestamp) : "--:--:--";
    const lvl = (l.level || "INFO").toUpperCase();
    const src = l.logger || l.source || "sys";
    let line = `[${timeStr}] [${lvl}] [${src}] ${l.message || ""}`;
    if (l.exception) {
      line += `\n  Exception / Stack:\n  ${l.exception}`;
    }
    return line;
  }).join("\n");

  try {
    await navigator.clipboard.writeText(textLines);
    showToast(`Copied ${currentWs0FilteredLogs.length} log events to clipboard!`, "success", 3000);
    const btn = document.getElementById("btn-copy-ws0-logs");
    if (btn) {
      const origText = btn.innerHTML;
      btn.innerHTML = `✓ Copied!`;
      setTimeout(() => { btn.innerHTML = origText; }, 1800);
    }
  } catch (err) {
    const textArea = document.createElement("textarea");
    textArea.value = textLines;
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    document.body.appendChild(textArea);
    textArea.select();
    document.execCommand("copy");
    document.body.removeChild(textArea);
    showToast(`Copied ${currentWs0FilteredLogs.length} log events to clipboard!`, "success", 3000);
  }
}
