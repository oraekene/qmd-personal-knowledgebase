// QMD Knowledgebase Control Plane Frontend Application
let lastLogIndex = 0;
let isPolling = false;

document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  setInterval(fetchStatus, 3000);
  setupDropzone();

  document.getElementById("btn-open-settings").addEventListener("click", openSettings);
  document.getElementById("btn-start-all-daemons").addEventListener("click", () => controlDaemon("all", "start"));
});

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
      pollLogs();
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
      if (isPolling) {
        pollLogs(); // fetch final lines
        isPolling = false;
      }
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

// Fetch streaming execution logs
async function pollLogs() {
  try {
    const res = await fetch(`/api/logs?since=${lastLogIndex}`);
    if (!res.ok) return;
    const data = await res.json();
    const terminal = document.getElementById("terminal");

    if (data.logs && data.logs.length > 0) {
      data.logs.forEach(line => {
        const div = document.createElement("div");
        div.className = "terminal-line";
        div.textContent = line;
        terminal.appendChild(div);
      });
      lastLogIndex = data.total;

      if (document.getElementById("autoscroll").checked) {
        terminal.scrollTop = terminal.scrollHeight;
      }
    }
  } catch (e) {
    console.error("Log poll error:", e);
  }
}

function clearLogs() {
  document.getElementById("terminal").innerHTML = "";
  lastLogIndex = 0;
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
      isPolling = true;
      lastLogIndex = 0;
      clearLogs();
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
  if (!q) return;

  const btn = document.getElementById("btn-search");
  btn.disabled = true;
  btn.innerText = "Searching...";

  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
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
