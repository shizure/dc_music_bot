const statusText = document.getElementById("statusText");
const pidText = document.getElementById("pidText");
const uptimeText = document.getElementById("uptimeText");
const exitCodeText = document.getElementById("exitCodeText");
const logsView = document.getElementById("logsView");
const messageBar = document.getElementById("messageBar");
const lastUpdated = document.getElementById("lastUpdated");

function formatUptime(seconds) {
  const s = Number(seconds || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h}h ${m}m ${sec}s`;
}

function showMessage(text, isError = false) {
  messageBar.textContent = text;
  messageBar.style.color = isError ? "#a4161a" : "#5b616a";
}

async function getStatus() {
  const res = await fetch("/api/status");
  if (!res.ok) {
    throw new Error("Failed to load status");
  }
  return res.json();
}

async function getLogs() {
  const res = await fetch("/api/logs?lines=300");
  if (!res.ok) {
    throw new Error("Failed to load logs");
  }
  return res.json();
}

async function postAction(endpoint) {
  const res = await fetch(endpoint, { method: "POST" });
  const payload = await res.json();
  if (!res.ok) {
    throw new Error(payload.message || "Request failed");
  }
  return payload;
}

function renderStatus(status) {
  if (status.running) {
    statusText.textContent = "RUNNING";
    statusText.className = "status running";
  } else {
    statusText.textContent = "STOPPED";
    statusText.className = "status stopped";
  }

  pidText.textContent = status.pid ?? "-";
  uptimeText.textContent = formatUptime(status.uptime_seconds);
  exitCodeText.textContent = status.exit_code ?? "-";
}

function renderLogs(logs) {
  logsView.textContent = logs.length ? logs.join("\n") : "No logs yet.";
  logsView.scrollTop = logsView.scrollHeight;
  lastUpdated.textContent = new Date().toLocaleTimeString();
}

async function refreshAll() {
  try {
    const [status, logsPayload] = await Promise.all([getStatus(), getLogs()]);
    renderStatus(status);
    renderLogs(logsPayload.logs || []);
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function wireActions() {
  document.getElementById("startBtn").addEventListener("click", async () => {
    try {
      const data = await postAction("/api/start");
      showMessage(data.message || "Bot started.");
      await refreshAll();
    } catch (err) {
      showMessage(err.message, true);
    }
  });

  document.getElementById("stopBtn").addEventListener("click", async () => {
    try {
      const data = await postAction("/api/stop");
      showMessage(data.message || "Bot stopped.");
      await refreshAll();
    } catch (err) {
      showMessage(err.message, true);
    }
  });

  document.getElementById("restartBtn").addEventListener("click", async () => {
    try {
      const data = await postAction("/api/restart");
      showMessage(data.message || "Bot restarted.");
      await refreshAll();
    } catch (err) {
      showMessage(err.message, true);
    }
  });

  document.getElementById("clearLogsBtn").addEventListener("click", async () => {
    try {
      const data = await postAction("/api/clear-logs");
      showMessage(data.message || "Logs cleared.");
      await refreshAll();
    } catch (err) {
      showMessage(err.message, true);
    }
  });

  document.getElementById("refreshBtn").addEventListener("click", refreshAll);
}

wireActions();
refreshAll();
setInterval(refreshAll, 5000);
