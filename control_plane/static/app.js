// QMD Knowledgebase Control Plane Frontend Application
let lastLogId = 0;
let currentFilter = "ALL";
let allLogEntries = [];
const MAX_LOG_ENTRIES = 3000;

document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  setInterval(fetchStatus, 3000);
  setupDropzone();

  // Load 3-tier operational mode, Cloudflare sync, and Pi agent status
  fetchOperationalMode();
  setInterval(fetchOperationalMode, 5000);
  fetchSyncStatus();
  setInterval(fetchSyncStatus, 5000);
  fetchPiStatus();
  setInterval(fetchPiStatus, 5000);

  // Load and refresh automations & scheduled tasks
  fetchAutomations();
  setInterval(fetchAutomations, 5000);

  // Start continuous real-time logging across all daemons and pipelines
  pollLogs();
  setInterval(pollLogs, 1500);

  // Check first-run onboarding status
  checkOnboardingStatus();

  const btnWizard = document.getElementById("btn-open-wizard");
  if (btnWizard) btnWizard.addEventListener("click", openWizard);
  document.getElementById("btn-open-prompts").addEventListener("click", openPrompts);
  document.getElementById("btn-open-settings").addEventListener("click", openSettings);
  document.getElementById("btn-start-all-daemons").addEventListener("click", () => controlDaemon("all", "restart"));
});

function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Toast notification helper
function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.innerText = message;
  toast.style.borderColor = isError ? "var(--danger)" : "var(--primary)";
  toast.style.display = "block";
  setTimeout(() => { toast.style.display = "none"; }, 3500);
}

// Fetch live status and update UI indicators
async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    // 1. Update Service Badges
    updateBadge("badge-qmd", data.services.qmd.ok);
    updateBadge("badge-proxy", data.services.auth_proxy.ok);
    updateBadge("badge-tunnel", data.services.tunnel.ok);
    updateBadge("badge-mirror", data.services.mirror.ok);

    if (data.services.bot_gateway) {
      const botBadge = document.getElementById("badge-bot");
      if (botBadge) {
        if (!data.services.bot_gateway.configured) {
          botBadge.className = "badge badge-gray";
          botBadge.innerText = "Not Configured";
        } else {
          updateBadge("badge-bot", data.services.bot_gateway.ok);
        }
      }
    }

    // Update Mirror Link
    if (data.services.mirror.url) {
      document.getElementById("link-mirror").href = data.services.mirror.url;
    }

    // 1b. Update Engine Retrieval Mode
    const mode = (data.retrieval_mode || "cpu-only").toLowerCase();
    const modeBadge = document.getElementById("badge-engine-mode");
    const modeDesc = document.getElementById("desc-engine-mode");
    const btnCpu = document.getElementById("btn-mode-cpu");
    const btnFull = document.getElementById("btn-mode-full");

    if (modeBadge) {
      if (mode === "cpu-only") {
        modeBadge.className = "badge badge-green";
        modeBadge.innerText = "⚡ CPU-Only Mode";
        if (modeDesc) modeDesc.innerText = "Fast sub-second BM25 search with OR fallback; vector embedding & LLM reranking bypassed for instant CPU response without timeouts.";
        if (btnCpu) btnCpu.className = "btn btn-sm btn-primary";
        if (btnFull) btnFull.className = "btn btn-sm btn-outline";
      } else {
        modeBadge.className = "badge badge-yellow";
        modeBadge.innerText = "🧠 Full Hybrid Mode";
        if (modeDesc) modeDesc.innerText = "Full hybrid search: dense vector embeddings, LLM query expansion, and cross-encoder neural reranking.";
        if (btnCpu) btnCpu.className = "btn btn-sm btn-outline";
        if (btnFull) btnFull.className = "btn btn-sm btn-primary";
      }
    }

    // 2. Update Corpus Counts
    const c = data.corpus;
    document.getElementById("stat-total").innerText = c.total || 0;
    document.getElementById("stat-notes").innerText = c.notes || 0;
    document.getElementById("stat-wiki").innerText = c.wiki || 0;
    document.getElementById("stat-github").innerText = c.github || 0;
    document.getElementById("stat-chats").innerText = c.chats || 0;
    document.getElementById("stat-pdfs").innerText = c.pdfs || 0;
    document.getElementById("stat-web").innerText = c.web || 0;
    document.getElementById("stat-twitter").innerText = c.twitter || 0;

    // 3. Update Task Status
    const task = data.task;
    const taskBadge = document.getElementById("task-badge");
    const stopBtn = document.getElementById("btn-stop-task");

    if (task.running) {
      taskBadge.className = "badge badge-yellow";
      taskBadge.innerText = `Running: ${task.action} (${task.elapsed_seconds}s)`;
      stopBtn.style.display = "inline-block";
    } else {
      if (task.exit_code === 0) {
        taskBadge.className = "badge badge-green";
        taskBadge.innerText = `Completed: ${task.action}`;
      } else if (task.exit_code !== null && task.exit_code !== undefined) {
        taskBadge.className = "badge badge-red";
        taskBadge.innerText = `Failed: ${task.action} (exit ${task.exit_code})`;
      } else {
        taskBadge.className = "badge badge-gray";
        taskBadge.innerText = "Idle";
      }
      stopBtn.style.display = "none";
    }
  } catch (e) {
    console.error("Status fetch error:", e);
  }
}

function updateBadge(id, isOk) {
  const el = document.getElementById(id);
  if (!el) return;
  if (isOk) {
    el.className = "badge badge-green";
    el.innerText = "Active";
  } else {
    el.className = "badge badge-red";
    el.innerText = "Inactive";
  }
}

// Log Filter Switcher
function setLogFilter(filter) {
  currentFilter = filter;
  const buttons = ["filter-all", "filter-user-actions", "filter-daemons", "filter-pipelines", "filter-errors"];
  buttons.forEach(bId => {
    const btn = document.getElementById(bId);
    if (btn) btn.classList.remove("active");
  });

  const activeMap = {
    "ALL": "filter-all",
    "USER_ACTION": "filter-user-actions",
    "DAEMONS": "filter-daemons",
    "PIPELINES": "filter-pipelines",
    "ERRORS": "filter-errors",
  };
  const activeBtn = document.getElementById(activeMap[filter]);
  if (activeBtn) activeBtn.classList.add("active");

  renderLogs();
}

function getBadgeClassForSource(source) {
  const s = (source || "").toLowerCase();
  if (s.includes("user_action") || s.includes("user")) return "badge-user_action";
  if (s.includes("qmd")) return "badge-qmd";
  if (s.includes("proxy") || s.includes("auth")) return "badge-auth_proxy";
  if (s.includes("tunnel")) return "badge-tunnel";
  if (s.includes("pipeline") || s.includes("task")) return "badge-pipeline";
  if (s.includes("supervisor")) return "badge-supervisor";
  return "badge-system";
}

// Render log entries in terminal based on active filter
function renderLogs() {
  const terminal = document.getElementById("terminal");
  if (!terminal) return;

  const filtered = allLogEntries.filter(entry => {
    const src = (entry.source || "").toUpperCase();
    const lvl = (entry.level || "").toUpperCase();
    const msg = (entry.message || "").toLowerCase();

    if (currentFilter === "USER_ACTION") {
      return src === "USER_ACTION";
    }
    if (currentFilter === "DAEMONS") {
      return ["QMD", "AUTH_PROXY", "TUNNEL", "SUPERVISOR"].includes(src);
    }
    if (currentFilter === "PIPELINES") {
      return ["PIPELINE", "TASK"].includes(src);
    }
    if (currentFilter === "ERRORS") {
      return lvl === "ERROR" || lvl === "WARNING" || msg.includes("error") || msg.includes("exception") || msg.includes("failed");
    }
    return true; // ALL
  });

  const countIndicator = document.getElementById("log-count-indicator");
  if (countIndicator) {
    countIndicator.innerText = `${filtered.length} / ${allLogEntries.length} entries`;
  }

  terminal.innerHTML = "";
  if (filtered.length === 0) {
    const empty = document.createElement("div");
    empty.className = "terminal-line text-muted";
    empty.textContent = `[System] No log entries matching filter '${currentFilter}'.`;
    terminal.appendChild(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  filtered.forEach(entry => {
    const div = document.createElement("div");
    const isErr = entry.level === "ERROR" || (entry.message && entry.message.toLowerCase().includes("error:"));
    const isWarn = entry.level === "WARNING";
    const isAudit = (entry.source || "").toUpperCase() === "USER_ACTION";
    div.className = `terminal-entry ${isErr ? "entry-error" : isWarn ? "entry-warning" : isAudit ? "entry-audit" : ""}`;

    const timeStr = (entry.time || "").split(" ")[1] || entry.time || "";
    const badgeClass = getBadgeClassForSource(entry.source);

    let html = `<span class="log-time">[${escapeHtml(timeStr)}]</span>`;
    html += `<span class="log-chip ${badgeClass}">${escapeHtml(entry.source || "SYS")}</span>`;
    if (isErr) {
      html += `<span class="log-chip badge-error">ERR</span>`;
    } else if (isWarn) {
      html += `<span class="log-chip badge-warning">WARN</span>`;
    }
    html += `<span class="log-msg" style="white-space: pre-wrap;">${escapeHtml(entry.message || entry.raw || "")}</span>`;


    div.innerHTML = html;
    fragment.appendChild(div);
  });

  terminal.appendChild(fragment);

  const auto = document.getElementById("autoscroll");
  if (auto && auto.checked) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

// Fetch streaming execution logs continuously
async function pollLogs() {
  try {
    const res = await fetch(`/api/logs?since=${lastLogId}`);
    if (!res.ok) return;
    const data = await res.json();

    let hasNew = false;
    if (data.entries && data.entries.length > 0) {
      data.entries.forEach(entry => {
        allLogEntries.push(entry);
      });
      if (allLogEntries.length > MAX_LOG_ENTRIES) {
        allLogEntries = allLogEntries.slice(allLogEntries.length - MAX_LOG_ENTRIES);
      }
      lastLogId = data.last_id || (data.entries[data.entries.length - 1].id) || lastLogId;
      hasNew = true;
    } else if (data.logs && data.logs.length > 0 && (!data.entries || data.entries.length === 0)) {
      data.logs.forEach(line => {
        allLogEntries.push({
          id: ++lastLogId,
          time: new Date().toLocaleTimeString(),
          source: "SYSTEM",
          level: line.toLowerCase().includes("error") ? "ERROR" : "INFO",
          message: line,
          raw: line
        });
      });
      hasNew = true;
    }

    if (hasNew) {
      renderLogs();
    }
  } catch (e) {
    console.error("Log poll error:", e);
  }
}

function clearLogs() {
  allLogEntries = [];
  renderLogs();
}

// Trigger Pipeline Action
async function runAction(action) {
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || "Action failed to start", true);
    } else {
      showToast(`Started: ${action}`);
      pollLogs();
      fetchStatus();
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

async function stopTask() {
  try {
    await fetch("/api/stop", { method: "POST" });
    showToast("Stop requested");
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

// Control Daemons
async function controlDaemon(daemon, action) {
  try {
    showToast(`${action} ${daemon}...`);
    const res = await fetch("/api/daemons", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ daemon, action })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Daemon ${daemon}: ${action} triggered`);
      setTimeout(fetchStatus, 1500);
    } else {
      showToast(data.message || data.error || "Failed", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

// Engine Mode Switcher
async function switchEngineMode(mode) {
  try {
    showToast(`Switching engine mode to ${mode}...`);
    const res = await fetch("/api/engine/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Engine mode switched to ${mode.toUpperCase()} (services reloaded)`);
      setTimeout(fetchStatus, 1000);
    } else {
      showToast(data.error || "Failed to switch engine mode", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

// Interactive Search Tester
async function executeSearch() {
  const q = document.getElementById("search-query").value.trim();
  const siloEl = document.getElementById("search-silo");
  const silo = siloEl ? siloEl.value.trim() : "all";
  const filterInput = document.getElementById("search-filter");
  const filterVal = filterInput ? filterInput.value.trim() : "";
  const synthCheck = document.getElementById("search-synthesize");
  const synthesize = synthCheck ? synthCheck.checked : false;
  if (!q) return;

  const btn = document.getElementById("btn-search");
  btn.disabled = true;
  btn.innerText = synthesize ? "Synthesizing..." : "Searching...";

  try {
    let url = `/api/search?q=${encodeURIComponent(q)}`;
    if (silo && silo !== "all") {
      url += `&silo=${encodeURIComponent(silo)}`;
    }
    if (filterVal) {
      url += `&filter=${encodeURIComponent(filterVal)}`;
    }
    if (synthesize) {
      url += `&synthesize=true`;
    }
    const res = await fetch(url);
    const data = await res.json();
    const box = document.getElementById("search-results-box");
    const pre = document.getElementById("search-raw-output");
    const synthBox = document.getElementById("search-synthesis-container");
    const synthOut = document.getElementById("search-synthesis-output");

    box.style.display = "block";
    if (res.ok) {
      pre.textContent = data.output || "No matches found.";
      if (synthBox && synthOut) {
        if (data.synthesis) {
          synthBox.style.display = "block";
          synthOut.textContent = data.synthesis;
        } else {
          synthBox.style.display = "none";
        }
      }
    } else {
      pre.textContent = `Error: ${data.error}`;
      if (synthBox) synthBox.style.display = "none";
    }
  } catch (e) {
    showToast(`Search error: ${e}`, true);
  } finally {
    btn.disabled = false;
    btn.innerText = "Search QMD";
  }
}


// Drag and Drop Uploads
function setupDropzone() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");

  ["dragenter", "dragover"].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag-over");
    });
  });

  dropzone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (files.length) uploadFiles(files);
  });

  fileInput.addEventListener("change", (e) => {
    if (fileInput.files.length) uploadFiles(fileInput.files);
  });
}

async function uploadFiles(files) {
  const list = document.getElementById("upload-status-list");

  for (const file of files) {
    const item = document.createElement("div");
    item.className = "upload-item";
    item.innerHTML = `<span>Uploading: <strong>${file.name}</strong> (${(file.size / 1024).toFixed(1)} KB)...</span>`;
    list.prepend(item);

    try {
      const res = await fetch("/api/upload", {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Filename": file.name
        },
        body: file
      });
      const data = await res.json();
      if (res.ok) {
        item.innerHTML = `<span>✓ <strong>${file.name}</strong> placed in <code>${data.target_dir}/</code></span><span class="badge badge-green">Ready</span>`;
        showToast(`Uploaded ${file.name}`);
        fetchStatus();
      } else {
        item.innerHTML = `<span>✗ Failed to upload ${file.name}</span><span class="badge badge-red">Error</span>`;
      }
    } catch (e) {
      item.innerHTML = `<span>✗ Error uploading ${file.name}: ${e}</span>`;
    }
  }
}

// Settings Modal Management
async function openSettings() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    const cfg = data.config || {};

    for (const [k, v] of Object.entries(cfg)) {
      const el = document.getElementById(`cfg-${k}`);
      if (el) el.value = v;
    }
    document.getElementById("settings-modal").style.display = "flex";
  } catch (e) {
    showToast(`Error loading settings: ${e}`, true);
  }
}

function closeSettings() {
  document.getElementById("settings-modal").style.display = "none";
}

function togglePassword(id) {
  const input = document.getElementById(id);
  input.type = input.type === "password" ? "text" : "password";
}

async function saveSettings() {
  const btn = document.getElementById("btn-save-settings");
  btn.disabled = true;
  btn.innerText = "Saving...";

  const fields = [
    "AUTH_PROXY_TOKEN", "TUNNEL_URL", "TUNNEL_TOKEN", "GITHUB_TOKEN",
    "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "MIRROR_TOKEN", "MIRROR_HOST",
    "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME", "TWITTER_BEARER_TOKEN", "MODAL_TOKEN_ID",
    "MODAL_TOKEN_SECRET", "E2B_API_KEY"
  ];


  const updates = {};
  fields.forEach(f => {
    const el = document.getElementById(`cfg-${f}`);
    if (el) updates[f] = el.value.trim();
  });

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates })
    });
    if (res.ok) {
      showToast("Configurations saved successfully!");
      closeSettings();
      fetchStatus();
    } else {
      showToast("Failed to save settings", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  } finally {
    btn.disabled = false;
    btn.innerText = "Save Configurations";
  }
}

// Persona & Prompts Management
async function openPrompts() {
  try {
    const res = await fetch("/api/prompts");
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || "Failed to load prompts", true);
      return;
    }

    document.getElementById("prompt-soul-editor").value = data.soul || "";
    document.getElementById("prompt-sys-editor").value = data.system_prompt || "";
    document.getElementById("prompt-preview-view").textContent = data.synthesized || "";

    const tplList = document.getElementById("prompt-templates-list");
    tplList.innerHTML = "";
    (data.templates || []).forEach(tpl => {
      const card = document.createElement("div");
      card.className = "card";
      card.style.padding = "10px 14px";
      card.style.background = "rgba(255,255,255,0.03)";
      card.style.border = "1px solid rgba(255,255,255,0.08)";
      card.style.borderRadius = "6px";
      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <strong style="color:var(--accent); font-family:monospace; font-size:0.95rem;">${escapeHtml(tpl.name)}</strong>
          <div style="display:flex; gap:6px; align-items:center;">
            <button type="button" class="btn btn-xs btn-outline" onclick="runPromptInPi('${escapeHtml(tpl.name)}')">⚡ Run in Pi Agent</button>
            <span class="badge badge-gray" style="font-size:10px;">MCP Prompt</span>
          </div>
        </div>
        <p style="margin:4px 0 6px 0; font-size:0.82rem; color:var(--text);">${escapeHtml(tpl.description)}</p>
        <div style="font-size:0.75rem; color:var(--text-muted); font-family:monospace;">
          Arguments: ${(tpl.arguments || []).map(a => `<span style="background:rgba(255,255,255,0.08); padding:2px 6px; border-radius:4px; margin-right:4px;">${escapeHtml(a.name)}${a.required ? '*' : ''}</span>`).join(" ")}
        </div>
      `;
      tplList.appendChild(card);
    });

    // Load Skills & Progressive Tools
    try {
      const skillsRes = await fetch("/api/skills");
      const skillsData = await skillsRes.json();
      const skillsList = document.getElementById("skills-catalog-list");
      if (skillsList && skillsData.skills) {
        skillsList.innerHTML = "";
        skillsData.skills.forEach(s => {
          const item = document.createElement("div");
          item.className = "card";
          item.style.padding = "8px 12px";
          item.style.background = "rgba(255,255,255,0.03)";
          item.style.border = "1px solid rgba(255,255,255,0.08)";
          item.style.borderRadius = "6px";
          item.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <strong style="color:var(--primary); font-family:monospace; font-size:0.9rem;">🧩 ${escapeHtml(s.name)}</strong>
              <div style="display:flex; gap:6px; align-items:center;">
                <button type="button" class="btn btn-xs btn-outline" onclick="runSkillInPi('${escapeHtml(s.name)}')">⚡ Activate in Pi</button>
                <span class="badge badge-green" style="font-size:10px;">Tier 1 Active</span>
              </div>
            </div>
            <p style="margin:4px 0 0 0; font-size:0.8rem; color:var(--text);">${escapeHtml(s.description)}</p>
          `;
          skillsList.appendChild(item);
        });
      }

      const toolsRes = await fetch("/api/tools");
      const toolsData = await toolsRes.json();
      const toolsList = document.getElementById("progressive-tools-list");
      if (toolsList && toolsData.progressive_manifest) {
        toolsList.innerHTML = "";
        toolsData.progressive_manifest.forEach(t => {
          const tItem = document.createElement("div");
          tItem.className = "card";
          tItem.style.padding = "8px 12px";
          tItem.style.background = "rgba(255,255,255,0.03)";
          tItem.style.border = "1px solid rgba(255,255,255,0.08)";
          tItem.style.borderRadius = "6px";
          tItem.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <strong style="color:var(--accent-blue, #60a5fa); font-family:monospace; font-size:0.88rem;">⚡ ${escapeHtml(t.name)}</strong>
              <span class="badge badge-gray" style="font-size:10px;">Bridge Tool</span>
            </div>
            <p style="margin:4px 0 0 0; font-size:0.78rem; color:var(--text-muted);">${escapeHtml(t.description)}</p>
          `;
          toolsList.appendChild(tItem);
        });
      }
    } catch (err) {
      console.warn("Failed to load skills/tools:", err);
    }

    switchPromptTab("soul");
    document.getElementById("prompts-modal").style.display = "flex";
  } catch (e) {
    showToast(`Error loading prompts: ${e}`, true);
  }
}

function runPromptInPi(promptName) {
  closePrompts();
  const input = document.getElementById("input-pi-prompt");
  if (input) {
    input.value = `Execute MCP prompt template '${promptName}' across my knowledgebase.`;
    input.focus();
  }
}

function runSkillInPi(skillName) {
  closePrompts();
  const input = document.getElementById("input-pi-prompt");
  if (input) {
    input.value = `Activate skill '${skillName}' and follow its instructions to inspect my knowledgebase.`;
    input.focus();
  }
}

function toggleAddPromptForm() {
  const f = document.getElementById("add-prompt-form");
  if (f) f.style.display = f.style.display === "none" ? "block" : "none";
}

async function submitNewPromptTemplate() {
  const name = document.getElementById("new-prompt-name").value.trim();
  const desc = document.getElementById("new-prompt-desc").value.trim();
  const argsRaw = document.getElementById("new-prompt-args").value.trim();
  const content = document.getElementById("new-prompt-content").value.trim();

  if (!name || !content) {
    showToast("Template Name and Content are required", true);
    return;
  }

  const argsList = argsRaw ? argsRaw.split(",").map(a => ({ name: a.trim(), description: a.trim(), required: true })) : [];

  try {
    const res = await fetch("/api/prompts/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: desc, arguments: argsList, content })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Prompt template '${name}' created!`);
      toggleAddPromptForm();
      openPrompts();
    } else {
      showToast(data.error || "Failed to create prompt template", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

function toggleAddSkillForm() {
  const f = document.getElementById("add-skill-form");
  if (f) f.style.display = f.style.display === "none" ? "block" : "none";
}

async function submitNewSkill() {
  const name = document.getElementById("new-skill-name").value.trim();
  const desc = document.getElementById("new-skill-desc").value.trim();
  const content = document.getElementById("new-skill-content").value.trim();

  if (!name || !content) {
    showToast("Skill Name and Content are required", true);
    return;
  }

  try {
    const res = await fetch("/api/skills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: desc, content })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Skill '${name}' created successfully!`);
      toggleAddSkillForm();
      openPrompts();
    } else {
      showToast(data.error || "Failed to create skill", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

function toggleAddToolForm() {
  const f = document.getElementById("add-tool-form");
  if (f) f.style.display = f.style.display === "none" ? "block" : "none";
}

async function submitNewTool() {
  const name = document.getElementById("new-tool-name").value.trim();
  const desc = document.getElementById("new-tool-desc").value.trim();
  const schemaRaw = document.getElementById("new-tool-schema").value.trim();

  if (!name) {
    showToast("Tool Name is required", true);
    return;
  }

  let schema = { type: "object", properties: {} };
  if (schemaRaw) {
    try {
      schema = JSON.parse(schemaRaw);
    } catch (e) {
      showToast("Invalid JSON schema syntax", true);
      return;
    }
  }

  try {
    const res = await fetch("/api/tools", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: desc, inputSchema: schema })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Tool '${name}' registered successfully!`);
      toggleAddToolForm();
      openPrompts();
    } else {
      showToast(data.error || "Failed to register tool", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}


function closePrompts() {
  document.getElementById("prompts-modal").style.display = "none";
}

function switchPromptTab(tabName) {
  const tabs = ["soul", "system", "preview", "templates", "skills"];
  tabs.forEach(t => {
    const btn = document.getElementById(`tab-btn-${t}`);
    const panel = document.getElementById(`tab-content-${t}`);
    if (btn) {
      if (t === tabName) btn.classList.add("active");
      else btn.classList.remove("active");
    }
    if (panel) {
      panel.style.display = (t === tabName) ? "block" : "none";
    }
  });
}

async function savePrompts() {
  const btn = document.getElementById("btn-save-prompts");
  btn.disabled = true;
  btn.innerText = "Saving...";

  const soul = document.getElementById("prompt-soul-editor").value;
  const system_prompt = document.getElementById("prompt-sys-editor").value;

  try {
    const res = await fetch("/api/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ soul, system_prompt })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Persona & Prompts updated successfully!");
      closePrompts();
    } else {
      showToast(data.error || "Failed to save prompts", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  } finally {
    btn.disabled = false;
    btn.innerText = "Save Persona & Prompts";
  }
}

// Agent-Reach & URL Ingestion
async function ingestReachUrl() {
  const urlInput = document.getElementById("reach-url");
  const channelSelect = document.getElementById("reach-channel");
  const transcribeCheckbox = document.getElementById("reach-transcribe");
  const btn = document.getElementById("btn-reach-ingest");
  const resultBox = document.getElementById("reach-result-box");
  const resultContent = document.getElementById("reach-result-content");

  const url = urlInput.value.trim();
  if (!url) return;

  const channel = channelSelect ? channelSelect.value : "auto";
  const transcribe = transcribeCheckbox ? transcribeCheckbox.checked : false;

  btn.disabled = true;
  btn.innerText = "⏳ Ingesting...";
  resultBox.style.display = "block";
  resultContent.innerHTML = `<span style="color: var(--text-muted);">Fetching and parsing <code>${escapeHtml(url)}</code>...</span>`;

  try {
    const res = await fetch("/api/connectors/reach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, type: channel, transcribe }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "Ingestion failed");
    }

    resultContent.innerHTML = `
      <div style="color: var(--success); font-weight: 600; margin-bottom: 6px;">
        ✅ Successfully Ingested into <code>corpus/${escapeHtml(data.silo)}/</code>!
      </div>
      <div style="font-size: 0.9rem; margin-bottom: 4px;"><strong>Title:</strong> ${escapeHtml(data.title)}</div>
      <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 4px;"><strong>Summary:</strong> ${escapeHtml(data.summary)}</div>
      <div style="font-size: 0.8rem; font-family: monospace; color: var(--primary);">File: ${escapeHtml(data.file)}</div>
    `;
    urlInput.value = "";
    showToast("URL ingested into knowledgebase!");
    fetchStatus();
  } catch (err) {
    resultContent.innerHTML = `
      <div style="color: var(--danger); font-weight: 600;">
        ❌ Ingestion Error: ${escapeHtml(err.message)}
      </div>
    `;
    showToast(`Ingestion failed: ${err.message}`, true);
  } finally {
    btn.disabled = false;
    btn.innerText = "⚡ Ingest URL";
  }
}

// ----------------------------------------------------------------------
// Automations & Crons (Feature 6)
// ----------------------------------------------------------------------

function onAutoActionChange() {
  const action = document.getElementById("auto-action").value;
  const nameInput = document.getElementById("auto-name");
  const reachUrl = document.getElementById("auto-reach-url");

  const actionNames = {
    "ingest_inbox": "Automatic Inbox Ingestion",
    "github_sync": "GitHub Repositories Tracking Sync",
    "reindex": "Vector & BM25 Store Reindex",
    "deploy_mirror": "Cloudflare Pages Mirror Deployment",
    "compile_wiki": "Workers AI Wiki Hub Synthesis",
    "reach_ingest": "Agent-Reach Scheduled URL Ingest"
  };
  if (nameInput) {
    nameInput.value = actionNames[action] || "Custom Task";
  }
  if (reachUrl) {
    reachUrl.style.display = (action === "reach_ingest") ? "block" : "none";
  }
}

function onAutoScheduleChange() {
  const sched = document.getElementById("auto-schedule").value;
  const customInput = document.getElementById("auto-custom-cron");
  if (customInput) {
    customInput.style.display = (sched === "custom") ? "block" : "none";
  }
}

async function fetchAutomations() {
  try {
    const res = await fetch("/api/automations");
    if (!res.ok) return;
    const data = await res.json();
    renderAutomations(data.automations || []);
  } catch (err) {
    console.warn("Failed to fetch automations:", err);
  }
}

function renderAutomations(list) {
  const countEl = document.getElementById("auto-count");
  if (countEl) countEl.innerText = list.length;

  const tbody = document.getElementById("automations-table-body");
  if (!tbody) return;

  if (list.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="padding: 16px; text-align: center; color: var(--text-muted);">No automations configured.</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  list.forEach(job => {
    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid rgba(255,255,255,0.05)";

    const statusBadge = getStatusBadge(job.last_status);
    const tierBadge = job.tier === "cloud"
      ? `<span class="badge badge-purple" style="font-size:10px;">☁️ Cloud</span>`
      : `<span class="badge badge-gray" style="font-size:10px;">💻 Local</span>`;

    const lastRunText = job.last_run_at ? new Date(job.last_run_at).toLocaleTimeString() : "Never";
    const nextRunText = job.next_run_at ? new Date(job.next_run_at).toLocaleTimeString() : "-";

    tr.innerHTML = `
      <td style="padding: 10px 6px;">
        <strong style="color: var(--text);">${escapeHtml(job.name)}</strong>
        <div style="font-size: 0.78rem; color: var(--text-muted); font-family: monospace;">${escapeHtml(job.action)}</div>
      </td>
      <td style="padding: 10px 6px; font-family: monospace; font-size: 0.85rem; color: var(--accent-blue, #60a5fa);">
        ${escapeHtml(job.schedule)}
      </td>
      <td style="padding: 10px 6px;">${tierBadge}</td>
      <td style="padding: 10px 6px; font-size: 0.82rem; color: var(--text-muted);">${lastRunText}</td>
      <td style="padding: 10px 6px; font-size: 0.82rem; color: var(--text); font-weight: 500;">${nextRunText}</td>
      <td style="padding: 10px 6px;">${statusBadge}</td>
      <td style="padding: 10px 6px; text-align: right;">
        <div style="display: inline-flex; gap: 6px; align-items: center;">
          <button class="btn btn-xs ${job.enabled ? 'btn-outline' : 'btn-secondary'}" onclick="toggleAutomation('${job.id}')" title="${job.enabled ? 'Pause automation' : 'Enable automation'}">
            ${job.enabled ? '🟢 Active' : '⏸️ Paused'}
          </button>
          <button class="btn btn-xs btn-primary" onclick="triggerAutomation('${job.id}')" id="btn-trigger-${job.id}" title="Run now">
            ⚡ Run
          </button>
          <button class="btn btn-xs btn-outline" style="color: var(--danger); border-color: rgba(239,68,68,0.3);" onclick="deleteAutomation('${job.id}')" title="Delete automation">
            🗑️
          </button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function getStatusBadge(status) {
  if (status === "success") {
    return `<span class="badge badge-green" style="font-size:10px;">🟢 Success</span>`;
  } else if (status === "running") {
    return `<span class="badge badge-yellow" style="font-size:10px;">🟡 Running...</span>`;
  } else if (status === "failed") {
    return `<span class="badge badge-red" style="font-size:10px;">🔴 Failed</span>`;
  }
  return `<span class="badge badge-gray" style="font-size:10px;">⚪ Idle</span>`;
}

async function createAutomation() {
  const action = document.getElementById("auto-action").value;
  const schedSelect = document.getElementById("auto-schedule").value;
  const customCron = document.getElementById("auto-custom-cron").value.trim();
  const schedule = (schedSelect === "custom" && customCron) ? customCron : schedSelect;
  const tier = document.getElementById("auto-tier").value;
  const name = document.getElementById("auto-name").value.trim();
  const reachUrl = document.getElementById("auto-reach-url").value.trim();

  const params = {};
  if (action === "reach_ingest" && reachUrl) {
    params.url = reachUrl;
  }

  const btn = document.getElementById("btn-save-automation");
  btn.disabled = true;
  btn.innerText = "Adding...";

  try {
    const res = await fetch("/api/automations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, action, schedule, tier, params, enabled: true })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Automation '${name}' added!`);
      fetchAutomations();
    } else {
      showToast(data.error || "Failed to create automation", true);
    }
  } catch (err) {
    showToast(`Error: ${err}`, true);
  } finally {
    btn.disabled = false;
    btn.innerText = "➕ Add Schedule";
  }
}

async function toggleAutomation(id) {
  try {
    const res = await fetch(`/api/automations/${id}/toggle`, { method: "POST" });
    if (res.ok) {
      fetchAutomations();
    } else {
      const data = await res.json();
      showToast(data.error || "Toggle failed", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

async function triggerAutomation(id) {
  const btn = document.getElementById(`btn-trigger-${id}`);
  if (btn) {
    btn.disabled = true;
    btn.innerText = "⏳";
  }
  try {
    const res = await fetch(`/api/automations/${id}/trigger`, { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast(`Automation triggered: ${data.result.success ? 'Success' : 'Failed'}`);
      fetchAutomations();
    } else {
      showToast(data.error || "Trigger failed", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "⚡ Run";
    }
  }
}

async function deleteAutomation(id) {
  if (!confirm(`Delete automation schedule '${id}'?`)) return;
  try {
    const res = await fetch(`/api/automations/${id}`, { method: "DELETE" });
    if (res.ok) {
      showToast("Automation deleted");
      fetchAutomations();
    } else {
      const data = await res.json();
      showToast(data.error || "Delete failed", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

// ======================================================================
// 3-Tier Operational Mode
// ======================================================================

async function fetchOperationalMode() {
  try {
    const res = await fetch("/api/engine/operational-mode");
    if (!res.ok) return;
    const data = await res.json();
    const mode = data.operational_mode || "full";

    const badge = document.getElementById("badge-operational-mode");
    const desc = document.getElementById("desc-operational-mode");
    const btnOffline = document.getElementById("btn-op-offline");
    const btnWiki = document.getElementById("btn-op-wiki");
    const btnFull = document.getElementById("btn-op-full");

    if (btnOffline) btnOffline.className = mode === "offline-only" ? "btn btn-sm btn-primary" : "btn btn-sm btn-outline";
    if (btnWiki) btnWiki.className = mode === "offline+cloudflare-wiki" ? "btn btn-sm btn-primary" : "btn btn-sm btn-outline";
    if (btnFull) btnFull.className = mode === "full" ? "btn btn-sm btn-primary" : "btn btn-sm btn-outline";

    if (badge) {
      if (mode === "offline-only") {
        badge.className = "badge badge-green";
        badge.innerText = "🔒 Offline Only";
        if (desc) desc.innerText = "100% on-device. Local GGUF models via llama.cpp + local Pi ReAct + SQLite index. Zero network calls.";
      } else if (mode === "offline+cloudflare-wiki") {
        badge.className = "badge badge-blue";
        badge.innerText = "🧠 Offline + CF Wiki";
        if (desc) desc.innerText = "Local search and Pi agent execution, plus Cloudflare Workers AI for cross-silo wiki synthesis & topic hub compilation.";
      } else {
        badge.className = "badge badge-yellow";
        badge.innerText = "🌐 Full Cloud Connected";
        if (desc) desc.innerText = "Everything enabled: Cloudflare Artifacts (Git versioning), Cloudflare R2 binary snapshots, and cloud models.";
      }
    }
  } catch (e) {
    console.warn("fetchOperationalMode error:", e);
  }
}

async function switchOperationalMode(mode) {
  try {
    const res = await fetch("/api/engine/operational-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Operational mode switched to: ${mode}`);
      fetchOperationalMode();
      fetchSyncStatus();
    } else {
      showToast(data.error || "Mode switch failed", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

// ======================================================================
// Cloudflare Artifacts (Git Versioning) & R2 Sync
// ======================================================================

async function fetchSyncStatus() {
  try {
    const res = await fetch("/api/sync/status");
    if (!res.ok) return;
    const data = await res.json();

    const repoElem = document.getElementById("sync-artifacts-repo");
    const bucketElem = document.getElementById("sync-r2-bucket");
    const statusBadge = document.getElementById("sync-status-badge");

    if (repoElem) repoElem.innerText = data.artifacts_repo || "qmd/corpus";
    if (bucketElem) bucketElem.innerText = data.r2_bucket || "qmd-knowledgebase";
    if (statusBadge) {
      if (data.cloud_sync_enabled) {
        statusBadge.className = "badge badge-green";
        statusBadge.innerText = "Active";
      } else {
        statusBadge.className = "badge badge-gray";
        statusBadge.innerText = "Blocked (Offline Mode)";
      }
    }

    // Render history
    const tbody = document.getElementById("sync-history-tbody");
    if (tbody && data.recent_commits) {
      if (data.recent_commits.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="padding: 10px; text-align: center; color: var(--text-muted);">No version history commits recorded yet.</td></tr>';
      } else {
        tbody.innerHTML = data.recent_commits.map(c => `
          <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
            <td style="padding: 6px 10px; font-family: monospace; color: var(--accent);">${escapeHtml(c.commit ? c.commit.slice(0, 7) : 'head')}</td>
            <td style="padding: 6px 10px;">${escapeHtml(c.message || '')}</td>
            <td style="padding: 6px 10px; font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(c.date ? c.date.slice(0, 19) : '')}</td>
            <td style="padding: 6px 10px; text-align: right;">
              <button class="btn btn-xs btn-outline" onclick="revertCommit('${c.commit}')">Rollback</button>
            </td>
          </tr>
        `).join("");
      }
    }
  } catch (e) {
    console.warn("fetchSyncStatus error:", e);
  }
}

async function triggerSync() {
  const btn = document.getElementById("btn-trigger-sync");
  if (btn) {
    btn.disabled = true;
    btn.innerText = "⏳ Syncing...";
  }
  try {
    const res = await fetch("/api/sync/trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "Manual 1-click sync from Web Control Plane" }),
    });
    const data = await res.json();
    if (data.status === "blocked") {
      showToast(`Sync blocked: ${data.message}`, true);
    } else {
      showToast("Sync completed successfully!");
      fetchSyncStatus();
    }
  } catch (e) {
    showToast(`Sync error: ${e}`, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "☁️ 1-Click Sync";
    }
  }
}

async function revertCommit(commitHash) {
  if (!confirm(`Revert knowledgebase corpus state back to commit ${commitHash.slice(0, 7)}?`)) return;
  try {
    const res = await fetch("/api/sync/revert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ commit: commitHash }),
    });
    const data = await res.json();
    if (res.ok && data.status === "reverted") {
      showToast(`Successfully reverted to ${commitHash.slice(0, 7)}`);
      fetchSyncStatus();
    } else {
      showToast(data.message || "Revert failed", true);
    }
  } catch (e) {
    showToast(`Error: ${e}`, true);
  }
}

// ======================================================================
// Pi Agent Autonomous Execution Console
// ======================================================================

async function fetchPiStatus() {
  try {
    const res = await fetch("/api/pi/status");
    if (!res.ok) return;
    const data = await res.json();
    const badge = document.getElementById("badge-pi-engine");
    if (badge && data.is_running) {
      badge.className = "badge badge-purple";
      badge.innerText = `Pi Agent (${data.mode})`;
    }
  } catch (e) {
    console.warn("fetchPiStatus error:", e);
  }
}

let piEventPollTimer = null;
let lastPiEventId = 0;

async function pollPiEvents() {
  try {
    const res = await fetch(`/api/pi/events?since=${lastPiEventId}`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.events && data.events.length > 0) {
      lastPiEventId = data.last_id;
      const container = document.getElementById("pi-output-container");
      if (!container) return;

      data.events.forEach(evt => {
        const div = document.createElement("div");
        div.style.marginBottom = "4px";
        if (evt.type === "thinking_delta") {
          div.style.color = "var(--text-muted)";
          div.innerHTML = `<em>🤔 [Pi Thought] ${escapeHtml(evt.content)}</em>`;
        } else if (evt.type === "tool_start") {
          div.style.color = "var(--primary)";
          div.innerHTML = `<strong>⚡ [Tool Call: ${escapeHtml(evt.tool)}]</strong> <span style="font-size:0.8rem;">args: ${escapeHtml(JSON.stringify(evt.arguments || {}))}</span>`;
        } else if (evt.type === "tool_end") {
          div.style.color = evt.success ? "var(--success, #10b981)" : "var(--danger, #ef4444)";
          div.innerHTML = `<span>↳ [Tool Result: ${evt.success ? 'Success' : 'Failed'}] ${escapeHtml(evt.preview || '')}</span>`;
        } else if (evt.type === "message_delta") {
          div.style.color = "var(--text)";
          div.style.marginTop = "8px";
          div.innerHTML = `<strong>💡 [Pi Response]:</strong><br><div style="white-space:pre-wrap; margin-top:4px;">${escapeHtml(evt.content)}</div>`;
        }
        if (div.innerHTML) {
          container.appendChild(div);
          container.scrollTop = container.scrollHeight;
        }
      });
    }
  } catch (e) {
    console.warn("pollPiEvents error:", e);
  }
}

async function runPiGoal() {
  const input = document.getElementById("input-pi-prompt");
  const modelSelect = document.getElementById("select-pi-model");
  const btn = document.getElementById("btn-run-pi-goal");
  const progressBar = document.getElementById("pi-progress-bar");
  const container = document.getElementById("pi-output-container");

  const prompt = (input ? input.value : "").trim();
  if (!prompt) {
    showToast("Please enter a goal or question for Pi Agent", true);
    return;
  }

  const model = modelSelect ? modelSelect.value : "local-gguf";

  if (btn) {
    btn.disabled = true;
    btn.innerText = "⏳ Executing...";
  }
  if (progressBar) progressBar.style.display = "block";
  if (container) {
    container.innerHTML = `<div style="color: var(--accent);">🚀 Launching goal: "${escapeHtml(prompt)}"...</div>`;
  }

  // Start polling events
  if (piEventPollTimer) clearInterval(piEventPollTimer);
  piEventPollTimer = setInterval(pollPiEvents, 300);

  try {
    const res = await fetch("/api/pi/goal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, model }),
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Pi Agent completed goal!");
    } else {
      showToast(data.error || "Goal execution failed", true);
    }
  } catch (e) {
    showToast(`Execution error: ${e}`, true);
  } finally {
    setTimeout(() => {
      pollPiEvents();
      if (piEventPollTimer) clearInterval(piEventPollTimer);
      if (progressBar) progressBar.style.display = "none";
      if (btn) {
        btn.disabled = false;
        btn.innerText = "⚡ Execute Goal";
      }
    }, 1000);
  }
// Onboarding / Quickstart Wizard Controller
let selectedWizardMode = "offline-only";
let currentWizardStep = 1;

async function checkOnboardingStatus() {
  try {
    const res = await fetch("/api/onboarding/status");
    if (!res.ok) return;
    const data = await res.json();
    const banner = document.getElementById("onboarding-banner");
    if (data.needs_setup) {
      if (banner) banner.style.display = "flex";
    } else {
      if (banner) banner.style.display = "none";
    }
  } catch (e) {
    console.error("Error checking onboarding status:", e);
  }
}

function openWizard() {
  currentWizardStep = 1;
  goToWizardStep(1);
  const modal = document.getElementById("onboarding-modal");
  if (modal) modal.style.display = "flex";
}

function closeWizard() {
  const modal = document.getElementById("onboarding-modal");
  if (modal) modal.style.display = "none";
}

function dismissOnboardingBanner() {
  const banner = document.getElementById("onboarding-banner");
  if (banner) banner.style.display = "none";
}

function setWizardMode(mode) {
  selectedWizardMode = mode;
  ["offline-only", "offline+cloudflare-wiki", "full"].forEach(m => {
    const card = document.getElementById(m === "offline-only" ? "wcard-offline-only" : m === "offline+cloudflare-wiki" ? "wcard-offline-wiki" : "wcard-full");
    if (card) {
      if (m === mode) {
        card.classList.add("selected");
        const radio = card.querySelector("input[type=radio]");
        if (radio) radio.checked = true;
      } else {
        card.classList.remove("selected");
      }
    }
  });

  const summaryMode = document.getElementById("wizard-summary-mode");
  if (summaryMode) {
    if (mode === "offline-only") {
      summaryMode.className = "badge badge-green";
      summaryMode.innerText = "🔒 100% Offline Only";
    } else if (mode === "offline+cloudflare-wiki") {
      summaryMode.className = "badge badge-yellow";
      summaryMode.innerText = "🧠 Offline Search + Cloudflare Wiki";
    } else {
      summaryMode.className = "badge badge-primary";
      summaryMode.innerText = "🌐 Full Cloud Connected";
    }
  }
}

function goToWizardStep(step) {
  currentWizardStep = step;
  [1, 2, 3].forEach(s => {
    const pane = document.getElementById(`wizard-pane-${s}`);
    const ind = document.getElementById(`wizard-step-ind-${s}`);
    if (pane) pane.style.display = (s === step) ? "block" : "none";
    if (ind) {
      if (s === step) {
        ind.classList.add("active");
      } else {
        ind.classList.remove("active");
      }
    }
  });

  // Update step 3 summary if entering step 3
  if (step === 3) {
    const autoKeys = document.getElementById("wizard-auto-keys")?.checked ?? true;
    const summaryTokens = document.getElementById("wizard-summary-tokens");
    if (summaryTokens) {
      summaryTokens.innerText = autoKeys ? "⚡ Auto-Generated (Secure 256-bit Hex)" : "Custom User-Provided";
    }

    const tgVal = document.getElementById("wizard-telegram-token")?.value.trim() || "";
    const summaryBot = document.getElementById("wizard-summary-bot");
    if (summaryBot) {
      summaryBot.innerText = tgVal ? "Configured (Long-Polling Active)" : "Not configured (can add anytime)";
      summaryBot.style.color = tgVal ? "var(--success)" : "var(--text-muted)";
    }
  }
}

function toggleWizardAutoKeys() {
  const isAuto = document.getElementById("wizard-auto-keys")?.checked ?? true;
  const manualBox = document.getElementById("wizard-manual-keys");
  if (manualBox) {
    manualBox.style.display = isAuto ? "none" : "block";
  }
}

async function completeWizard() {
  const btn = document.getElementById("btn-wizard-finish");
  if (btn) {
    btn.disabled = true;
    btn.innerText = "Configuring Engine...";
  }

  const autoKeys = document.getElementById("wizard-auto-keys")?.checked ?? true;
  const customAuth = document.getElementById("wizard-custom-auth-token")?.value.trim() || "";
  const customMirror = document.getElementById("wizard-custom-mirror-token")?.value.trim() || "";
  const telegramToken = document.getElementById("wizard-telegram-token")?.value.trim() || "";

  const customTokens = {};
  if (!autoKeys) {
    if (customAuth) customTokens["AUTH_PROXY_TOKEN"] = customAuth;
    if (customMirror) customTokens["MIRROR_TOKEN"] = customMirror;
  }
  if (telegramToken) {
    customTokens["TELEGRAM_BOT_TOKEN"] = telegramToken;
  }

  try {
    const res = await fetch("/api/onboarding/quickstart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: selectedWizardMode,
        auto_generate_tokens: autoKeys,
        tokens: customTokens,
      }),
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Knowledgebase setup completed successfully! Starting services...");
      closeWizard();
      dismissOnboardingBanner();
      // Reload daemons with the new configuration
      controlDaemon("all", "restart");
      fetchStatus();
      fetchOperationalMode();
    } else {
      showToast(data.error || "Setup failed", true);
    }
  } catch (e) {
    showToast(`Error completing setup: ${e}`, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "🚀 Finish Setup & Launch Knowledgebase";
    }
  }
}
