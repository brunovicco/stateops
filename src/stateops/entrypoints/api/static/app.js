"use strict";

const byId = (id) => document.getElementById(id);

const ui = {
  actionContent: byId("action-content"),
  actionEmpty: byId("action-empty"),
  actionName: byId("action-name"),
  approvalDescription: byId("approval-description"),
  approvalPanel: byId("approval-panel"),
  approveButton: byId("approve-button"),
  attemptValue: byId("attempt-value"),
  branchCount: byId("branch-count"),
  branchDots: byId("branch-dots"),
  branchMeter: byId("branch-meter"),
  captureButton: byId("capture-button"),
  checkpointValue: byId("checkpoint-value"),
  confidenceFill: byId("confidence-fill"),
  confidenceValue: byId("confidence-value"),
  currentError: byId("current-error"),
  deployment: byId("deployment"),
  errorAfter: byId("error-after"),
  errorBefore: byId("error-before"),
  errorDelta: byId("error-delta"),
  evidenceCount: byId("evidence-count"),
  evidenceStrip: byId("evidence-strip"),
  form: byId("incident-form"),
  headerIncident: byId("header-incident"),
  healthLabel: byId("health-label"),
  healthPill: byId("health-pill"),
  hypothesisCount: byId("hypothesis-count"),
  incidentId: byId("incident-id"),
  loadButton: byId("load-button"),
  outcomeAfter: byId("outcome-after"),
  outcomeBefore: byId("outcome-before"),
  outcomeDescription: byId("outcome-description"),
  outcomePanel: byId("outcome-panel"),
  parameterList: byId("parameter-list"),
  phaseBadge: byId("phase-badge"),
  reasoningStatus: byId("reasoning-status"),
  rejectButton: byId("reject-button"),
  resetButton: byId("reset-button"),
  riskBadge: byId("risk-badge"),
  rootHypothesis: byId("root-hypothesis"),
  rootSummary: byId("root-summary"),
  service: byId("service"),
  severityValue: byId("severity-value"),
  sparkline: document.querySelector(".sparkline"),
  startButton: byId("start-button"),
  statusMessage: byId("status-message"),
  timelineList: byId("timeline-list"),
};

const graphNodes = Array.from(document.querySelectorAll(".graph-node"));
const graphEdges = Array.from(document.querySelectorAll(".graph-edge"));

const phasePosition = {
  received: 0,
  enriching: 0,
  classified: 0,
  hypotheses_generated: 1,
  investigating: 2,
  evidence_ready: 3,
  planning: 4,
  waiting_approval: 5,
  executing: 6,
  verifying: 7,
  resolved: 8,
  escalated: 8,
  failed: 8,
};

let latestState = null;
let busy = false;

function makeIncidentId() {
  const now = new Date();
  const date = now.toISOString().slice(0, 10).replaceAll("-", "");
  const time = now.toTimeString().slice(0, 8).replaceAll(":", "");
  return `INC-DEMO-${date}-${time}`;
}

function setText(element, value) {
  element.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
}

function setStatus(message, kind = "") {
  setText(ui.statusMessage, message);
  ui.statusMessage.className = `status-message ${kind}`.trim();
}

function setBusy(nextBusy, message = "") {
  busy = nextBusy;
  document.body.classList.toggle("is-busy", nextBusy);
  ui.startButton.disabled = nextBusy;
  ui.loadButton.disabled = nextBusy;
  ui.approveButton.disabled = nextBusy;
  ui.rejectButton.disabled = nextBusy;
  if (message) {
    setStatus(message, nextBusy ? "running" : "");
  }
}

function formatPercent(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${numeric.toFixed(numeric < 1 ? 1 : 1)}%` : "—";
}

function formatPhase(phase) {
  return String(phase || "idle").replaceAll("_", " ").toUpperCase();
}

function formatTime(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function normalizedParameters(parameters) {
  if (!Array.isArray(parameters)) {
    return [];
  }
  return parameters.flatMap((parameter) => {
    if (Array.isArray(parameter) && parameter.length >= 2) {
      return [{ name: parameter[0], value: parameter[1] }];
    }
    if (parameter && typeof parameter === "object" && "name" in parameter && "value" in parameter) {
      return [{ name: parameter.name, value: parameter.value }];
    }
    return [];
  });
}

function createBranchIndicators(hypotheses, evidence) {
  const completed = new Set(evidence.map((item) => item.hypothesis_id));
  ui.branchDots.replaceChildren();
  ui.branchMeter.replaceChildren();

  hypotheses.forEach((hypothesis) => {
    const dot = document.createElement("i");
    dot.classList.toggle("complete", completed.has(hypothesis.id));
    dot.title = String(hypothesis.id || "branch");
    ui.branchDots.append(dot);

    const bar = document.createElement("i");
    bar.classList.toggle("complete", completed.has(hypothesis.id));
    ui.branchMeter.append(bar);
  });
}

function renderGraph(phase) {
  const position = phasePosition[phase] ?? -1;
  const terminal = phase === "resolved";

  graphNodes.forEach((node, index) => {
    node.classList.toggle("complete", terminal || index < position);
    node.classList.toggle("active", !terminal && index === position);
    node.classList.toggle("resolved", terminal && index === graphNodes.length - 1);
  });
  graphEdges.forEach((edge, index) => {
    edge.classList.toggle("complete", terminal || index < position);
  });
}

function renderEvidence(evidence) {
  ui.evidenceStrip.replaceChildren();
  evidence.slice(0, 5).forEach((item) => {
    const chip = document.createElement("span");
    chip.className = "evidence-chip";
    chip.classList.toggle("supports", item.supports === true);
    chip.textContent = `${item.hypothesis_id || item.id || "E"} ${item.supports ? "SUPPORTS" : "REFUTES"}`;
    ui.evidenceStrip.append(chip);
  });
}

function renderAction(action) {
  const hasAction = Boolean(action && action.id);
  ui.actionEmpty.hidden = hasAction;
  ui.actionContent.hidden = !hasAction;
  ui.parameterList.replaceChildren();

  if (!hasAction) {
    setText(ui.actionName, null);
    setText(ui.riskBadge, null);
    ui.riskBadge.className = "risk-badge";
    return;
  }

  setText(ui.actionName, action.kind);
  setText(ui.riskBadge, String(action.risk || "unknown").toUpperCase());
  ui.riskBadge.className = `risk-badge ${String(action.risk || "").toLowerCase()}`;

  normalizedParameters(action.parameters).slice(0, 4).forEach((parameter) => {
    const row = document.createElement("div");
    row.className = "parameter-row";
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    setText(term, parameter.name);
    setText(description, parameter.value);
    description.title = String(parameter.value);
    row.append(term, description);
    ui.parameterList.append(row);
  });
}

function renderTimeline(timeline) {
  ui.timelineList.replaceChildren();
  if (timeline.length === 0) {
    const empty = document.createElement("li");
    empty.className = "timeline-empty";
    empty.textContent = "Os eventos aparecerão durante a execução.";
    ui.timelineList.append(empty);
    return;
  }

  timeline.slice(-7).forEach((item) => {
    const entry = document.createElement("li");
    entry.className = "timeline-item";
    const eventBox = document.createElement("div");
    const event = document.createElement("span");
    const phase = document.createElement("span");
    const time = document.createElement("time");
    event.className = "timeline-event";
    phase.className = "timeline-phase";
    time.className = "timeline-time";
    setText(event, item.event);
    setText(phase, formatPhase(item.phase));
    setText(time, formatTime(item.occurred_at));
    if (item.occurred_at) {
      time.dateTime = String(item.occurred_at);
    }
    eventBox.append(event, phase);
    entry.append(eventBox, time);
    ui.timelineList.append(entry);
  });
}

function renderState(state) {
  if (!state || typeof state !== "object") {
    return;
  }
  latestState = state;

  const phase = String(state.phase || "idle");
  const incident = state.incident && typeof state.incident === "object" ? state.incident : {};
  const hypotheses = Array.isArray(state.hypotheses) ? state.hypotheses : [];
  const evidence = Array.isArray(state.evidence) ? state.evidence : [];
  const rootCause = state.root_cause && typeof state.root_cause === "object" ? state.root_cause : null;
  const verification = state.verification_result && typeof state.verification_result === "object"
    ? state.verification_result
    : null;
  const candidates = Array.isArray(state.candidate_actions) ? state.candidate_actions : [];
  const action = state.selected_action || candidates[0] || null;
  const timeline = Array.isArray(state.timeline) ? state.timeline : [];

  setText(ui.headerIncident, state.incident_id || ui.incidentId.value);
  setText(ui.phaseBadge, formatPhase(phase));
  ui.phaseBadge.dataset.phase = ["resolved", "waiting_approval", "failed", "escalated"].includes(phase)
    ? phase
    : "running";
  setText(ui.severityValue, String(state.severity || "pending").toUpperCase());
  ui.severityValue.classList.toggle("critical", state.severity === "critical");
  setText(ui.attemptValue, state.attempts ?? 0);

  const displayError = verification?.error_rate_after ?? incident.error_rate_after;
  setText(ui.currentError, formatPercent(displayError));
  if (verification?.recovered) {
    setText(ui.errorDelta, "RECOVERED");
    ui.errorDelta.className = "metric-delta recovered";
    ui.sparkline.classList.add("recovered");
  } else if (incident.error_rate_after !== undefined && incident.error_rate_before !== undefined) {
    const delta = Number(incident.error_rate_after) - Number(incident.error_rate_before);
    setText(ui.errorDelta, `+${delta.toFixed(1)} PTS`);
    ui.errorDelta.className = "metric-delta";
    ui.sparkline.classList.remove("recovered");
  }

  setText(ui.hypothesisCount, hypotheses.length);
  setText(ui.branchCount, hypotheses.length);
  setText(ui.evidenceCount, `${evidence.length} EVIDENCES`);
  createBranchIndicators(hypotheses, evidence);

  if (rootCause) {
    const confidence = Number(rootCause.confidence || 0);
    setText(ui.confidenceValue, `${Math.round(confidence * 100)}%`);
    setText(ui.rootHypothesis, rootCause.hypothesis_id || "SELECTED");
    ui.confidenceFill.style.width = `${Math.max(0, Math.min(100, confidence * 100))}%`;
    setText(ui.rootSummary, rootCause.summary);
    ui.rootSummary.classList.remove("muted");
    setText(ui.reasoningStatus, "SYNTHESIZED");
    ui.reasoningStatus.classList.add("ready");
  }
  renderEvidence(evidence);
  renderAction(action);
  renderTimeline(timeline);
  renderGraph(phase);

  const waiting = phase === "waiting_approval";
  ui.approvalPanel.hidden = !waiting;
  if (waiting && action) {
    setText(
      ui.approvalDescription,
      `${action.kind} · risk ${action.risk || "unknown"} · revision ${action.revision || 1}`,
    );
  }

  const resolved = phase === "resolved";
  ui.outcomePanel.hidden = !resolved;
  if (resolved && verification) {
    setText(ui.outcomeBefore, formatPercent(verification.error_rate_before));
    setText(ui.outcomeAfter, formatPercent(verification.error_rate_after));
    const effect = state.execution_result?.synthetic_effect || "simulated action";
    setText(ui.outcomeDescription, `${effect} · recovery confirmed · idempotent execution`);
  }

  if (phase === "failed") {
    const errors = Array.isArray(state.errors) ? state.errors : [];
    const latestError = errors.at(-1);
    setStatus(latestError?.message || "O workflow terminou em estado de falha.", "error");
  } else if (waiting) {
    setStatus("Checkpoint persistido. Aguardando decisão humana.");
  } else if (resolved) {
    setStatus("Execução concluída e recuperação verificada.");
  } else if (busy) {
    setStatus(`Processando fase ${formatPhase(phase)}…`, "running");
  }
}

async function responseError(response) {
  const body = await response.text();
  try {
    const parsed = JSON.parse(body);
    return parsed.detail || parsed.message || `HTTP ${response.status}`;
  } catch {
    return body || `HTTP ${response.status}`;
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.json();
}

async function refreshHistory(incidentId) {
  try {
    const history = await fetchJson(`/incidents/${encodeURIComponent(incidentId)}/history`);
    setText(ui.checkpointValue, Array.isArray(history) ? history.length : 0);
  } catch {
    setText(ui.checkpointValue, "—");
  }
}

function parseSseBlock(block) {
  const data = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) {
    return;
  }
  renderState(JSON.parse(data));
}

async function consumeStateStream(response) {
  if (!response.body) {
    throw new Error("Este navegador não disponibilizou o stream da resposta.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      parseSseBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) {
      break;
    }
  }
  if (buffer.trim()) {
    parseSseBlock(buffer);
  }
}

function incidentPayload() {
  return {
    incident_id: ui.incidentId.value.trim(),
    service: ui.service.value.trim(),
    error_rate_before: Number(ui.errorBefore.value),
    error_rate_after: Number(ui.errorAfter.value),
    deployment: ui.deployment.value.trim(),
    started_at: new Date().toISOString(),
  };
}

async function startIncident(event) {
  event.preventDefault();
  if (!ui.form.reportValidity()) {
    return;
  }
  const payload = incidentPayload();
  setBusy(true, "Abrindo stream do grafo…");
  ui.outcomePanel.hidden = true;
  ui.approvalPanel.hidden = true;
  setText(ui.headerIncident, payload.incident_id);

  try {
    const response = await fetch(`/incidents/${encodeURIComponent(payload.incident_id)}/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    await consumeStateStream(response);
    await refreshHistory(payload.incident_id);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Falha ao iniciar incidente.", "error");
  } finally {
    setBusy(false);
  }
}

async function loadIncident() {
  const incidentId = ui.incidentId.value.trim();
  if (!incidentId) {
    ui.incidentId.focus();
    return;
  }
  setBusy(true, "Carregando checkpoint persistido…");
  try {
    const state = await fetchJson(`/incidents/${encodeURIComponent(incidentId)}`);
    renderState(state);
    await refreshHistory(incidentId);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Thread não encontrada.", "error");
  } finally {
    setBusy(false);
  }
}

async function submitDecision(decision) {
  const incidentId = String(latestState?.incident_id || ui.incidentId.value).trim();
  const candidates = Array.isArray(latestState?.candidate_actions) ? latestState.candidate_actions : [];
  const action = latestState?.selected_action || candidates[0];
  if (!incidentId || !action?.id) {
    setStatus("A execução não possui uma ação selecionada.", "error");
    return;
  }

  setBusy(true, decision === "approved" ? "Retomando execução aprovada…" : "Replanejando…");
  try {
    const result = await fetchJson(`/incidents/${encodeURIComponent(incidentId)}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        action_id: action.id,
        comment: "Decision submitted from StateOps Control Room",
      }),
    });
    renderState(result.state);
    await refreshHistory(incidentId);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Falha ao enviar decisão.", "error");
  } finally {
    setBusy(false);
  }
}

function resetConsole() {
  latestState = null;
  ui.form.reset();
  ui.incidentId.value = makeIncidentId();
  ui.service.value = "checkout-service";
  ui.errorBefore.value = "0.2";
  ui.errorAfter.value = "18.0";
  ui.deployment.value = "v2.31";
  setText(ui.headerIncident, "NO ACTIVE INCIDENT");
  setText(ui.phaseBadge, "IDLE");
  ui.phaseBadge.dataset.phase = "idle";
  setText(ui.severityValue, null);
  setText(ui.checkpointValue, 0);
  setText(ui.attemptValue, 0);
  setText(ui.currentError, null);
  setText(ui.errorDelta, "NO SIGNAL");
  ui.errorDelta.className = "metric-delta";
  setText(ui.hypothesisCount, 0);
  setText(ui.evidenceCount, "0 EVIDENCES");
  setText(ui.branchCount, 0);
  setText(ui.confidenceValue, null);
  setText(ui.rootHypothesis, "PENDING");
  ui.confidenceFill.style.width = "0";
  setText(ui.rootSummary, "Inicie um incidente para visualizar a síntese das evidências produzidas pelos ramos.");
  ui.rootSummary.classList.add("muted");
  setText(ui.reasoningStatus, "PENDING");
  ui.reasoningStatus.classList.remove("ready");
  renderEvidence([]);
  createBranchIndicators([], []);
  renderAction(null);
  renderTimeline([]);
  renderGraph("idle");
  ui.approvalPanel.hidden = true;
  ui.outcomePanel.hidden = true;
  ui.sparkline.classList.remove("recovered");
  setStatus("Pronto para iniciar uma nova execução.");
}

function setCaptureMode(enabled) {
  document.body.classList.toggle("capture-mode", enabled);
  ui.captureButton.setAttribute("aria-pressed", String(enabled));
  ui.captureButton.title = enabled ? "Sair do modo captura" : "Expandir para captura";
}

function toggleCaptureMode() {
  setCaptureMode(!document.body.classList.contains("capture-mode"));
}

async function checkHealth() {
  try {
    const result = await fetchJson("/healthz");
    const online = result.status === "ok";
    ui.healthPill.dataset.status = online ? "online" : "offline";
    setText(ui.healthLabel, online ? "API online" : "API degradada");
  } catch {
    ui.healthPill.dataset.status = "offline";
    setText(ui.healthLabel, "API offline");
  }
}

ui.form.addEventListener("submit", startIncident);
ui.loadButton.addEventListener("click", loadIncident);
ui.approveButton.addEventListener("click", () => submitDecision("approved"));
ui.rejectButton.addEventListener("click", () => submitDecision("rejected"));
ui.resetButton.addEventListener("click", resetConsole);
ui.captureButton.addEventListener("click", toggleCaptureMode);

async function initialize() {
  resetConsole();
  const parameters = new URLSearchParams(window.location.search);
  const incidentId = parameters.get("incident");
  if (parameters.get("capture") === "1") {
    setCaptureMode(true);
  }
  await checkHealth();
  if (incidentId && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(incidentId)) {
    ui.incidentId.value = incidentId;
    await loadIncident();
  }
}

initialize();
