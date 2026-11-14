// Complaint Router web UI. Talks to the backend only through REST
// (API_BASE_URL comes from config.js). All server text is HTML-escaped.
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
let modelUp = true;
let routing = false;

// ---- api ----
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

// ---- tabs ----
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

// ---- status ----
async function refreshStatus() {
  const dot = $("#status-dot"), text = $("#status-text");
  let problem = "";
  try {
    const h = await api("/health", { timeout: 6000 });
    modelUp = h.model_server === "up";
    text.textContent = modelUp ? `Model v${h.model_version ?? "?"} online` : "Model offline";
    if (!modelUp) problem = "The model is starting or has not been trained yet. Routing is paused, please try again in a minute.";
  } catch {
    modelUp = false;
    text.textContent = "Server unreachable";
    problem = "The application server cannot be reached. Check that the application is running, then reload this page.";
  }
  dot.className = `dot ${modelUp ? "up" : "down"}`;
  // server came back after being offline: load the examples again without a page reload
  if (modelUp && !categories.length) loadLookups();
  // tell the user why the button is disabled instead of silently disabling it
  $("#offline-banner").innerHTML = problem ? `<div class="banner error" style="margin:0 0 20px">${esc(problem)}</div>` : "";
  validateInput();
}

// ---- route ----
function validateInput() {
  const v = $("#complaint").value;
  const n = v.trim().length;
  $("#char-count").textContent = `${v.length.toLocaleString()} / 10,000 characters`;
  let hint = "";
  if (n > 0 && n < MIN_CHARS) hint = `Please write a bit more (${MIN_CHARS - n} more characters).`;
  else if (n >= MIN_CHARS && (v.match(/[a-z]/gi) || []).length < 10) hint = "The text should describe the problem in words.";
  $("#input-hint").textContent = hint;
  $("#btn-route").disabled = routing || !modelUp || n < MIN_CHARS || n > MAX_CHARS || !!hint;
  // if the text was changed after routing, the shown result no longer matches it
  const card = $("#result-card");
  if (card) {
    const stale = v.trim() !== lastText;
    card.classList.toggle("stale", stale);
    $("#stale-note").hidden = !stale;
    document.querySelectorAll("#fb-correct, #fb-send").forEach((b) => { b.disabled = stale; });
  }
}

function setLoading(on) {
  routing = on;
  $("#btn-route").innerHTML = on ? '<span class="spinner"></span> Routing…' : "Route complaint →";
  if (on) {
    $("#result").innerHTML = `<div class="card" aria-busy="true">
      <div class="tiles">${'<div class="tile"><div class="skeleton" style="height:12px;width:60%"></div><div class="skeleton" style="height:22px;margin-top:10px"></div></div>'.repeat(3)}</div>
      <div class="skeleton" style="height:56px;margin-top:12px"></div>
      <div class="skeleton" style="height:14px;width:40%;margin-top:22px"></div>
      <div class="skeleton" style="height:14px;width:80%;margin-top:10px"></div></div>`;
  }
  validateInput();
}

async function routeComplaint() {
  const text = $("#complaint").value.trim();
  if (text.length < MIN_CHARS || routing) return;
  setLoading(true);
  try {
    const res = await api("/api/v1/predict", { method: "POST", body: JSON.stringify({ text, top_k_similar: 3 }) });
    lastPrediction = res; lastText = text;
    renderResult(res);
  } catch (e) {
    lastPrediction = null;
    $("#result").innerHTML = `<div class="card"><div class="banner error" style="margin:0"><strong>Could not route this complaint.</strong><br>${esc(e.message)}</div></div>`;
  } finally { setLoading(false); }
}

// plain-language confidence level
function confidenceLevel(c) {
  if (c >= 0.8) return { word: "High", cls: "" };
  if (c >= 0.5) return { word: "Medium", cls: "" };
  return { word: "Low", cls: "low" };
}

// what the agent should do next, in one sentence
function nextStep(r) {
  if (r.priority === "high") {
    return { cls: "high", ico: "!", title: "Handle first",
      text: `Urgent case. Send it to the ${r.team} today and escalate it to a team lead.` };
  }
  if (r.low_confidence) {
    return { cls: "warn", ico: "?", title: "Check before assigning",
      text: "The system is not sure. Read the complaint, pick the right team below and send the correction." };
  }
  return { cls: "ok", ico: "✓", title: "Ready to assign",
    text: `Send it to the ${r.team} in the normal queue.` };
}

function renderResult(r) {
  const high = r.priority === "high";
  const conf = confidenceLevel(r.confidence);
  const step = nextStep(r);
  const alt = r.alternatives.map((a) => `
    <div class="alt"><span>${esc(a.category_label)}</span>
      <div class="meter"><span style="width:${pct(a.probability)}"></span></div><span class="p">${pct(a.probability)}</span></div>`).join("");
  const terms = r.explanation.length
    ? r.explanation.map((t) => `<span class="term" title="influence ${esc(t.weight)}">${esc(t.term)}</span>`).join("")
    : '<span class="muted small">No strong keywords found.</span>';
  const similar = r.similar_complaints.length ? r.similar_complaints.map((s) => `
    <div class="similar">
      <div class="meta"><strong>${esc(s.category_label)}</strong><span>${pct(s.similarity)} similar</span>
        ${s.priority === "high" ? '<span class="pill high">Urgent</span>' : ""}
        ${s.date_received ? `<span>${esc(s.date_received)}</span>` : ""}</div>
      ${s.issue ? `<div class="issue">${esc(s.issue)}</div>` : ""}
      <div class="snippet">“${esc(s.snippet)}…”</div>
      ${s.company_response ? `<div class="meta" style="margin-top:6px"><span>Outcome: ${esc(s.company_response)}</span></div>` : ""}
    </div>`).join("") : '<p class="muted small">No similar complaints found.</p>';
  const options = categories.map((c) => `<option value="${esc(c.key)}" ${c.key === r.category ? "selected" : ""}>${esc(c.team)} (${esc(c.label)})</option>`).join("");

  $("#result").innerHTML = `
    <div class="card" id="result-card">
      <div id="stale-note" class="banner info" style="margin:0 0 14px" hidden>The text was changed. Click <strong>Route complaint</strong> again to update this result.</div>
      <div class="tiles">
        <div class="tile">
          <div class="label">Routed to</div>
          <div class="value">${esc(r.team)}</div>
          <div class="sub">${esc(r.category_label)}</div>
        </div>
        <div class="tile ${high ? "urgent" : "normal"}">
          <div class="label">Priority</div>
          <div class="value">${high ? "Urgent" : "Normal"}</div>
          <div class="sub">Urgency score ${pct(r.priority_score)}</div>
        </div>
        <div class="tile ${conf.cls}">
          <div class="label">Confidence</div>
          <div class="value">${pct(r.confidence)}</div>
          <div class="sub">${conf.word}${r.low_confidence ? ", needs review" : ""}</div>
          <div class="meter ${conf.cls}"><span style="width:${pct(r.confidence)}"></span></div>
        </div>
      </div>

      <div class="next-step ${step.cls}">
        <span class="ico" aria-hidden="true">${step.ico}</span>
        <div><strong>${esc(step.title)}</strong><span class="small">${esc(step.text)}</span></div>
      </div>

      <div class="block"><span class="label">Why this priority</span><ul class="reasons">${r.priority_reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="block"><span class="label">Words that drove the decision</span><div class="terms">${terms}</div></div>
      <div class="block"><span class="label">Other possible categories</span>${alt}</div>

      <div class="block" id="feedback-block">
        <span class="label">Was this right?</span>
        <div class="feedback">
          <button class="btn ghost small" id="fb-correct">✓ Yes, correct</button>
          <span class="muted small">or change it:</span>
          <select id="fb-category" aria-label="Correct team">${options}</select>
          <label class="check"><input type="checkbox" id="fb-urgent" ${high ? "checked" : ""}> Urgent</label>
          <button class="btn ghost small" id="fb-send">Send correction</button>
        </div>
      </div>

      <div class="result-foot">
        <span class="meta">Model v${esc(r.model_version ?? "?")} · ${esc(r.latency_ms)} ms · ref ${esc(r.prediction_id.slice(0, 8))}</span>
        <button class="btn ghost small" id="btn-copy">Copy summary</button>
      </div>
    </div>
    <div class="card"><h2>Similar past complaints</h2>${similar}</div>`;
  $("#fb-correct").onclick = () => sendFeedback(r.category, high ? "high" : "normal");
  $("#fb-send").onclick = () => sendFeedback($("#fb-category").value, $("#fb-urgent").checked ? "high" : "normal");
  $("#btn-copy").onclick = () => copySummary(r, step);
  validateInput();
}

async function copySummary(r, step) {
  const text = [
    `Team: ${r.team} (${r.category_label})`,
    `Priority: ${r.priority === "high" ? "URGENT" : "Normal"} (urgency score ${pct(r.priority_score)})`,
    `Confidence: ${pct(r.confidence)}`,
    `Next step: ${step.title} - ${step.text}`,
    `Reference: ${r.prediction_id}`,
  ].join("\n");
  try {
    await navigator.clipboard.writeText(text);
    toast("Summary copied. You can paste it into the ticket.");
  } catch { toast("Copying is not allowed in this browser. Please select the text manually."); }
}

async function sendFeedback(correctCategory, correctPriority) {
  if (!lastPrediction) return;
  const buttons = document.querySelectorAll("#fb-correct, #fb-send");
  buttons.forEach((b) => { b.disabled = true; });
  try {
    await api("/api/v1/feedback", {
      method: "POST", body: JSON.stringify({
        prediction_id: lastPrediction.prediction_id, complaint_text: lastText,
        predicted_category: lastPrediction.category, correct_category: correctCategory,
        predicted_priority: lastPrediction.priority, correct_priority: correctPriority,
      }),
    });
    const changed = correctCategory !== lastPrediction.category || correctPriority !== lastPrediction.priority;
    $("#feedback-block").innerHTML = `<span class="label">Was this right?</span>
      <div class="feedback-done">✓ Thank you, ${changed ? "your correction was saved" : "we recorded that it was correct"}. It will help the next model.</div>`;
  } catch (e) {
    buttons.forEach((b) => { b.disabled = false; });
    toast(`Feedback not saved: ${e.message}`);
  }
}

// ---- pipeline ----
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
  const preds = (id) => dag.edges.filter((e) => e.target === id).map((e) => e.source);
  const succs = (id) => dag.edges.filter((e) => e.source === id).map((e) => e.target);

  // depth = longest path from a starting node
  const depth = {};
  const getDepth = (id, seen = new Set()) => {
    if (depth[id] != null) return depth[id];
    if (seen.has(id)) return 0;
    seen.add(id);
    const p = preds(id);
    return (depth[id] = p.length ? 1 + Math.max(...p.map((x) => getDepth(x, seen))) : 0);
  };
  dag.nodes.forEach((n) => getDepth(n.id));

  // main chain = the longest path; it goes on the top row
  const ids = dag.nodes.map((n) => n.id);
  let cur = ids.reduce((a, b) => (depth[b] > depth[a] ? b : a));
  const chain = new Set([cur]);
  while (preds(cur).length) {
    cur = preds(cur).reduce((a, b) => (depth[b] > depth[a] ? b : a));
    chain.add(cur);
  }

  // other nodes sit one column before the stage they feed, on the rows below
  const col = {}, row = {}, used = {};
  ids.forEach((id) => { if (chain.has(id)) { col[id] = depth[id]; row[id] = 0; } });
  ids.filter((id) => !chain.has(id)).forEach((id) => {
    const next = succs(id).filter((t) => col[t] != null);
    col[id] = next.length ? Math.max(0, Math.min(...next.map((t) => col[t])) - 1) : depth[id];
    used[col[id]] = (used[col[id]] || 0) + 1;
    row[id] = used[col[id]];
  });

  const W = 132, H = 54, GX = 34, GY = 34, TOP = 40, PAD = 10;
  const pos = {};
  ids.forEach((id) => { pos[id] = { x: PAD + col[id] * (W + GX), y: TOP + row[id] * (H + GY) }; });
  const width = PAD * 2 + (Math.max(...Object.values(col)) + 1) * (W + GX) - GX;
  const height = TOP + (Math.max(...Object.values(row)) + 1) * (H + GY);

  // Edges that skip a stage are drawn as arcs over the row. If an arc would
  // cross another arc, draw it under the row instead (when nothing is there).
  const skips = dag.edges.filter((e) => row[e.source] === row[e.target] && col[e.target] - col[e.source] > 1)
    .sort((p, q) => col[p.source] - col[q.source]);
  const above = [], below = new Set();
  skips.forEach((e) => {
    const c1 = col[e.source], c2 = col[e.target];
    const crosses = above.some(([a1, a2]) => c1 > a1 && c1 < a2 && c2 > a2);
    const freeBelow = !ids.some((id) => row[id] > 0 && col[id] >= c1 && col[id] <= c2);
    if (crosses && freeBelow) below.add(e); else above.push([c1, c2]);
  });

  const edges = dag.edges.map((e) => {
    const a = pos[e.source], b = pos[e.target];
    const span = col[e.target] - col[e.source];
    let d;
    if (row[e.source] === row[e.target] && span === 1) {
      // neighbours: straight line
      d = `M${a.x + W},${a.y + H / 2} L${b.x - 4},${b.y + H / 2}`;
    } else if (row[e.source] === row[e.target]) {
      // skips a stage: arc over (or under) the boxes in between
      const x1 = a.x + W * 0.7, x2 = b.x + W * 0.3, lift = 26 + 10 * (span - 2);
      d = below.has(e)
        ? `M${x1},${a.y + H} C${x1},${a.y + H + lift} ${x2},${b.y + H + lift} ${x2},${b.y + H + 4}`
        : `M${x1},${a.y} C${x1},${a.y - lift} ${x2},${b.y - lift} ${x2},${b.y - 4}`;
    } else {
      // from a lower row: come up into the bottom of the target
      const x2 = b.x + W / 2;
      d = `M${a.x + W},${a.y + H / 2} C${x2},${a.y + H / 2} ${x2},${a.y + H / 2} ${x2},${b.y + H + 4}`;
    }
    return `<path class="edge" d="${d}"/>`;
  }).join("");

  const nodes = dag.nodes.map((n) => {
    const r = latest[n.id];
    const st = r ? r.status : "";
    const sub = r ? `${st} · ${fmtSec(r.duration_seconds)}` : "not run yet";
    return `<g class="node ${esc(st)}" data-id="${esc(n.id)}" transform="translate(${pos[n.id].x},${pos[n.id].y})" tabindex="0">
      <rect width="${W}" height="${H}" rx="10"/><text x="12" y="23">${esc(n.id)}</text><text class="sub" x="12" y="41">${esc(sub)}</text></g>`;
  }).join("");
  $("#dag").innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="DVC pipeline graph">
    <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#71717a"/></marker></defs>
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

// ---- monitoring ----
async function loadMonitoring() {
  const dash = `${LINKS.grafana}/d/complaint-router/financial-complaint-router?orgId=1&refresh=10s&theme=dark&kiosk`;
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

// ---- init ----
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

  await loadLookups();
  refreshStatus();
  setInterval(refreshStatus, 15000);
  let start = "route";
  try { start = localStorage.getItem("cr.view") || "route"; } catch { /* ignore */ }
  showView(start);
  validateInput();
}

// team list (for corrections) and example complaints
async function loadLookups() {
  try { categories = await api("/api/v1/categories"); } catch { categories = []; }
  try {
    const ex = await api("/api/v1/examples");
    $("#example-chips").innerHTML = ex.map((e, i) => `<button class="chip" data-i="${i}">${esc(e.title)}</button>`).join("");
    document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
      $("#complaint").value = ex[Number(c.dataset.i)].text; validateInput(); routeComplaint();
    }));
  } catch { $("#example-chips").innerHTML = '<span class="muted small">Examples unavailable while the server is offline.</span>'; }
}

document.addEventListener("DOMContentLoaded", init);
