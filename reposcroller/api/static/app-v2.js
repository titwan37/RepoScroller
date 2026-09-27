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
  // Diagnostics initialization — uses global error interceptors for maximum coverage
  initDiagnostics();
  initSideColumnResizer();
  initTableColumnResizers();
  await Promise.all([
    checkBackendHealth(),
    loadMountsAndCrawlerStatus(),
    loadWorkloadTelemetry(),
    loadMetrics(),
    loadSidecarStats(),
    loadTaxonomyCategories(),
    loadLedger(),
    typeof loadProcessScrollerData === "function" ? loadProcessScrollerData() : Promise.resolve(),
    typeof pollOllamaProcessInspector === "function" ? pollOllamaProcessInspector() : Promise.resolve(),
    typeof loadLineageChains === "function" ? loadLineageChains() : Promise.resolve()
  ]);

  if (typeof renderWs0DiagLogs === "function") renderWs0DiagLogs();

  // Periodic refresh for metrics, sidecar queue, workload telemetry, and Workspace 0 live data
  setInterval(() => {
    loadMetrics();
    loadSidecarStats();
    loadWorkloadTelemetry();
    if (activeWorkspace === "process") {
      if (typeof loadProcessScrollerData === "function") loadProcessScrollerData();
      if (typeof pollOllamaProcessInspector === "function") pollOllamaProcessInspector();
      if (typeof renderWs0DiagLogs === "function") renderWs0DiagLogs();
    }
  }, 3500);
}

async function loadWorkloadTelemetry(force = false) {
  const refreshBtn = document.getElementById("btn-workload-refresh");
  if (force && refreshBtn) {
    refreshBtn.classList.add("refreshing");
    refreshBtn.innerHTML = `⟳ Probing...`;
  }

  try {
    const res = await fetch(`/api/v1/diagnostics/workload${force ? '?force=true' : ''}`);
    if (!res.ok) return;
    const data = await res.json();
    
    const syncTimeEl = document.getElementById("hud-sync-time");
    if (syncTimeEl && data.timestamp) {
      syncTimeEl.textContent = `⟳ Synced: ${data.timestamp}`;
    }

    const tierData = data.embedding_tier || {};
    const activeTierPill = document.getElementById("hud-active-tier-pill");
    const activeModelPill = document.getElementById("hud-active-model-pill");

    if (activeTierPill) {
      activeTierPill.textContent = tierData.tier_label || "⚡ CUDA Remote Node (PC2)";
      activeTierPill.className = `workload-hud-pill ${
        tierData.active_tier === 'cuda' ? 'pill-cuda' : (tierData.active_tier === 'local' ? 'pill-local' : 'pill-fallback')
      }`;
    }

    if (activeModelPill && tierData.active_model) {
      activeModelPill.textContent = tierData.active_model;
    }

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
          pc1Ping.innerHTML = ` ${pingVal < 1 ? '<1' : pingVal.toFixed(1)} ms`;
        } else {
          pc1Ping.textContent = 'Offline';
        }
      }

      if (pc1ChatCount) {
        const calls = chatRouting.pc1_requests ?? pc1.stats?.requests ?? 0;
        pc1ChatCount.textContent = `${calls.toLocaleString()} calls`;
      }

      if (pc1Latency) {
        pc1Latency.textContent = `\({pc1.processor || '100% CPU'} (\){pc1.vram_formatted || '0 MB'})`;
        pc1Latency.title = `Host Processor: \({pc1.processor} | VRAM:\){pc1.vram_formatted}`;
      }

      if (pc1Activity) {
        const act = pc1.stats?.last_active || (pc1.online ? 'idle' : 'offline');
        const ctxStr = pc1.context_length > 0 ? ` (${(pc1.context_length >= 1024 ? (pc1.context_length / 1024).toFixed(0) + 'k' : pc1.context_length)} ctx)` : '';
        if (act === 'active') {
          pc1Activity.innerHTML = ` active${ctxStr}`;
        } else if (pc1.online) {
          pc1Activity.innerHTML = ` idle${ctxStr}`;
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
            return `\({shortName}\){meta}`;
          }).join('');
        } else if (Array.isArray(pc1.models_loaded) && pc1.models_loaded.length > 0) {
          pc1ModelsList.innerHTML = pc1.models_loaded.map(m => `${m}`).join('');
        } else {
          pc1ModelsList.innerHTML = `None loaded`;
        }
      }
      
      if (pc1Badge) {
        if (pc1.online) {
          pc1Badge.className = "node-status-badge badge-online";
          pc1Badge.innerHTML = ` Online (CPU)`;
        } else {
          pc1Badge.className = "node-status-badge badge-offline";
          pc1Badge.innerHTML = ` Fallback / Offline`;
        }
      }
    }

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
          pc2Ping.innerHTML = ` ${pingVal < 1 ? '<1' : pingVal.toFixed(1)} ms`;
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
          pc2Latency.textContent = `\({pc2.vram_formatted} (\){pc2.processor || '100% GPU'})`;
          pc2Latency.title = `Active GPU VRAM Allocated: \({pc2.vram_formatted} | Architecture:\){pc2.processor} on NVIDIA RTX 3060`;
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
          pc2Activity.innerHTML = ` active${ctxStr}`;
          pc2Activity.className = "node-metric-val text-cyan font-bold";
        } else if (pc2.online) {
          pc2Activity.innerHTML = ` idle${ctxStr}`;
        } else {
          pc2Activity.textContent = 'offline';
        }
      }

      if (pc2ModelsList) {
        if (!pc2.online) {
          pc2ModelsList.innerHTML = `Offline`;
        } else {
          const details = Array.isArray(pc2.models_detail) ? pc2.models_detail : [];
          const embedModel = pc2.target_model || "snowflake-arctic-embed2:latest";
          const chatModel = pc2.chat_model || "llama3.2:3b";

          const embedDetail = details.find(d => d.name.includes(embedModel.split(':')[0]));
          const chatDetail = details.find(d => d.name.includes(chatModel.split(':')[0]));

          const isEmbedHot = !!embedDetail;
          const isChatHot = !!chatDetail;

          const embedVramMeta = embedDetail ? ` • \({embedDetail.size_vram_mb}MB\){embedDetail.quantization}` : '';
          const chatVramMeta = chatDetail ? ` • \({(chatDetail.size_vram_mb >= 1024 ? (chatDetail.size_vram_mb / 1024).toFixed(1) + 'GB' : chatDetail.size_vram_mb + 'MB')}\){chatDetail.quantization}` : '';

          let tagsHtml = `
            \({isEmbedHot ? '⚡ ' : ''}\){embedModel}${embedVramMeta}
            \({isChatHot ? '⚡ ' : ''}\){chatModel}${chatVramMeta}
          `;

          details.forEach(d => {
            if (!d.name.includes(embedModel.split(':')[0]) && !d.name.includes(chatModel.split(':')[0])) {
              tagsHtml += `⚡ \({d.name} (\){d.size_vram_mb}MB)`;
            }
          });

          pc2ModelsList.innerHTML = tagsHtml;
        }
      }
      
      if (pc2Badge) {
        if (effectiveTier === "cuda" && pc2.online) {
          pc2Badge.className = "node-status-badge badge-online";
          pc2Badge.innerHTML = ` ⚡ CUDA Ready`;
          pc2Badge.title = "Embedding running on PC2 NVIDIA RTX 3060 CUDA GPU";
        } else if (effectiveTier === "local") {
          pc2Badge.className = "node-status-badge badge-fallback-local";
          pc2Badge.innerHTML = ` 🟠 Local CPU Fallback`;
          pc2Badge.title = tierData.last_fallback_reason || "PC2 unreachable. Operating on PC1 Local CPU with snowflake-arctic-embed.";
        } else {
          pc2Badge.className = "node-status-badge badge-fallback-pseudo";
          pc2Badge.innerHTML = ` 🔴 Offline Pseudo-Vectors`;
          pc2Badge.title = "No Ollama instances available. Operating in offline pseudo-vector mode.";
        }
      }
    }

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
    }
    if (tpCheckpoints) {
      const cpVal = tp.checkpoints !== undefined ? tp.checkpoints : 0;
      tpCheckpoints.textContent = `${cpVal} (WAL)`;
    }
    if (tpPayload) {
      const mibVal = tp.payload_mib !== undefined ? tp.payload_mib : 37.702;
      tpPayload.textContent = `${mibVal.toFixed(2)} MiB`;
    }

    const pl = data.pipeline || {};
    const flowProducer = document.getElementById("flow-producer-val");
    const flowEmbedQ = document.getElementById("flow-embed-q-val");
    const flowWorkers = document.getElementById("flow-workers-val");
    const flowDbQ = document.getElementById("flow-db-q-val");
    const flowWriter = document.getElementById("flow-writer-val");

    if (flowProducer) flowProducer.textContent = pl.producer_stage || (sidecarContinuousRunning ? "active" : "idle");
    if (flowEmbedQ) {
      const qVal = pl.embed_queue_depth !== undefined ? pl.embed_queue_depth : 0;
      flowEmbedQ.textContent = `\({qVal}/\){pl.embed_queue_max || 100}`;
    }
    if (flowWorkers) {
      const activeW = pl.active_http_workers !== undefined ? pl.active_http_workers : 0;
      flowWorkers.textContent = `\({pl.total_http_workers || 4}x (\){activeW} busy)`;
    }
    if (flowDbQ) {
      const dbQVal = pl.db_queue_depth !== undefined ? pl.db_queue_depth : 0;
      flowDbQ.textContent = `\({dbQVal}/\){pl.db_queue_max || 100}`;
    }
    if (flowWriter) flowWriter.textContent = pl.db_writer_stage || (sidecarContinuousRunning ? "idle" : "stopped");

    const zoo = data.zoo || {};
    const zooPdfVal = document.getElementById("zoo-pdf-val");
    const zooPdfSub = document.getElementById("zoo-pdf-sub");
    if (zooPdfVal && zoo.io_pdf_reading) {
      zooPdfVal.textContent = `${zoo.io_pdf_reading.rate_mb_s} MB/s`;
      if (zooPdfSub) zooPdfSub.textContent = `(${zoo.io_pdf_reading.files_per_min} f/m)`;
    }

  } catch (err) {
    console.debug("Workload telemetry probe notice:", err);
  } finally {
    if (force && refreshBtn) {
      setTimeout(() => {
        refreshBtn.classList.remove("refreshing");
        refreshBtn.innerHTML = `⟳ Probe Hardware`;
      }, 500);
    }
  }
}

async function switchChatNode(targetNode, targetModel = null) {
  try {
    activeChatNode = targetNode;
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
      showToast(`⚡ api/chat reasoning routed to ${targetNode === "pc2" ? "PC2 Remote (CUDA)" : "PC1 Host (CPU)"}`, "success", 4000);
      loadWorkloadTelemetry(false);
    }
  } catch (err) {
    showToast("Error switching chat routing: " + err, "error");
  }
}

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
      chip.innerHTML = `\({r.accessible ? '🟢' : '🔴'}\){escapeHtml(r.root)}`;
      container.appendChild(chip);
    });
  } catch (err) {
    console.error("Failed loading crawler status:", err);
  }
}

function updateWatcherButton() {
  const btnText = document.getElementById("watch-btn-text");
  if (watcherRunning) {
    if (btnText) btnText.textContent = "Stop Watcher";
    document.getElementById("btn-watch").classList.add("btn-primary");
    document.getElementById("btn-watch").classList.remove("btn-outline");
  } else {
    if (btnText) btnText.textContent = "Start Watcher";
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
  btn.innerHTML = `⏳ Scanning...`;

  try {
    const res = await fetch("/api/v1/crawler/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force_reprocess: false })
    });
    const summary = await res.json();
    showToast(`Scan complete: \({summary.total_ingested} ingested,\){summary.total_duplicates_found} duplicates`, "success", 5000);
    await Promise.all([loadMetrics(), loadLedger(), loadSidecarStats()]);
  } catch (err) {
    showToast("Scan failed: " + err, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `⚡ Quick Scan`;
  }
}

async function loadMetrics() {
  try {
    const res = await fetch("/api/v1/documents/stats");
    const stats = await res.json();
    document.getElementById("metric-unique").textContent = stats.total_unique_documents;
    document.getElementById("metric-locations").textContent = stats.total_physical_locations;
    document.getElementById("metric-savings").textContent = stats.duplicates_deduplicated;
    document.getElementById("metric-lineage").textContent = stats.version_links_count;
  } catch (err) {}
}

async function loadTaxonomyCategories() {
  try {
    const res = await fetch("/api/v1/taxonomy/");
    if (!res.ok) return;
    const data = await res.json();
    const select = document.getElementById("category-filter");
    if (!select) return;

    select.innerHTML = `All Categories (Taxonomy)`;
    (data.categories || []).forEach(cat => {
      const opt = document.createElement("option");
      opt.value = cat.category_id;
      opt.textContent = `\({cat.name_en} (\){cat.name_fr} / ${cat.name_de})`;
      select.appendChild(opt);
    });
  } catch (err) {}
}

function handleCategoryChange() {
  const select = document.getElementById("category-filter");
  activeCategory = select ? select.value : "";
  updateActiveFilterBar();
  loadLedger();
}

function toggleDuplicatesFilter() {
  filterOnlyDuplicates = !filterOnlyDuplicates;
  const card = document.getElementById("card-duplicates");
  const badge = document.getElementById("duplicates-badge");
  const sub = document.getElementById("duplicates-sub");

  if (filterOnlyDuplicates) {
    card.classList.add("active-card");
    badge.classList.remove("hidden");
    sub.textContent = "Showing duplicates only (click to reset)";
    switchWorkspace("ledger");
  } else {
    card.classList.remove("active-card");
    badge.classList.add("hidden");
    sub.textContent = "Exact duplicate copies (click to filter)";
  }
  updateActiveFilterBar();
  loadLedger();
}

function getEffectiveDocDate(doc) {
  if (!doc) return "";
  if (doc.doc_date) return String(doc.doc_date);
  if (doc.created_at) return String(doc.created_at).slice(0, 10);
  return "";
}

function setSort(column) {
  if (activeSortBy === column) {
    activeSortOrder = (activeSortOrder === "ASC") ? "DESC" : "ASC";
  } else {
    activeSortBy = column;
    activeSortOrder = (column === "canonical_filename" || column === "doc_type") ? "ASC" : "DESC";
  }
  updateSortIndicators();
  if (cachedLedgerItems && cachedLedgerItems.length > 0) {
    cachedLedgerItems = sortItemsLocally(cachedLedgerItems, activeSortBy, activeSortOrder);
    renderLedgerRows(cachedLedgerItems);
  }
  loadLedger();
}

function sortItemsLocally(items, sortBy, sortOrder) {
  const isAsc = String(sortOrder).toUpperCase() === "ASC";
  return [...items].sort((a, b) => {
    let valA = String(a[sortBy] || "");
    let valB = String(b[sortBy] || "");
    if (sortBy === "location_count") {
      valA = Number(a.location_count || 0); valB = Number(b.location_count || 0);
    }
    if (valA < valB) return isAsc ? -1 : 1;
    if (valA > valB) return isAsc ? 1 : -1;
    return 0;
  });
}

function updateSortIndicators() {
  const cols = ["canonical_filename", "doc_type", "maturity_score", "lifecycle_status", "location_count", "doc_date", "created_at"];
  cols.forEach(col => {
    const indicator = document.getElementById(`sort-${col}`);
    if (!indicator) return;
    if (col === activeSortBy) {
      indicator.textContent = (activeSortOrder === "ASC") ? "▲" : "▼";
    } else {
      indicator.textContent = "↕";
    }
  });
}

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
  document.getElementById("category-filter").value = "";
  document.getElementById("search-box").value = "";
  updateActiveFilterBar();
  loadLedger();
}

function updateActiveFilterBar() {
  const bar = document.getElementById("active-filter-bar");
  const text = document.getElementById("active-filter-text");
  const resetBtn = document.getElementById("btn-clear-filters");
  if (filterOnlyDuplicates || activeCategory || searchFilterQuery) {
    bar.classList.remove("hidden");
    text.innerHTML = `Filters active`;
    if (resetBtn) resetBtn.classList.remove("hidden");
  } else {
    bar.classList.add("hidden");
    if (resetBtn) resetBtn.classList.add("hidden");
  }
}

async function openFile(filePath, reveal = false) {
  if (!filePath) return;
  try {
    const res = await fetch("/api/v1/documents/open-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_path: filePath, reveal: reveal })
    });
    if (res.ok) showToast(`Revealed: ${filePath}`, "success", 5000);
  } catch (err) {}
}

function handleOpenPathClick(event, el, reveal = false) {
  event.stopPropagation();
  openFile(el.getAttribute("data-path"), reveal);
}

function initSideColumnResizer() {
  const resizer = document.getElementById("side-column-resizer");
  const grid = document.querySelector(".dashboard-grid");
  const sideColumn = document.getElementById("side-column");
  if (!resizer || !grid || !sideColumn) return;
  
  const savedWidth = localStorage.getItem("reposcroller_side_width");
  if (savedWidth) grid.style.setProperty("--side-column-width", `${savedWidth}px`);

  let isDragging = false, startX = 0, startWidth = 0;
  resizer.addEventListener("mousedown", (e) => {
    isDragging = true;
    startX = e.clientX;
    startWidth = sideColumn.getBoundingClientRect().width;
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    grid.style.setProperty("--side-column-width", `${Math.max(280, startWidth + (startX - e.clientX))}px`);
  });
  window.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      localStorage.setItem("reposcroller_side_width", Math.round(sideColumn.getBoundingClientRect().width));
    }
  });
}

function initTableColumnResizers() {}

async function loadLedger() {
  const params = new URLSearchParams();
  if (activeCategory) params.append("category", activeCategory);
  if (filterOnlyDuplicates) params.append("only_duplicates", "true");
  if (searchFilterQuery) params.append("query", searchFilterQuery);
  params.append("sort_by", activeSortBy);
  params.append("sort_order", activeSortOrder);
  params.append("limit", "100");

  try {
    const res = await fetch(`/api/v1/documents/ledger?${params.toString()}`);
    const data = await res.json();
    cachedLedgerItems = sortItemsLocally(data.items || [], activeSortBy, activeSortOrder);
    renderLedgerRows(cachedLedgerItems);
  } catch (err) {}
}

function renderLedgerRows(items) {
  const tbody = document.getElementById("ledger-rows");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (items.length === 0) {
    tbody.innerHTML = `