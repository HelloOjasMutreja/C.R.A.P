"use strict";

// Live frames sent to the laptop are scaled to this width; records use full resolution.
const LIVE_WIDTH = 512;
const RECORD_MAX_WIDTH = 1600;
const VERDICT_WINDOW = 8;     // recent results considered for the live verdict
const VERDICT_MIN_HITS = 3;   // a condition must show up this many times to be shown
const STALE_MS = 1500;        // boxes fade out after this long without a new result

const $ = (id) => document.getElementById(id);
const video = $("video");
const overlay = $("overlay");
const ctx = overlay.getContext("2d");
const capture = $("capture");

const state = {
  ws: null,
  inFlight: false,
  latest: null,          // last detection result
  latestAt: 0,
  history: [],           // recent results for the verdict
  resultTimes: [],       // for fps
  plantId: null,
  location: "",
  manualPlant: false,    // true once the user picks a plant; tags then stop overriding it
  plant: null,           // summary from the server
  recording: false,
};

// ---------- helpers ----------

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const STATUS_LABEL = {
  unassessed: "Unassessed",
  healthy: "Healthy",
  suspected_disease: "Suspected",
  diseased: "Diseased",
  needs_reinspection: "Re-inspect",
  suspected: "Suspected",
  confirmed: "Confirmed",
  proposed: "Proposed",
  awaiting_approval: "Needs approval",
  approved: "Approved",
  completed: "Done",
  failed: "Failed",
  rejected: "Rejected",
  superseded: "Replaced",
};

const ACTION_LABEL = {
  inspect_closer: "Inspect closer",
  flag_plant: "Flag plant for treatment",
  reposition_and_retry: "Reposition and retry",
  move_on: "Move on to next plant",
};

const OPEN_ACTION = ["proposed", "awaiting_approval", "approved"];

function statusTag(status) {
  return `<span class="tag ${escapeHtml(status)}">${escapeHtml(STATUS_LABEL[status] || status)}</span>`;
}

function timeAgo(iso) {
  if (!iso) return "never";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

let toastTimer = null;
function toast(html, ms = 3200) {
  const el = $("toast");
  el.innerHTML = html;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), ms);
}

// ---------- camera + connection ----------

async function startCamera() {
  const error = $("startError");
  error.textContent = "";

  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    error.textContent = "The camera needs a secure page. Open the https:// address the laptop printed, and accept the certificate warning.";
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();
  } catch (err) {
    error.textContent = `Could not open the camera: ${err.message || err}. Check the browser's camera permission for this site.`;
    return;
  }

  $("start").classList.add("hidden");
  keepScreenOn();
  connect();
  requestAnimationFrame(draw);
}

async function keepScreenOn() {
  try {
    await navigator.wakeLock?.request("screen");
  } catch (_) { /* not supported or denied; the demo still works */ }
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && video.srcObject) keepScreenOn();
});

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws/detect`);
  ws.binaryType = "arraybuffer";
  state.ws = ws;
  state.inFlight = false;
  setLive(false, "CONNECTING");

  ws.onopen = () => {
    setLive(true, "LIVE");
    sendFrame();
  };
  ws.onmessage = (event) => {
    state.inFlight = false;
    const msg = JSON.parse(event.data);
    if (msg.type === "detections") onDetections(msg);
    sendFrame();
  };
  ws.onclose = () => {
    setLive(false, "RECONNECTING");
    setTimeout(connect, 1000);
  };
  ws.onerror = () => ws.close();
}

function setLive(live, text) {
  document.body.classList.toggle("live", live);
  $("liveText").textContent = text;
}

// Only one frame is in flight at a time, so a slow laptop never builds a queue.
function sendFrame() {
  const ws = state.ws;
  if (!ws || ws.readyState !== WebSocket.OPEN || state.inFlight) return;
  if (video.readyState < 2 || !video.videoWidth) {
    setTimeout(sendFrame, 100);
    return;
  }

  const scale = LIVE_WIDTH / video.videoWidth;
  capture.width = LIVE_WIDTH;
  capture.height = Math.round(video.videoHeight * scale);
  capture.getContext("2d").drawImage(video, 0, 0, capture.width, capture.height);

  state.inFlight = true;
  capture.toBlob((blob) => {
    if (blob && ws.readyState === WebSocket.OPEN) ws.send(blob);
    else state.inFlight = false;
  }, "image/jpeg", 0.7);
}

// ---------- results ----------

function onDetections(msg) {
  const now = performance.now();
  state.latest = msg;
  state.latestAt = now;

  state.resultTimes.push(now);
  while (state.resultTimes.length > 10) state.resultTimes.shift();
  const span = (now - state.resultTimes[0]) / 1000;
  const fps = state.resultTimes.length > 1 ? (state.resultTimes.length - 1) / span : 0;
  $("stats").textContent = `${fps.toFixed(1)} fps · ${msg.infer_ms} ms`;

  state.history.push(msg.detections);
  while (state.history.length > VERDICT_WINDOW) state.history.shift();
  updateVerdict();

  if (msg.tag && !state.manualPlant && msg.tag.plant_id !== state.plantId) {
    selectPlant(msg.tag.plant_id, { fromTag: true });
  }
}

function updateVerdict() {
  const conditionHits = new Map();
  let healthyHits = 0;
  let species = null;

  for (const detections of state.history) {
    const seen = new Set();
    let healthy = false;
    for (const d of detections) {
      species = species || d.species;
      if (d.is_healthy) {
        healthy = true;
      } else {
        const key = `${d.species} · ${d.condition}`;
        if (!seen.has(key)) {
          seen.add(key);
          const hit = conditionHits.get(key) || { count: 0, best: 0 };
          hit.count += 1;
          hit.best = Math.max(hit.best, d.confidence);
          conditionHits.set(key, hit);
        }
      }
    }
    if (healthy) healthyHits += 1;
  }

  const strongest = [...conditionHits.entries()]
    .filter(([, hit]) => hit.count >= VERDICT_MIN_HITS)
    .sort((a, b) => b[1].count - a[1].count || b[1].best - a[1].best)[0];

  const box = $("verdict");
  const frames = state.history.length;
  if (strongest) {
    const [name, hit] = strongest;
    box.className = "verdict disease";
    $("verdictTitle").textContent = name;
    $("verdictSub").textContent = `Possible disease · up to ${Math.round(hit.best * 100)}% · in ${hit.count} of last ${frames} frames`;
  } else if (healthyHits >= VERDICT_MIN_HITS) {
    box.className = "verdict healthy";
    $("verdictTitle").textContent = `${species || "Leaf"} · healthy`;
    $("verdictSub").textContent = `No disease seen in the last ${frames} frames`;
  } else {
    box.className = "verdict neutral";
    $("verdictTitle").textContent = "Point the camera at a leaf";
    $("verdictSub").textContent = "Live detection";
  }
}

// ---------- drawing ----------

function draw() {
  requestAnimationFrame(draw);

  const dpr = window.devicePixelRatio || 1;
  const cw = overlay.clientWidth;
  const ch = overlay.clientHeight;
  if (overlay.width !== Math.round(cw * dpr) || overlay.height !== Math.round(ch * dpr)) {
    overlay.width = Math.round(cw * dpr);
    overlay.height = Math.round(ch * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cw, ch);

  const msg = state.latest;
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!msg || !vw) return;

  const age = performance.now() - state.latestAt;
  const alpha = age < STALE_MS ? 1 : Math.max(0, 1 - (age - STALE_MS) / 800);
  if (alpha <= 0) return;

  // The video uses object-fit: cover, so map frame pixels the same way.
  const scale = Math.max(cw / vw, ch / vh);
  const offsetX = (cw - vw * scale) / 2;
  const offsetY = (ch - vh * scale) / 2;
  const frameToVideo = vw / msg.width;
  const map = (x, y) => [offsetX + x * frameToVideo * scale, offsetY + y * frameToVideo * scale];

  ctx.globalAlpha = alpha;

  for (const d of msg.detections) {
    const [x1, y1] = map(d.bbox[0], d.bbox[1]);
    const [x2, y2] = map(d.bbox[2], d.bbox[3]);
    const color = d.is_healthy ? "#3cb44b" : "#e6463c";
    drawBox(x1, y1, x2 - x1, y2 - y1, color);
    const label = d.is_healthy
      ? `${d.species} · healthy ${Math.round(d.confidence * 100)}%`
      : `${d.condition} ${Math.round(d.confidence * 100)}%`;
    drawLabel(label, x1, y1, color);
  }

  if (msg.tag) {
    const points = msg.tag.corners.map(([x, y]) => map(x, y));
    ctx.strokeStyle = "#4fd1ff";
    ctx.lineWidth = 3;
    ctx.beginPath();
    points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.stroke();
    const top = points.reduce((a, b) => (b[1] < a[1] ? b : a));
    drawLabel(`TAG ${msg.tag.plant_id}`, top[0], top[1], "#0a7fa6");
  }

  ctx.globalAlpha = 1;
}

function drawBox(x, y, w, h, color) {
  ctx.fillStyle = color + "22";
  ctx.fillRect(x, y, w, h);

  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.strokeRect(x, y, w, h);

  // Thick corner brackets give it the viewfinder look.
  const c = Math.min(18, w / 3, h / 3);
  ctx.lineWidth = 3.5;
  ctx.beginPath();
  ctx.moveTo(x, y + c); ctx.lineTo(x, y); ctx.lineTo(x + c, y);
  ctx.moveTo(x + w - c, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + c);
  ctx.moveTo(x + w, y + h - c); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w - c, y + h);
  ctx.moveTo(x + c, y + h); ctx.lineTo(x, y + h); ctx.lineTo(x, y + h - c);
  ctx.stroke();
}

function drawLabel(text, x, y, color) {
  ctx.font = "600 12px system-ui, sans-serif";
  const w = ctx.measureText(text).width + 10;
  const h = 18;
  const ly = Math.max(0, y - h < 0 ? y : y - h);
  // Keep labels on screen even when the box runs off the edge.
  x = Math.min(Math.max(0, x), overlay.clientWidth - w);
  ctx.fillStyle = color;
  ctx.fillRect(x, ly, w, h);
  ctx.fillStyle = "#fff";
  ctx.fillText(text, x + 5, ly + 13);
}

// ---------- plant selection + record panel ----------

async function selectPlant(plantId, { fromTag = false, manual = false, location = "" } = {}) {
  state.plantId = plantId;
  if (manual) state.manualPlant = true;
  if (location) state.location = location;

  const chip = $("plantChip");
  chip.textContent = `${fromTag ? "🏷 " : ""}${plantId} ▾`;
  chip.classList.toggle("tagged", fromTag);
  if (fromTag) toast(`Plant tag found: <b>${escapeHtml(plantId)}</b>`, 1800);

  await refreshPlant();
}

async function refreshPlant() {
  if (!state.plantId) {
    state.plant = null;
    renderSheet();
    return;
  }
  const res = await fetch(`/api/plants/${encodeURIComponent(state.plantId)}`);
  state.plant = res.ok ? await res.json() : null;
  renderSheet();
}

function renderSheet(newConditions = []) {
  const body = $("sheetBody");

  if (!state.plantId) {
    body.innerHTML = `
      <div class="rec-head"><div class="rec-title">No plant selected</div></div>
      <div class="rec-meta">Point at a plant tag, or tap “Select plant” at the top.</div>`;
    return;
  }

  const p = state.plant;
  if (!p) {
    body.innerHTML = `
      <div class="rec-head"><div class="rec-title">${escapeHtml(state.plantId)}</div>${statusTag("unassessed")}</div>
      <div class="rec-meta">New plant · record a visit to start its history</div>`;
    return;
  }

  const diagnoses = p.diagnoses.map((d) => {
    const pct = Math.round((d.confidence || 0) * 100);
    const color = d.status === "confirmed" ? "#e6463c" : "#e0a020";
    const isNew = newConditions.includes(d.condition) ? " new-flash" : "";
    const support = d.supporting.slice(0, 2).map((e) => `<div class="ev">${escapeHtml(e)}</div>`).join("");
    const against = d.contradicting.slice(0, 2).map((e) => `<div class="ev against">${escapeHtml(e)}</div>`).join("");
    return `
      <div class="diag${isNew}">
        <div class="diag-head"><span>${escapeHtml(d.condition)}</span>${statusTag(d.status)}</div>
        <div class="bar"><i style="width:${pct}%;background:${color}"></i></div>
        ${support}${against}
      </div>`;
  }).join("");

  body.innerHTML = `
    <div class="rec-head">
      <div class="rec-title">${escapeHtml(p.plant_id)}${p.species ? ` · ${escapeHtml(p.species)}` : ""}</div>
      ${statusTag(p.status)}
    </div>
    <div class="rec-meta">${escapeHtml(p.location)} · ${p.visits} visit${p.visits === 1 ? "" : "s"} · last ${timeAgo(p.last_visit)}</div>
    ${actionCard(p.actions || [])}
    ${diagnoses || `<div class="empty" style="margin-top:12px">No diagnoses yet.</div>`}`;
}

function actionCard(actions) {
  const open = actions.find((a) => OPEN_ACTION.includes(a.status));
  const action = open || actions[0];
  if (!action) return "";

  let buttons = "";
  if (action.status === "awaiting_approval") {
    buttons = `
      <button type="button" class="btn-approve" data-act="approve" data-id="${escapeHtml(action.action_id)}">Approve</button>
      <button type="button" class="btn-reject" data-act="reject" data-id="${escapeHtml(action.action_id)}">Reject</button>`;
  } else if (action.status === "proposed" || action.status === "approved") {
    buttons = `
      <button type="button" class="btn-run" data-act="execute" data-id="${escapeHtml(action.action_id)}">Run on robot</button>
      <button type="button" class="btn-reject" data-act="reject" data-id="${escapeHtml(action.action_id)}">Skip</button>`;
  }

  return `
    <div class="action-card">
      <div class="label">${open ? "Next action" : "Last action"}</div>
      <div class="title"><span>${escapeHtml(ACTION_LABEL[action.type] || action.type)}</span>${statusTag(action.status)}</div>
      <div class="why">${escapeHtml(action.reason)}</div>
      ${action.result ? `<div class="result">${escapeHtml(action.result)}</div>` : ""}
      ${buttons ? `<div class="action-buttons">${buttons}</div>` : ""}
    </div>`;
}

$("sheetBody").addEventListener("click", async (e) => {
  const button = e.target.closest("[data-act]");
  if (!button || !state.plantId) return;
  button.disabled = true;

  const url = `/api/plants/${encodeURIComponent(state.plantId)}/actions/${encodeURIComponent(button.dataset.id)}/${button.dataset.act}`;
  try {
    const res = await fetch(url, { method: "POST" });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || `server said ${res.status}`);
    state.plant = body.plant;
    renderSheet();
    const a = body.action;
    toast(`${escapeHtml(ACTION_LABEL[a.type] || a.type)} · <b>${escapeHtml(STATUS_LABEL[a.status] || a.status)}</b>${a.result ? `<br>${escapeHtml(a.result)}` : ""}`);
  } catch (err) {
    toast(`⚠️ ${escapeHtml(err.message || err)}`);
    button.disabled = false;
  }
});

$("sheetHandle").addEventListener("click", () => $("sheet").classList.toggle("collapsed"));

// ---------- recording a visit ----------

async function recordVisit() {
  if (state.recording) return;
  if (!state.plantId) {
    openPicker();
    return;
  }

  state.recording = true;
  $("recordBtn").classList.add("busy");

  try {
    const scale = Math.min(1, RECORD_MAX_WIDTH / video.videoWidth);
    capture.width = Math.round(video.videoWidth * scale);
    capture.height = Math.round(video.videoHeight * scale);
    capture.getContext("2d").drawImage(video, 0, 0, capture.width, capture.height);
    const blob = await new Promise((resolve) => capture.toBlob(resolve, "image/jpeg", 0.9));

    const params = new URLSearchParams({ location: state.location || "field" });
    const res = await fetch(`/api/plants/${encodeURIComponent(state.plantId)}/visits?${params}`, {
      method: "POST",
      headers: { "Content-Type": "image/jpeg" },
      body: blob,
    });
    if (!res.ok) throw new Error(`server said ${res.status}`);
    const result = await res.json();

    state.plant = result.plant;
    renderSheet(result.new_diagnoses.map((d) => d.condition));
    $("sheet").classList.remove("collapsed");

    const found = result.new_diagnoses.length
      ? result.new_diagnoses.map((d) => `${escapeHtml(d.condition)} · <b>${escapeHtml(STATUS_LABEL[d.status] || d.status)}</b>`).join("<br>")
      : `Status: <b>${escapeHtml(STATUS_LABEL[result.status] || result.status)}</b>`;
    const next = result.proposed_action
      ? `<br>Next: <b>${escapeHtml(ACTION_LABEL[result.proposed_action.type] || result.proposed_action.type)}</b>`
      : "";
    toast(`✅ Visit recorded for ${escapeHtml(result.plant.plant_id)}<br>${found}${next}`, 4200);
  } catch (err) {
    toast(`⚠️ Could not record: ${escapeHtml(err.message || err)}`);
  } finally {
    state.recording = false;
    $("recordBtn").classList.remove("busy");
  }
}

$("recordBtn").addEventListener("click", recordVisit);

// ---------- plant picker ----------

async function openPicker() {
  $("picker").classList.remove("hidden");
  const list = $("plantList");
  list.innerHTML = `<div class="empty">Loading plants…</div>`;

  const plants = await fetch("/api/plants").then((r) => r.json()).catch(() => []);
  $("pickAuto").classList.toggle("active", !state.manualPlant);

  list.innerHTML = plants.length
    ? plants.map((p) => `
        <button type="button" class="plant-row${p.plant_id === state.plantId && state.manualPlant ? " active" : ""}" data-id="${escapeHtml(p.plant_id)}">
          <div class="row-top"><b>${escapeHtml(p.plant_id)}</b>${statusTag(p.status)}</div>
          <span>${escapeHtml(p.species || "Unknown species")} · ${escapeHtml(p.location)} · ${p.visits} visit${p.visits === 1 ? "" : "s"}</span>
        </button>`).join("")
    : `<div class="empty">No plants yet. Add one below.</div>`;

  const next = plants.length + 1;
  $("newPlantId").placeholder = `PLANT_${String(next).padStart(3, "0")}`;
}

function closePicker() {
  $("picker").classList.add("hidden");
}

$("plantChip").addEventListener("click", openPicker);
$("pickerClose").addEventListener("click", closePicker);
$("picker").addEventListener("click", (e) => { if (e.target.id === "picker") closePicker(); });

$("plantList").addEventListener("click", (e) => {
  const row = e.target.closest(".plant-row");
  if (!row) return;
  selectPlant(row.dataset.id, { manual: true });
  closePicker();
});

$("pickAuto").addEventListener("click", () => {
  state.manualPlant = false;
  state.plantId = null;
  $("plantChip").textContent = "Waiting for tag ▾";
  $("plantChip").classList.remove("tagged");
  renderSheet();
  closePicker();
});

$("newPlant").addEventListener("submit", (e) => {
  e.preventDefault();
  const id = ($("newPlantId").value || $("newPlantId").placeholder).trim().toUpperCase().replace(/\s+/g, "_");
  const loc = $("newPlantLocation").value.trim();
  if (!id) return;
  selectPlant(id, { manual: true, location: loc });
  $("newPlantId").value = "";
  closePicker();
});

// ---------- robot ----------

async function refreshRobot() {
  const pill = $("robotMode");
  try {
    const status = await fetch("/api/robot").then((r) => r.json());
    if (status.simulated) {
      pill.textContent = "ROBOT · SIM";
      pill.className = "pill sim";
    } else if (status.connected) {
      pill.textContent = "ROBOT · OK";
      pill.className = "pill ok";
    } else {
      pill.textContent = "ROBOT · OFFLINE";
      pill.className = "pill off";
    }
  } catch (_) {
    pill.textContent = "ROBOT · ?";
    pill.className = "pill off";
  }
}

$("stopBtn").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/robot/stop", { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).detail || res.status);
    toast("🛑 Stop sent to robot", 1800);
  } catch (err) {
    toast(`⚠️ Stop failed: ${escapeHtml(err.message || err)}`);
  }
});

refreshRobot();
setInterval(refreshRobot, 5000);

$("startBtn").addEventListener("click", startCamera);
renderSheet();
