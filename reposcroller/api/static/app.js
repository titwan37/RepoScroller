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
    loadLedger()
  ]);

  // Periodic refresh for metrics, sidecar queue, and workload telemetry
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
      activeTierPill.className = `workload-hud-pill ${
        tierData.active_tier === 'cuda' ? 'pill-cuda' : (tierData.active_tier === 'local' ? 'pill-local' : 'pill-fallback')
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
      const totW = pl.total_http_workers || 6;
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

      <div class="detail-section" style="margin-top: 1rem;">
        <button class="btn btn-interrogate-detail" data-filename="${escapeHtml(doc.canonical_filename)}" onclick="interrogateAboutCurrent(this.getAttribute('data-filename'))">
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
// 12. Workspace Navigation (Ledger, GraphRAG Studio, AI Room)
// ==========================================
let activeWorkspace = "process";

function switchWorkspace(ws) {
  activeWorkspace = ws;

  const btnProcess = document.getElementById("ws-btn-process");
  const btnLedger = document.getElementById("ws-btn-ledger");
  const btnGraphrag = document.getElementById("ws-btn-graphrag");
  const btnUniverse = document.getElementById("ws-btn-universe");
  const btnChat = document.getElementById("ws-btn-chat");

  const paneProcess = document.getElementById("ws-pane-process");
  const paneLedger = document.getElementById("ws-pane-ledger");
  const paneGraphrag = document.getElementById("ws-pane-graphrag");
  const paneUniverse = document.getElementById("ws-pane-universe");
  const paneChat = document.getElementById("ws-pane-chat");

  if (btnProcess) btnProcess.classList.toggle("active", ws === "process");
  if (btnLedger) btnLedger.classList.toggle("active", ws === "ledger");
  if (btnGraphrag) btnGraphrag.classList.toggle("active", ws === "graphrag");
  if (btnUniverse) btnUniverse.classList.toggle("active", ws === "universe");
  if (btnChat) btnChat.classList.toggle("active", ws === "chat");

  if (paneProcess) paneProcess.classList.toggle("hidden", ws !== "process");
  if (paneLedger) paneLedger.classList.toggle("hidden", ws !== "ledger");
  if (paneGraphrag) paneGraphrag.classList.toggle("hidden", ws !== "graphrag");
  if (paneUniverse) paneUniverse.classList.toggle("hidden", ws !== "universe");
  if (paneChat) paneChat.classList.toggle("hidden", ws !== "chat");

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
  } else if (ws === "chat") {
    const chatInput = document.getElementById("chat-input");
    if (chatInput) chatInput.focus();
  } else if (ws === "ledger") {
    loadLedger();
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
    const res = await fetch(`/api/v1/sidecar/graph-rag?query=${encodeURIComponent(query)}&top_k=8&expand_graph_hops=1`);
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
              <button class="btn btn-outline btn-xs" onclick="selectDocument('${escapeHtml(sha)}'); switchWorkspace('ledger');" title="Inspect full document in ledger">
                🗄️ View in Ledger
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
  let sseUrl = `/api/v1/chat/stream?query=${encodeURIComponent(query)}&node=${encodeURIComponent(activeChatNode)}`;
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
  labelsGroup: null,
  axesGroup: null,
  gridHelper: null,
  nodes: [],
  edges: [],
  clusters: [],
  axes: {},
  stats: {},
  uniforms: {
    uTime: { value: 0.0 },
    uPointSize: { value: 1.0 },
  },
  autoSpin: true,
  showEdges: true,
  showLabels: true,
  colorMode: "cluster",
  activeClusterFilter: "all",
  selectedNode: null,
  hoveredNodeIndex: -1,
  raycaster: null,
  mouse: null,
  animId: null,
  isUserInteracting: false,
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

const UNIVERSE_FRAGMENT_SHADER = `
  varying vec3 vColor;
  varying float vCluster;
  varying float vDegree;
  varying float vDimmed;
  varying float vDist;

  uniform float uTime;

  void main() {
    vec2 coord = gl_PointCoord - vec2(0.5);
    float r = length(coord);
    if (r > 0.5) discard;

    // Radial falloff: solid core + glowing Gaussian halo
    float core = smoothstep(0.24, 0.04, r);
    float halo = exp(-r * 6.5);
    float alpha = clamp(core * 0.95 + halo * 0.65, 0.0, 1.0);

    if (vDimmed > 0.5) {
      alpha *= 0.15;
    }

    // Dynamic luminescence shimmer
    float shimmer = 0.88 + 0.16 * sin(uTime * 3.2 + vCluster * 2.0);
    vec3 finalColor = vColor * shimmer + vec3(0.08, 0.14, 0.22) * halo;

    gl_FragColor = vec4(finalColor, alpha);
  }
`;

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

  // Scene & Camera
  glsl3D.scene = new THREE.Scene();
  glsl3D.scene.background = null; // transparent to inherit CSS gradient

  glsl3D.camera = new THREE.PerspectiveCamera(50, width / height, 1, 4000);
  glsl3D.camera.position.set(0, 45, 270);

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
    glsl3D.controls.maxDistance = 1200;
    glsl3D.controls.target.set(0, 0, 0);

    glsl3D.controls.addEventListener("start", () => {
      glsl3D.isUserInteracting = true;
    });
    glsl3D.controls.addEventListener("end", () => {
      glsl3D.isUserInteracting = false;
    });
  }

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
  canvasEl.addEventListener("mouseleave", on3DMouseLeave);

  // Window Resize Listener
  window.addEventListener("resize", onWindowResize3D);
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => onWindowResize3D()).observe(container);
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

function onWindowResize3D() {
  if (!glsl3D.renderer || !glsl3D.camera || !glsl3D.container) return;
  const width = glsl3D.container.clientWidth || 800;
  const height = glsl3D.container.clientHeight || 650;
  glsl3D.camera.aspect = width / height;
  glsl3D.camera.updateProjectionMatrix();
  glsl3D.renderer.setSize(width, height);
}

async function load3DUniverseData(forceReload = false) {
  if (glsl3D.nodes.length > 0 && !forceReload) {
    return;
  }

  try {
    const res = await fetch("/api/v1/sidecar/graph-3d?limit=350");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();

    glsl3D.nodes = data.nodes || [];
    glsl3D.edges = data.edges || [];
    glsl3D.clusters = data.clusters || [];
    glsl3D.axes = data.axes || {};
    glsl3D.stats = data.stats || {};

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

      clusterLegendContainer.innerHTML = glsl3D.clusters.map(c => `
        <div class="cluster-item" onclick="filter3DCluster(${c.id})">
          <div class="cluster-item-left">
            <span class="cluster-color-dot" style="background: ${c.color}; color: ${c.color};"></span>
            <span class="cluster-name" title="${escapeHtml(c.name)}">${escapeHtml(c.icon || "")} ${escapeHtml(c.name)}</span>
          </div>
          <span class="cluster-count">${counts[c.id] || 0}</span>
        </div>
      `).join("");
    }

    // Build Three.js Point Cloud & Edges
    build3DSceneObjects();

  } catch (err) {
    console.error("Failed to load 3D Knowledge Universe:", err);
    pushDiagnosticLog("error", "Failed to load 3D Knowledge Universe data: " + err.message, "frontend", "GLSL3D");
  }
}

function build3DSceneObjects() {
  if (!glsl3D.scene || !glsl3D.worldGroup) return;

  // Remove old objects
  if (glsl3D.pointsMesh) glsl3D.worldGroup.remove(glsl3D.pointsMesh);
  if (glsl3D.edgesMesh) glsl3D.worldGroup.remove(glsl3D.edgesMesh);
  if (glsl3D.labelsGroup) glsl3D.worldGroup.remove(glsl3D.labelsGroup);

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

    positions[i * 3 + 0] = n.x;
    positions[i * 3 + 1] = n.y;
    positions[i * 3 + 2] = n.z;

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
    blending: THREE.AdditiveBlending,
  });

  glsl3D.pointsMesh = new THREE.Points(geometry, shaderMaterial);
  glsl3D.worldGroup.add(glsl3D.pointsMesh);

  // 2. Edges Buffer Geometry
  const edgePositions = [];
  const edgeColors = [];
  const defaultLineColor = new THREE.Color(0x38bdf8);

  glsl3D.edges.forEach(e => {
    const sIdx = nodeIndexMap.get(e.source);
    const tIdx = nodeIndexMap.get(e.target);
    if (sIdx !== undefined && tIdx !== undefined) {
      const sNode = glsl3D.nodes[sIdx];
      const tNode = glsl3D.nodes[tIdx];

      edgePositions.push(sNode.x, sNode.y, sNode.z);
      edgePositions.push(tNode.x, tNode.y, tNode.z);

      const sColor = new THREE.Color(sNode.cluster_color || "#38bdf8");
      edgeColors.push(sColor.r, sColor.g, sColor.b);
      edgeColors.push(sColor.r, sColor.g, sColor.b);
    }
  });

  if (edgePositions.length > 0) {
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute("position", new THREE.Float32BufferAttribute(edgePositions, 3));
    edgeGeo.setAttribute("color", new THREE.Float32BufferAttribute(edgeColors, 3));

    const edgeMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.22,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    glsl3D.edgesMesh = new THREE.LineSegments(edgeGeo, edgeMat);
    glsl3D.edgesMesh.visible = glsl3D.showEdges;
    glsl3D.worldGroup.add(glsl3D.edgesMesh);
  }

  // 3. Billboard Text Labels for High-Degree Nodes (Top 25)
  glsl3D.labelsGroup = new THREE.Group();
  const topNodes = [...glsl3D.nodes].sort((a, b) => b.degree - a.degree).slice(0, 25);

  topNodes.forEach(n => {
    const sprite = create3DTextSprite(`${n.name}`, n.cluster_color, 20);
    sprite.position.set(n.x, n.y + 4.5, n.z);
    sprite.scale.set(22, 5.5, 1);
    glsl3D.labelsGroup.add(sprite);
  });

  glsl3D.labelsGroup.visible = glsl3D.showLabels;
  glsl3D.worldGroup.add(glsl3D.labelsGroup);
}

function getNodeColorForMode(node, mode) {
  if (mode === "centrality") {
    // Heatmap: Cold dark blue -> Cyan -> Emerald -> Amber -> Red/Hot
    const deg = node.degree || 0;
    const t = Math.min(1.0, Math.log(deg + 1) / Math.log(200));
    const hsl = [ (1.0 - t) * 0.65, 0.9, 0.55 ];
    return new THREE.Color().setHSL(hsl[0], hsl[1], hsl[2]);
  } else if (mode === "type") {
    const typeColors = {
      organization: "#38bdf8",
      contract_type: "#10b981",
      person: "#c084fc",
      location: "#f59e0b",
      statute: "#f43f5e",
    };
    return new THREE.Color(typeColors[node.type] || "#94a3b8");
  } else {
    // Topological Cluster Color
    return new THREE.Color(node.cluster_color || "#38bdf8");
  }
}

function animate3DUniverse() {
  glsl3D.animId = requestAnimationFrame(animate3DUniverse);

  // Advance GLSL temporal uniform
  glsl3D.uniforms.uTime.value += 0.016;

  // Auto-Spin orbital rotation
  if (glsl3D.autoSpin && !glsl3D.isUserInteracting && glsl3D.worldGroup) {
    glsl3D.worldGroup.rotation.y += 0.0015;
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
  if (type) type.textContent = node.type;
  if (cluster) cluster.textContent = node.cluster_name || "Cluster " + node.cluster;
  if (degree) degree.textContent = node.degree;
  if (docs) docs.textContent = node.doc_count || 1;

  tooltip.style.display = "block";
}

function open3DNodeInspector(node) {
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
  if (docCountEl) docCountEl.textContent = node.doc_count || 1;
  if (coordsEl) coordsEl.textContent = `[${node.x}, ${node.y}, ${node.z}]`;
  if (dateEl) dateEl.textContent = node.latest_date ? node.latest_date.split("T")[0] : "2026-03-24";

  drawer.classList.remove("hidden");

  // Focus camera smoothly toward the node
  if (glsl3D.controls) {
    glsl3D.controls.target.set(node.x, node.y, node.z);
  }
}

function close3DNodeInspector() {
  glsl3D.selectedNode = null;
  const drawer = document.getElementById("glsl-node-inspector");
  if (drawer) drawer.classList.add("hidden");
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
  glsl3D.activeClusterFilter = clusterId;
  const select = document.getElementById("select-glsl-cluster");
  if (select && select.value !== String(clusterId)) {
    select.value = String(clusterId);
  }

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

function reset3DCamera() {
  if (glsl3D.camera && glsl3D.controls) {
    glsl3D.camera.position.set(0, 45, 270);
    glsl3D.controls.target.set(0, 0, 0);
    if (glsl3D.worldGroup) {
      glsl3D.worldGroup.rotation.set(0, 0, 0);
    }
  }
}

function handle3DNodeSearch(name) {
  if (!name || !name.trim()) return;
  const match = glsl3D.nodes.find(n => n.name.toLowerCase() === name.trim().toLowerCase());
  if (match) {
    open3DNodeInspector(match);
  }
}

function toggleLegendHUD() {
  const body = document.getElementById("axes-legend-body");
  const btn = document.querySelector(".btn-legend-collapse");
  if (!body) return;
  const isHidden = body.style.display === "none";
  body.style.display = isHidden ? "flex" : "none";
  if (btn) btn.textContent = isHidden ? "−" : "+";
}

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

  // 1A. Probe PC1 (127.0.0.1:11434/api/ps)
  try {
    let pc1Data = null;
    try {
      const pc1Direct = await fetch("http://127.0.0.1:11434/api/ps", { signal: AbortSignal.timeout(2800) });
      if (pc1Direct.ok) pc1Data = await pc1Direct.json();
    } catch (directErr) {
      // Fallback to backend proxy
      const pc1Proxy = await fetch("/api/v1/diagnostics/ollama/ps?node=pc1");
      if (pc1Proxy.ok) pc1Data = await pc1Proxy.json();
    }

    const tbodyPc1 = document.getElementById("ps-pc1-models-tbody");
    const countPc1 = document.getElementById("pulse-pc1-models-count");
    const badgePc1 = document.getElementById("ps-pc1-status-badge");
    const summaryPc1 = document.getElementById("ps-pc1-summary");

    if (pc1Data && Array.isArray(pc1Data.models)) {
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
      if (badgePc1) {
        badgePc1.className = "node-status-badge badge-offline";
        badgePc1.innerHTML = `<span class="dot"></span> Standby`;
      }
      if (tbodyPc1) tbodyPc1.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Node offline or unreachable (127.0.0.1:11434)</td></tr>`;
    }
  } catch (err) {
    console.debug("PC1 PS inspection error:", err);
  }

  // 1B. Probe PC2 (nitro-an51755:11434/api/ps)
  try {
    let pc2Data = null;
    try {
      const pc2Direct = await fetch("http://nitro-an51755:11434/api/ps", { signal: AbortSignal.timeout(2800) });
      if (pc2Direct.ok) pc2Data = await pc2Direct.json();
    } catch (directErr) {
      // Fallback to backend proxy
      const pc2Proxy = await fetch("/api/v1/diagnostics/ollama/ps?node=pc2");
      if (pc2Proxy.ok) pc2Data = await pc2Proxy.json();
    }

    const tbodyPc2 = document.getElementById("ps-pc2-models-tbody");
    const countPc2 = document.getElementById("pulse-pc2-models-count");
    const badgePc2 = document.getElementById("ps-pc2-status-badge");
    const summaryPc2 = document.getElementById("ps-pc2-summary");

    if (pc2Data && Array.isArray(pc2Data.models)) {
      const models = pc2Data.models;
      let totalVram = 0;
      models.forEach(m => totalVram += (m.size_vram || m.size || 0));

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
  } catch (err) {
    console.debug("PC2 PS inspection error:", err);
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
    const totWorkers = pl.total_http_workers || 6;
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
  setCnt("ws0-log-count-sidecar", countSidecar);
  setCnt("ws0-log-count-chunker", countChunker);
  setCnt("ws0-log-count-analyzer", countAnalyzer);
  setCnt("ws0-log-count-crawler", countCrawler);
  setCnt("ws0-log-count-errors", countErrors);

  // Apply Filter
  const filtered = logs.filter(l => {
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

  if (emptyEl) {
    emptyEl.style.display = filtered.length === 0 ? "flex" : "none";
  }

  // Display newest logs (limit to latest 80 for high performance)
  const displaySlice = filtered.slice(-80);
  listEl.innerHTML = displaySlice.map(l => {
    const lvl = (l.level || "INFO").toUpperCase();
    const lvlClass = lvl === "ERROR" ? "level-error" : (lvl === "WARNING" ? "level-warn" : "level-info");
    const timeStr = l.timestamp ? l.timestamp.split("T")[1]?.substring(0, 8) || l.timestamp : "--:--:--";
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



