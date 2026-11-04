/* Complaint Router web UI.
 * Talks to the backend exclusively through REST (API_BASE_URL from config.js).
 * No framework: small helpers, every server string is HTML-escaped before rendering. */
"use strict";

const CFG = window.APP_CONFIG || {};
const host = window.location.hostname || "localhost";
const proto = window.location.protocol === "https:" ? "https:" : "http:";
const urlOr = (value, port) => (value && value.trim()) || `${proto}//${host}:${port}`;
const API = urlOr(CFG.API_BASE_URL, 8000).replace(/\/$/, "");
const LINKS = {
  grafana: urlOr(CFG.GRAFANA_URL, 3000),
  mlflow: urlOr(CFG.MLFLOW_URL, 5000),
  prometheus: urlOr(CFG.PROMETHEUS_URL, 9090),
  alertmanager: urlOr(CFG.ALERTMANAGER_URL, 9093),
};
const MIN_CHARS = 20, MAX_CHARS = 10000;

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => `${Math.round((x || 0) * 100)}%`;
const fmtTime = (v) => { if (!v) return "–"; const d = new Date(v); return isNaN(d) ? "–" : d.toLocaleString(); };
const fmtSec = (s) => s == null ? "–" : s < 60 ? `${Number(s).toFixed(1)} s` : `${Math.floor(s / 60)} m ${Math.round(s % 60)} s`;

let categories = [];
let lastPrediction = null;
let lastText = "";

/* ------------------------------------------------------------------ API */
class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout || 20000);
  let resp;
  try {
    resp = await fetch(`${API}${path}`, {
      ...options, signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch (e) {
    throw new ApiError(e.name === "AbortError" ? "The server took too long to answer. Please try again."
      : "Cannot reach the server. Check that the application is running.", 0);
  } finally { clearTimeout(timer); }
  let body = null;
  try { body = await resp.json(); } catch { /* non-JSON body */ }
  if (!resp.ok) {
    let msg = body && body.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    throw new ApiError(msg || `Request failed (HTTP ${resp.status})`, resp.status);
  }
  return body;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3500);
}

/* ------------------------------------------------------------- tabs */
function showView(name) {
  document.querySelectorAll(".tab").forEach((b) => {
    const on = b.dataset.view === name;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on);
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  try { localStorage.setItem("cr.view", name); } catch { /* storage unavailable */ }
  if (name === "pipeline") loadPipeline();
  if (name === "monitoring") loadMonitoring();
}

/* ----------------------------------------------------------- status */
async function refreshStatus() {
  const dot = $("#status-dot"), text = $("#status-text");
  try {
    const h = await api("/health", { timeout: 6000 });
    const up = h.model_server === "up";
    dot.className = `dot ${up ? "up" : "down"}`;
    text.textContent = up ? `Model v${h.model_version ?? "?"} online` : "Model offline";
  } catch {
    dot.className = "dot down";
    text.textContent = "Server unreachable";
  }
}

/* ------------------------------------------------------------ route */
function validateInput() {
  const v = $("#complaint").value;
  const n = v.trim().length;
  $("#char-count").textContent = `${v.length.toLocaleString()} / 10,000 characters`;
  let hint = "";
  if (n > 0 && n < MIN_CHARS) hint = "Please write a bit more (at least 20 characters).";
  else if (n >= MIN_CHARS && (v.match(/[a-z]/gi) || []).length < 10) hint = "The text should describe the problem in words.";
  $("#input-hint").textContent = hint;
  $("#btn-route").disabled = n < MIN_CHARS || n > MAX_CHARS || !!hint;
}

function setLoading(on) {
  const b = $("#btn-route");
  b.disabled = on;
  b.innerHTML = on ? '<span class="spinner"></span> Routing…' : "Route complaint";
  if (!on) validateInput();
}

async function routeComplaint() {
  const text = $("#complaint").value.trim();
  if (text.length < MIN_CHARS) return;
  setLoading(true);
  try {
    const res = await api("/api/v1/predict", { method: "POST", body: JSON.stringify({ text, top_k_similar: 3 }) });
    lastPrediction = res; lastText = text;
    renderResult(res);
  } catch (e) {
    $("#result").innerHTML = `<div class="card"><div class="banner error"><strong>Could not route this complaint.</strong><br>${esc(e.message)}</div></div>`;
  } finally { setLoading(false); }
}

function renderResult(r) {
  const high = r.priority === "high";
  const alt = r.alternatives.map((a) => `
    <div class="alt"><span>${esc(a.category_label)}</span>
      <div class="meter"><span style="width:${pct(a.probability)}"></span></div><span>${pct(a.probability)}</span></div>`).join("");
  const terms = r.explanation.length
    ? r.explanation.map((t) => `<span class="term" title="influence ${esc(t.weight)}">${esc(t.term)}</span>`).join("")
    : '<span class="muted">No strong keywords found.</span>';
  const similar = r.similar_complaints.length ? r.similar_complaints.map((s) => `
    <div class="similar">
      <div class="meta"><span><strong>${esc(s.category_label)}</strong></span><span>${pct(s.similarity)} similar</span>
        ${s.priority === "high" ? '<span class="pill high">URGENT</span>' : ""}
        ${s.date_received ? `<span>${esc(s.date_received)}</span>` : ""}
        ${s.company_response ? `<span>Outcome: ${esc(s.company_response)}</span>` : ""}</div>
      ${s.issue ? `<div class="small"><em>${esc(s.issue)}</em></div>` : ""}
      <div class="snippet">${esc(s.snippet)}…</div>
    </div>`).join("") : '<p class="muted">No similar complaints found.</p>';
  const options = categories.map((c) => `<option value="${esc(c.key)}" ${c.key === r.category ? "selected" : ""}>${esc(c.label)} - ${esc(c.team)}</option>`).join("");

  $("#result").innerHTML = `
    <div class="card">
      <div class="decision">
        <div>
          <div class="label">Send to</div>
          <div class="team">${esc(r.team)}</div>
          <div class="category">Category: ${esc(r.category_label)}</div>
        </div>
        <div>${high ? '<span class="pill high">URGENT</span>' : '<span class="pill normal">Normal priority</span>'}</div>
      </div>
      <div class="block">
        <div class="row-between"><strong>Confidence</strong><span>${pct(r.confidence)} ${r.low_confidence ? '<span class="pill warn">Needs review</span>' : ""}</span></div>
        <div class="meter ${r.low_confidence ? "low" : ""}"><span style="width:${pct(r.confidence)}"></span></div>
      </div>
      ${r.low_confidence ? '<div class="banner warn">The system is not sure about this one. Please read the complaint and confirm the team below.</div>' : ""}
      ${high ? `<div class="banner high"><strong>Handle first.</strong> This complaint looks urgent (urgency score ${pct(r.priority_score)}).</div>` : ""}
      <div class="block"><strong>Why this priority</strong><ul class="reasons">${r.priority_reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="block"><strong>Words that drove the decision</strong><div class="terms" style="margin-top:6px">${terms}</div></div>
      <div class="block"><strong>Other possible categories</strong>${alt}</div>
      <div class="block">
        <strong>Was this routing correct?</strong>
        <div class="feedback" style="margin-top:8px">
          <button class="btn ghost" id="fb-correct">✓ Correct</button>
          <select id="fb-category" aria-label="Correct team">${options}</select>
          <label class="small"><input type="checkbox" id="fb-urgent" ${high ? "checked" : ""}> urgent</label>
          <button class="btn ghost" id="fb-send">Send correction</button>
        </div>
      </div>
      <p class="muted small" style="margin-top:14px">Model v${esc(r.model_version ?? "?")} · ${esc(r.latency_ms)} ms · ref ${esc(r.prediction_id.slice(0, 8))}</p>
    </div>
    <div class="card"><h2>Similar past complaints</h2>${similar}</div>`;
  $("#fb-correct").onclick = () => sendFeedback(r.category, high ? "high" : "normal");
  $("#fb-send").onclick = () => sendFeedback($("#fb-category").value, $("#fb-urgent").checked ? "high" : "normal");
}

async function sendFeedback(correctCategory, correctPriority) {
  if (!lastPrediction) return;
  try {
    const res = await api("/api/v1/feedback", {
      method: "POST", body: JSON.stringify({
        prediction_id: lastPrediction.prediction_id, complaint_text: lastText,
        predicted_category: lastPrediction.category, correct_category: correctCategory,
        predicted_priority: lastPrediction.priority, correct_priority: correctPriority,
      }),
    });
    toast(res.message);
    document.querySelectorAll("#fb-correct, #fb-send").forEach((b) => { b.disabled = true; });
  } catch (e) { toast(`Feedback not saved: ${e.message}`); }
}

/* ---------------------------------------------------------- pipeline */
function kpi(label, value, cls = "") {
  return `<div class="kpi ${cls}"><div class="v">${esc(value)}</div><div class="k">${esc(label)}</div></div>`;
}

let pipelineData = { dag: null, runs: [], latest: {} };

async function loadPipeline() {
  const [dag, runs, reports, models, retrain] = await Promise.allSettled([
    api("/api/v1/pipeline/dag"), api("/api/v1/pipeline/runs?limit=200"), api("/api/v1/pipeline/reports"),
    api("/api/v1/pipeline/models"), api("/api/v1/pipeline/retrain"),
  ]);
  const val = (p, d) => (p.status === "fulfilled" ? p.value : d);
  const runData = val(runs, { summary: { total_runs: 0, succeeded: 0, failed: 0, latest_by_stage: {} }, runs: [] });
  const rep = val(reports, {});
  pipelineData = { dag: val(dag, { nodes: [], edges: [] }), runs: runData.runs, latest: runData.summary.latest_by_stage };

  const m = rep.metrics || {}, pre = rep.preprocess || {};
  const s = runData.summary;
  $("#pipeline-kpis").innerHTML =
    kpi("Stage runs", s.total_runs) + kpi("Succeeded", s.succeeded, "good") +
    kpi("Failed", s.failed, s.failed ? "bad" : "") +
    kpi("Ray throughput", pre.throughput_rows_per_sec ? `${Math.round(pre.throughput_rows_per_sec).toLocaleString()} rows/s` : "–") +
    kpi("Rows cleaned", pre.rows_out ? pre.rows_out.toLocaleString() : "–") +
    kpi("Test macro-F1", m.test_macro_f1 != null ? pct(m.test_macro_f1) : "–") +
    kpi("Urgent recall", m.test_priority_recall != null ? pct(m.test_priority_recall) : "–") +
    kpi("Latency / request", m.single_prediction_latency_ms != null ? `${m.single_prediction_latency_ms.toFixed(1)} ms` : "–");

  renderDag(pipelineData.dag, pipelineData.latest);
  renderRuns();

  const mod = val(models, { versions: [], experiment_runs: [] });
  $("#tbl-versions tbody").innerHTML = mod.versions.length ? mod.versions.map((v) => `
    <tr><td>v${esc(v.version)}</td><td>${v.aliases.map((a) => `<span class="pill ${a === "champion" ? "normal" : "warn"}">@${esc(a)}</span>`).join(" ")}</td>
    <td>${v.test_macro_f1 ? pct(Number(v.test_macro_f1)) : "–"}</td>
    <td><span class="status-tag ${v.gate === "passed" ? "success" : "failed"}">${esc(v.gate || "–")}</span></td><td>${fmtTime(v.created)}</td></tr>`).join("")
    : '<tr><td colspan="5" class="muted">No model registered yet. Run <code>make train</code>.</td></tr>';
  $("#tbl-experiments tbody").innerHTML = mod.experiment_runs.length ? mod.experiment_runs.map((r) => `
    <tr><td>${fmtTime(r.start_time)}</td><td><a href="${esc(LINKS.mlflow)}/#/experiments/${esc(r.experiment_id)}/runs/${esc(r.run_id)}" target="_blank" rel="noopener">${esc(r.run_name || r.run_id.slice(0, 8))}</a></td>
    <td>${esc(r.model_type || "–")}</td><td>${r.val_macro_f1 != null ? pct(r.val_macro_f1) : "–"}</td>
    <td>${r.test_macro_f1 != null ? pct(r.test_macro_f1) : "–"}</td><td>${esc(r.trigger || "–")}</td>
    <td><code>${esc((r.git_commit || "").slice(0, 7))}</code></td></tr>`).join("")
    : '<tr><td colspan="7" class="muted">No experiment runs yet.</td></tr>';

  const rt = val(retrain, null);
  if (!rt) {
    $("#retrain-status").textContent = "Retraining service unreachable.";
    $("#tbl-retrain tbody").innerHTML = "";
  } else {
    $("#retrain-status").innerHTML = rt.running
      ? `<span class="status-tag running">● Retraining in progress</span> (${esc(rt.current.trigger)}, started ${fmtTime(rt.current.started_at)})`
      : `Idle. Automatic retraining has a cool-down of ${Math.round(rt.cooldown_seconds / 60)} min.`;
    $("#tbl-retrain tbody").innerHTML = rt.history.length ? rt.history.map((h) => `
      <tr><td>${fmtTime(h.started_at)}</td><td>${esc(h.trigger)}</td><td><span class="status-tag ${esc(h.status)}">${esc(h.status)}</span></td>
      <td>${fmtSec(h.duration_seconds)}</td><td>${h.promoted == null ? "–" : h.promoted ? `yes (v${esc(h.version)})` : "no (kept champion)"}</td></tr>`).join("")
      : '<tr><td colspan="5" class="muted">No retraining runs yet.</td></tr>';
  }
}

function renderRuns() {
  const filter = $("#run-filter").value;
  const rows = pipelineData.runs.filter((r) => !filter || r.status === filter).slice(0, 60);
  $("#tbl-runs tbody").innerHTML = rows.length ? rows.map((r) => `
    <tr><td>${fmtTime(r.finished_at)}</td><td>${esc(r.stage)}</td>
    <td><span class="status-tag ${esc(r.status)}">${esc(r.status)}</span></td><td>${fmtSec(r.duration_seconds)}</td>
    <td>${Number(r.rows_in || 0).toLocaleString()} → ${Number(r.rows_out || 0).toLocaleString()}</td>
    <td>${r.throughput_rows_per_sec ? Math.round(r.throughput_rows_per_sec).toLocaleString() : "–"}</td>
    <td><code>${esc((r.git_commit || "").slice(0, 7))}</code></td><td class="err">${esc(r.error || "")}</td></tr>`).join("")
    : '<tr><td colspan="8" class="muted">No runs recorded yet.</td></tr>';
}

function renderDag(dag, latest) {
  if (!dag.nodes.length) { $("#dag").innerHTML = '<p class="muted">dvc.yaml not found.</p>'; return; }
  // Layer = longest path from a source node.
  const layer = {};
  const preds = (id) => dag.edges.filter((e) => e.target === id).map((e) => e.source);
  const depth = (id, seen = new Set()) => {
    if (layer[id] != null) return layer[id];
    if (seen.has(id)) return 0;
    seen.add(id);
    const p = preds(id);
    return (layer[id] = p.length ? 1 + Math.max(...p.map((x) => depth(x, seen))) : 0);
  };
  dag.nodes.forEach((n) => depth(n.id));
  const cols = {};
  dag.nodes.forEach((n) => { (cols[layer[n.id]] = cols[layer[n.id]] || []).push(n.id); });
  const W = 132, H = 54, GX = 34, GY = 26;
  const pos = {};
  const maxRows = Math.max(...Object.values(cols).map((c) => c.length));
  Object.entries(cols).forEach(([l, ids]) => ids.forEach((id, i) => {
    const offset = (maxRows - ids.length) * (H + GY) / 2;
    pos[id] = { x: 10 + Number(l) * (W + GX), y: 10 + offset + i * (H + GY) };
  }));
  const width = 20 + (Object.keys(cols).length) * (W + GX);
  const height = 20 + maxRows * (H + GY);
  const edges = dag.edges.map((e) => {
    const a = pos[e.source], b = pos[e.target];
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x - 4, y2 = b.y + H / 2, mx = (x1 + x2) / 2;
    return `<path class="edge" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
  }).join("");
  const nodes = dag.nodes.map((n) => {
    const r = latest[n.id];
    const st = r ? r.status : "";
    const sub = r ? `${st} · ${fmtSec(r.duration_seconds)}` : "not run yet";
    return `<g class="node ${esc(st)}" data-id="${esc(n.id)}" transform="translate(${pos[n.id].x},${pos[n.id].y})" tabindex="0">
      <rect width="${W}" height="${H}" rx="10"/><text x="12" y="23">${esc(n.id)}</text><text class="sub" x="12" y="41">${esc(sub)}</text></g>`;
  }).join("");
  $("#dag").innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="DVC pipeline graph">
    <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#7a8b97"/></marker></defs>
    ${edges}${nodes}</svg>`;
  document.querySelectorAll(".dag .node").forEach((g) => {
    const open = () => showStage(g.dataset.id);
    g.addEventListener("click", open);
    g.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
}

function showStage(id) {
  document.querySelectorAll(".dag .node").forEach((g) => g.classList.toggle("selected", g.dataset.id === id));
  const n = pipelineData.dag.nodes.find((x) => x.id === id);
  const r = pipelineData.latest[id];
  const history = pipelineData.runs.filter((x) => x.stage === id);
  const fails = history.filter((x) => x.status === "failed").length;
  $("#stage-detail").innerHTML = `
    <strong>${esc(id)}</strong>: ${esc(n.description)}
    <pre>${esc(n.cmd)}</pre>
    <div><strong>Inputs:</strong> ${n.deps.map(esc).join(", ") || "–"}</div>
    <div><strong>Outputs:</strong> ${n.outs.map(esc).join(", ") || "–"}</div>
    <div><strong>Latest run:</strong> ${r ? `<span class="status-tag ${esc(r.status)}">${esc(r.status)}</span> at ${fmtTime(r.finished_at)}, ${fmtSec(r.duration_seconds)}, ${Number(r.rows_out || 0).toLocaleString()} rows${r.throughput_rows_per_sec ? `, ${Math.round(r.throughput_rows_per_sec).toLocaleString()} rows/s` : ""}` : "never"}</div>
    <div><strong>History:</strong> ${history.length} runs, ${fails} failed</div>
    ${r && r.error ? `<div class="banner error">${esc(r.error)}</div>` : ""}`;
}

async function startRetrain() {
  const dlg = $("#retrain-dialog");
  dlg.showModal();
  dlg.onclose = async () => {
    if (dlg.returnValue !== "ok") return;
    try {
      const res = await api("/api/v1/pipeline/retrain", {
        method: "POST", headers: { "X-Admin-Token": $("#admin-token").value },
        body: JSON.stringify({ reason: $("#retrain-reason").value || "manual" }),
      });
      toast(res.message);
      setTimeout(loadPipeline, 1500);
    } catch (e) { toast(`Retraining not started: ${e.message}`); }
  };
}

/* -------------------------------------------------------- monitoring */
async function loadMonitoring() {
  const dash = `${LINKS.grafana}/d/complaint-router/financial-complaint-router?orgId=1&refresh=10s&kiosk`;
  const frame = $("#grafana-frame");
  if (!frame.src) frame.src = dash;
  $("#grafana-open").href = dash.replace("&kiosk", "");
  try {
    const d = await api("/api/v1/monitoring/drift");
    $("#drift-kpis").innerHTML =
      kpi("Drift status", d.drift_detected ? "DRIFT" : (d.status || "–").split(" (")[0], d.drift_detected ? "bad" : "good") +
      kpi("Drift score", (d.drift_score ?? 0).toFixed(2)) +
      kpi("Category PSI", d.category_psi != null ? d.category_psi.toFixed(3) : "–") +
      kpi("Length PSI", d.length_psi != null ? d.length_psi.toFixed(3) : "–") +
      kpi("Unknown-word rate", d.oov_rate_live != null ? pct(d.oov_rate_live) : "–") +
      kpi("Window", `${d.window_size} / ${d.min_samples}+`);
  } catch (e) { $("#drift-kpis").innerHTML = kpi("Drift", "unavailable", "bad"); }
}

/* ------------------------------------------------------------- init */
async function init() {
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  $("#complaint").addEventListener("input", validateInput);
  $("#complaint").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !$("#btn-route").disabled) routeComplaint(); });
  $("#btn-route").addEventListener("click", routeComplaint);
  $("#btn-clear").addEventListener("click", () => { $("#complaint").value = ""; validateInput(); $("#complaint").focus(); });
  $("#btn-refresh-pipeline").addEventListener("click", loadPipeline);
  $("#btn-retrain").addEventListener("click", startRetrain);
  $("#run-filter").addEventListener("change", renderRuns);
  $("#tool-links").innerHTML = [
    ["MLflow (experiments & registry)", LINKS.mlflow], ["Grafana (dashboards)", LINKS.grafana],
    ["Prometheus (metrics & alerts)", LINKS.prometheus], ["Alertmanager", LINKS.alertmanager],
    ["API documentation (Swagger)", `${API}/docs`],
  ].map(([t, u]) => `<a class="btn ghost" href="${esc(u)}" target="_blank" rel="noopener">${esc(t)} ↗</a>`).join("");

  refreshStatus();
  setInterval(refreshStatus, 15000);
  try { categories = await api("/api/v1/categories"); } catch { categories = []; }
  try {
    const ex = await api("/api/v1/examples");
    $("#example-chips").innerHTML = ex.map((e, i) => `<button class="chip" data-i="${i}">${esc(e.title)}</button>`).join("");
    document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
      $("#complaint").value = ex[Number(c.dataset.i)].text; validateInput(); routeComplaint();
    }));
  } catch { $("#example-chips").innerHTML = '<span class="muted small">Examples unavailable (server offline).</span>'; }
  let start = "route";
  try { start = localStorage.getItem("cr.view") || "route"; } catch { /* ignore */ }
  showView(start);
  validateInput();
}

document.addEventListener("DOMContentLoaded", init);
