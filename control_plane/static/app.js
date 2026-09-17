// QMD Knowledgebase Control Plane Frontend Application
let lastLogId = 0;
let currentFilter = "ALL";
let allLogEntries = [];
const MAX_LOG_ENTRIES = 3000;

document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  setInterval(fetchStatus, 3000);
  setupDropzone();

  // Start continuous real-time logging across all daemons and pipelines
  pollLogs();
  setInterval(pollLogs, 1500);

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

    // Update Mirror Link
    if (data.services.mirror.url) {
      document.getElementById("link-mirror").href = data.services.mirror.url;
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
  const buttons = ["filter-all", "filter-daemons", "filter-pipelines", "filter-errors"];
  buttons.forEach(bId => {
    const btn = document.getElementById(bId);
    if (btn) btn.classList.remove("active");
  });

  const activeMap = {
    "ALL": "filter-all",
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
    div.className = `terminal-entry ${isErr ? "entry-error" : isWarn ? "entry-warning" : ""}`;

    const timeStr = (entry.time || "").split(" ")[1] || entry.time || "";
    const badgeClass = getBadgeClassForSource(entry.source);

    let html = `<span class="log-time">[${escapeHtml(timeStr)}]</span>`;
    html += `<span class="log-chip ${badgeClass}">${escapeHtml(entry.source || "SYS")}</span>`;
    if (isErr) {
      html += `<span class="log-chip badge-error">ERR</span>`;
    } else if (isWarn) {
      html += `<span class="log-chip badge-warning">WARN</span>`;
    }
    html += `<span class="log-msg">${escapeHtml(entry.message || entry.raw || "")}</span>`;

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

// Interactive Search Tester
async function executeSearch() {
  const q = document.getElementById("search-query").value.trim();
  const filterInput = document.getElementById("search-filter");
  const filterVal = filterInput ? filterInput.value.trim() : "";
  if (!q) return;

  const btn = document.getElementById("btn-search");
  btn.disabled = true;
  btn.innerText = "Searching...";

  try {
    let url = `/api/search?q=${encodeURIComponent(q)}`;
    if (filterVal) {
      url += `&filter=${encodeURIComponent(filterVal)}`;
    }
    const res = await fetch(url);
    const data = await res.json();
    const box = document.getElementById("search-results-box");
    const pre = document.getElementById("search-raw-output");

    box.style.display = "block";
    if (res.ok) {
      pre.textContent = data.output || "No matches found.";
    } else {
      pre.textContent = `Error: ${data.error}`;
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
    "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "MIRROR_TOKEN", "MIRROR_HOST"
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
