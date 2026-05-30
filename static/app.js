const els = {
  modelSelect: document.querySelector("#modelSelect"),
  expressionInput: document.querySelector("#expressionInput"),
  parameterInput: document.querySelector("#parameterInput"),
  parameterSlider: document.querySelector("#parameterSlider"),
  playPauseButton: document.querySelector("#playPauseButton"),
  restartButton: document.querySelector("#restartButton"),
  speedSelect: document.querySelector("#speedSelect"),
  xMinInput: document.querySelector("#xMinInput"),
  xMaxInput: document.querySelector("#xMaxInput"),
  rMinInput: document.querySelector("#rMinInput"),
  rMaxInput: document.querySelector("#rMaxInput"),
  analyzeButton: document.querySelector("#analyzeButton"),
  equilibriaList: document.querySelector("#equilibriaList"),
  bifurcationList: document.querySelector("#bifurcationList"),
  systemSummary: document.querySelector("#systemSummary"),
  phaseCanvas: document.querySelector("#phaseCanvas"),
  bifurcationCanvas: document.querySelector("#bifurcationCanvas"),
  errorBox: document.querySelector("#errorBox"),
  oneDTabButton: document.querySelector("#oneDTabButton"),
  linear2dTabButton: document.querySelector("#linear2dTabButton"),
  oneDControls: document.querySelector("#oneDControls"),
  linear2dControls: document.querySelector("#linear2dControls"),
  oneDWorkspace: document.querySelector("#oneDWorkspace"),
  linear2dWorkspace: document.querySelector("#linear2dWorkspace"),
  linearAInput: document.querySelector("#linearAInput"),
  linearBInput: document.querySelector("#linearBInput"),
  linearCInput: document.querySelector("#linearCInput"),
  linearDInput: document.querySelector("#linearDInput"),
  linearCalculateButton: document.querySelector("#linearCalculateButton"),
  linearMatrixSummary: document.querySelector("#linearMatrixSummary"),
  linearClassificationSummary: document.querySelector("#linearClassificationSummary"),
  linearInvariantSummary: document.querySelector("#linearInvariantSummary"),
  linearEigenList: document.querySelector("#linearEigenList"),
  linearSolutionBox: document.querySelector("#linearSolutionBox"),
  nullclineCanvas: document.querySelector("#nullclineCanvas"),
  linearPhaseCanvas: document.querySelector("#linearPhaseCanvas"),
  linearErrorBox: document.querySelector("#linearErrorBox"),
};

const colors = {
  stable: "#138a5b",
  unstable: "#c7473f",
  semistable: "#b7791f",
  unknown: "#6b7280",
  axis: "#6f7d80",
  grid: "#dfe7e5",
  curve: "#0f766e",
  nullclineX: "#2563eb",
  nullclineY: "#b7791f",
  trajectory: "#6d45e8",
  eigenV1: "#0ea5a4",
  eigenV2: "#e11d48",
  vector: "#87959a",
  text: "#243033",
};

let models = [];
let activeResult = null;
let debounceHandle = null;
let animationFrameId = null;
let isAnimating = false;
let animationDirection = 1;
let lastAnimationTimestamp = null;
let lastFrameDispatch = 0;
let frameInFlight = false;
let queuedFrameParameter = null;
let activeTab = "oneD";
let linear2dResult = null;

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  const number = Number(value);
  if (Math.abs(number) < 1e-9) return "0";
  return number.toLocaleString("es-AR", { maximumFractionDigits: 4 });
}

function stabilityLabel(value) {
  return {
    stable: "estable",
    unstable: "inestable",
    semistable: "semestable",
    unknown: "indeterminado",
  }[value] || value;
}

function pill(text, className = "") {
  const span = document.createElement("span");
  span.className = `pill ${className}`.trim();
  span.textContent = text;
  return span;
}

function setError(message) {
  els.errorBox.hidden = !message;
  els.errorBox.textContent = message || "";
}

function setLinearError(message) {
  els.linearErrorBox.hidden = !message;
  els.linearErrorBox.textContent = message || "";
}

function setActiveTab(tab) {
  activeTab = tab;
  if (tab !== "oneD") {
    stopAnimation();
  }
  [
    [els.oneDTabButton, tab === "oneD"],
    [els.linear2dTabButton, tab === "linear2d"],
    [els.oneDControls, tab === "oneD"],
    [els.linear2dControls, tab === "linear2d"],
    [els.oneDWorkspace, tab === "oneD"],
    [els.linear2dWorkspace, tab === "linear2d"],
  ].forEach(([element, isActive]) => {
    element.classList.toggle("active", isActive);
  });

  if (tab === "linear2d") {
    if (linear2dResult) {
      renderLinear2d(linear2dResult);
    } else {
      calculateLinear2d().catch((error) => setLinearError(error.message));
    }
  } else if (activeResult) {
    renderPhase(activeResult);
    renderBifurcation(activeResult);
  }
}

function selectedModel() {
  return models.find((model) => model.key === els.modelSelect.value) || models[0];
}

function applyModel(model) {
  els.modelSelect.value = model.key;
  els.expressionInput.value = model.expression;
  els.parameterInput.value = model.defaultParameter;
  els.parameterSlider.min = model.rRange[0];
  els.parameterSlider.max = model.rRange[1];
  els.parameterSlider.value = model.defaultParameter;
  els.xMinInput.value = model.xRange[0];
  els.xMaxInput.value = model.xRange[1];
  els.rMinInput.value = model.rRange[0];
  els.rMaxInput.value = model.rRange[1];
}

function payload() {
  return {
    model: els.modelSelect.value,
    expression: els.expressionInput.value,
    parameter: Number(els.parameterInput.value),
    xRange: [Number(els.xMinInput.value), Number(els.xMaxInput.value)],
    rRange: [Number(els.rMinInput.value), Number(els.rMaxInput.value)],
  };
}

function framePayload(parameter = Number(els.parameterInput.value)) {
  return {
    ...payload(),
    parameter,
  };
}

async function analyze() {
  setError("");
  const response = await fetch("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload()),
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.error || "No se pudo analizar el sistema.");
  }
  activeResult = result;
  renderSummary(result);
  renderPhase(result);
  renderBifurcation(result);
}

async function refreshFrame(parameter) {
  if (!activeResult) {
    await analyze();
    return;
  }
  if (frameInFlight) {
    queuedFrameParameter = parameter;
    return;
  }

  frameInFlight = true;
  try {
    let response = await fetch("/api/frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(framePayload(parameter)),
    });
    if (response.status === 404) {
      response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(framePayload(parameter)),
      });
    }
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "No se pudo actualizar el fotograma.");
    }
    activeResult = {
      ...activeResult,
      ...result,
      bifurcation: activeResult.bifurcation,
      bifurcationPoints: activeResult.bifurcationPoints,
    };
    renderSummary(activeResult);
    renderPhase(activeResult);
    renderBifurcation(activeResult);
  } finally {
    frameInFlight = false;
    if (queuedFrameParameter !== null) {
      const next = queuedFrameParameter;
      queuedFrameParameter = null;
      refreshFrame(next).catch((error) => setError(error.message));
    }
  }
}

function scheduleAnalyze() {
  window.clearTimeout(debounceHandle);
  debounceHandle = window.setTimeout(() => {
    analyze().catch((error) => setError(error.message));
  }, 180);
}

function scheduleFrameRefresh(parameter = Number(els.parameterInput.value)) {
  window.clearTimeout(debounceHandle);
  debounceHandle = window.setTimeout(() => {
    refreshFrame(parameter).catch((error) => setError(error.message));
  }, 100);
}

function syncParameterInputs(value) {
  const normalized = Number(value);
  els.parameterInput.value = normalized.toFixed(4).replace(/\.?0+$/, "");
  els.parameterSlider.value = String(normalized);
}

function setAnimationButtonState() {
  els.playPauseButton.innerHTML = isAnimating ? "&#10074;&#10074;" : "&#9654;";
  els.playPauseButton.title = isAnimating ? "Pausar" : "Reproducir";
  els.playPauseButton.setAttribute("aria-label", isAnimating ? "Pausar animacion" : "Reproducir animacion");
}

function stopAnimation() {
  isAnimating = false;
  lastAnimationTimestamp = null;
  if (animationFrameId !== null) {
    window.cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }
  setAnimationButtonState();
}

function animationStep(timestamp) {
  if (!isAnimating) return;
  if (lastAnimationTimestamp === null) {
    lastAnimationTimestamp = timestamp;
  }

  const elapsedSeconds = Math.max(0, (timestamp - lastAnimationTimestamp) / 1000);
  lastAnimationTimestamp = timestamp;
  const rMin = Number(els.rMinInput.value);
  const rMax = Number(els.rMaxInput.value);
  const span = rMax - rMin;
  const duration = Number(els.speedSelect.value);
  let next = Number(els.parameterInput.value) + animationDirection * (span / duration) * elapsedSeconds;

  if (next >= rMax) {
    next = rMax;
    animationDirection = -1;
  } else if (next <= rMin) {
    next = rMin;
    animationDirection = 1;
  }

  syncParameterInputs(next);
  if (timestamp - lastFrameDispatch >= 85) {
    lastFrameDispatch = timestamp;
    refreshFrame(next).catch((error) => {
      stopAnimation();
      setError(error.message);
    });
  }

  animationFrameId = window.requestAnimationFrame(animationStep);
}

function toggleAnimation() {
  if (isAnimating) {
    stopAnimation();
    return;
  }
  const rMin = Number(els.rMinInput.value);
  const rMax = Number(els.rMaxInput.value);
  if (!Number.isFinite(rMin) || !Number.isFinite(rMax) || rMin >= rMax) {
    setError("El rango de r debe tener minimo menor que maximo para animar.");
    return;
  }
  setError("");
  isAnimating = true;
  lastAnimationTimestamp = null;
  lastFrameDispatch = 0;
  setAnimationButtonState();
  animationFrameId = window.requestAnimationFrame(animationStep);
}

function restartAnimation() {
  stopAnimation();
  animationDirection = 1;
  const rMin = Number(els.rMinInput.value);
  syncParameterInputs(rMin);
  refreshFrame(rMin).catch((error) => setError(error.message));
}

function renderSummary(result) {
  els.equilibriaList.replaceChildren();
  if (!result.equilibria.length) {
    els.equilibriaList.append(pill("sin equilibrios visibles", "unknown"));
  } else {
    result.equilibria.forEach((item) => {
      els.equilibriaList.append(
        pill(`x* = ${formatNumber(item.x)} · ${stabilityLabel(item.stability)}`, item.stability),
      );
    });
  }

  els.bifurcationList.replaceChildren();
  if (!result.bifurcationPoints.length) {
    els.bifurcationList.append(pill("sin candidato en el rango", "unknown"));
  } else {
    result.bifurcationPoints.forEach((item) => {
      els.bifurcationList.append(
        pill(`r = ${formatNumber(item.r)}, x = ${formatNumber(item.x)} · ${item.type}`, "semistable"),
      );
    });
  }

  els.systemSummary.replaceChildren(
    pill(`${result.model.label}`),
    pill(`r = ${formatNumber(result.parameter)}`),
    pill(`x′ = ${result.model.expression}`),
  );
}

function resizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(360, Math.floor(rect.width * ratio));
  const height = Math.max(220, Math.floor(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width: width / ratio, height: height / ratio };
}

function drawGrid(ctx, plot, xTicks, yTicks, xScale, yScale) {
  ctx.save();
  ctx.strokeStyle = colors.grid;
  ctx.lineWidth = 1;
  ctx.font = "12px Inter, system-ui, sans-serif";
  ctx.fillStyle = colors.axis;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  xTicks.forEach((tick) => {
    const x = xScale(tick);
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, plot.bottom);
    ctx.stroke();
    ctx.fillText(formatNumber(tick), x, plot.bottom + 8);
  });

  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  yTicks.forEach((tick) => {
    const y = yScale(tick);
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
    ctx.fillText(formatNumber(tick), plot.left - 8, y);
  });
  ctx.restore();
}

function ticks(min, max, count = 5) {
  const values = [];
  for (let i = 0; i < count; i += 1) {
    values.push(min + ((max - min) * i) / (count - 1));
  }
  return values;
}

function drawArrow(ctx, fromX, y, toX, color) {
  const head = toX >= fromX ? 1 : -1;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(fromX, y);
  ctx.lineTo(toX, y);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(toX, y);
  ctx.lineTo(toX - head * 8, y - 5);
  ctx.lineTo(toX - head * 8, y + 5);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function renderPhase(result) {
  const { ctx, width, height } = resizeCanvas(els.phaseCanvas);
  ctx.clearRect(0, 0, width, height);

  const plot = { left: 56, right: width - 22, top: 24, bottom: height * 0.62 };
  const lineY = height * 0.8;
  const xMin = result.xRange[0];
  const xMax = result.xRange[1];
  const finiteY = result.phase.points.map((point) => point.y).filter((value) => value !== null);
  let yMin = Math.min(...finiteY, 0);
  let yMax = Math.max(...finiteY, 0);
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax) || Math.abs(yMax - yMin) < 1e-9) {
    yMin = -1;
    yMax = 1;
  }
  const padY = (yMax - yMin) * 0.12;
  yMin -= padY;
  yMax += padY;

  const xScale = (x) => plot.left + ((x - xMin) / (xMax - xMin)) * (plot.right - plot.left);
  const yScale = (y) => plot.bottom - ((y - yMin) / (yMax - yMin)) * (plot.bottom - plot.top);
  drawGrid(ctx, plot, ticks(xMin, xMax), ticks(yMin, yMax), xScale, yScale);

  if (yMin <= 0 && yMax >= 0) {
    ctx.strokeStyle = colors.axis;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(plot.left, yScale(0));
    ctx.lineTo(plot.right, yScale(0));
    ctx.stroke();
  }

  ctx.save();
  ctx.strokeStyle = colors.curve;
  ctx.lineWidth = 2.4;
  ctx.beginPath();
  let started = false;
  result.phase.points.forEach((point) => {
    if (point.y === null) {
      started = false;
      return;
    }
    const px = xScale(point.x);
    const py = yScale(point.y);
    if (!started) {
      ctx.moveTo(px, py);
      started = true;
    } else {
      ctx.lineTo(px, py);
    }
  });
  ctx.stroke();
  ctx.restore();

  ctx.save();
  ctx.strokeStyle = colors.axis;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(plot.left, lineY);
  ctx.lineTo(plot.right, lineY);
  ctx.stroke();
  ctx.fillStyle = colors.text;
  ctx.font = "13px Inter, system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText("x", plot.right, lineY + 22);
  ctx.restore();

  const roots = result.equilibria.map((item) => item.x).sort((a, b) => a - b);
  const boundaries = [xMin, ...roots, xMax];
  for (let i = 0; i < boundaries.length - 1; i += 1) {
    const left = boundaries[i];
    const right = boundaries[i + 1];
    if (right - left <= 1e-6) continue;
    const mid = (left + right) / 2;
    const nearest = result.phase.points.reduce((best, point) => {
      if (point.y === null) return best;
      return Math.abs(point.x - mid) < Math.abs(best.x - mid) ? point : best;
    }, result.phase.points.find((point) => point.y !== null));
    if (!nearest || nearest.y === null || Math.abs(nearest.y) < 1e-9) continue;
    const direction = nearest.y > 0 ? 1 : -1;
    const intervalWidth = xScale(right) - xScale(left);
    const margin = Math.min(18, Math.abs(intervalWidth) * 0.25);
    const from = direction > 0 ? xScale(left) + margin : xScale(right) - margin;
    const to = direction > 0 ? xScale(right) - margin : xScale(left) + margin;
    drawArrow(ctx, from, lineY, to, colors.axis);
  }

  result.equilibria.forEach((item) => {
    const x = xScale(item.x);
    ctx.save();
    ctx.fillStyle = colors[item.stability] || colors.unknown;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, lineY, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = colors.text;
    ctx.font = "12px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(formatNumber(item.x), x, lineY + 12);
    ctx.restore();
  });
}

function groupedSegments(points) {
  if (!points.length) return [];
  const groups = [];
  let current = [points[0]];
  for (let i = 1; i < points.length; i += 1) {
    const previous = points[i - 1];
    const point = points[i];
    if (point.stability === previous.stability) {
      current.push(point);
    } else {
      current.push(point);
      groups.push({ stability: previous.stability, points: current });
      current = [point];
    }
  }
  groups.push({ stability: current[current.length - 1].stability, points: current });
  return groups;
}

function renderBifurcation(result) {
  const { ctx, width, height } = resizeCanvas(els.bifurcationCanvas);
  ctx.clearRect(0, 0, width, height);

  const plot = { left: 58, right: width - 24, top: 24, bottom: height - 42 };
  const rMin = result.rRange[0];
  const rMax = result.rRange[1];
  const xMin = result.xRange[0];
  const xMax = result.xRange[1];
  const rScale = (r) => plot.left + ((r - rMin) / (rMax - rMin)) * (plot.right - plot.left);
  const xScale = (x) => plot.bottom - ((x - xMin) / (xMax - xMin)) * (plot.bottom - plot.top);

  drawGrid(ctx, plot, ticks(rMin, rMax), ticks(xMin, xMax), rScale, xScale);

  ctx.save();
  ctx.strokeStyle = colors.axis;
  ctx.lineWidth = 1.4;
  if (rMin <= 0 && rMax >= 0) {
    ctx.beginPath();
    ctx.moveTo(rScale(0), plot.top);
    ctx.lineTo(rScale(0), plot.bottom);
    ctx.stroke();
  }
  if (xMin <= 0 && xMax >= 0) {
    ctx.beginPath();
    ctx.moveTo(plot.left, xScale(0));
    ctx.lineTo(plot.right, xScale(0));
    ctx.stroke();
  }
  ctx.fillStyle = colors.text;
  ctx.font = "13px Inter, system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText("r", plot.right, plot.bottom + 28);
  ctx.textAlign = "left";
  ctx.fillText("x*", plot.left, plot.top - 8);
  ctx.restore();

  result.bifurcation.branches.forEach((branch) => {
    if (branch.kind === "scatter") {
      branch.points.forEach((point) => {
        ctx.save();
        ctx.fillStyle = colors[point.stability] || colors.unknown;
        ctx.globalAlpha = 0.88;
        ctx.beginPath();
        ctx.arc(rScale(point.r), xScale(point.x), 2.8, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      });
      return;
    }

    groupedSegments(branch.points).forEach((segment) => {
      if (segment.points.length < 2) return;
      ctx.save();
      ctx.strokeStyle = colors[segment.stability] || colors.unknown;
      ctx.lineWidth = segment.stability === "semistable" ? 2.2 : 2.8;
      ctx.setLineDash(segment.stability === "unstable" ? [7, 6] : []);
      ctx.beginPath();
      segment.points.forEach((point, index) => {
        const px = rScale(point.r);
        const py = xScale(point.x);
        if (index === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.stroke();
      ctx.restore();
    });
  });

  result.bifurcationPoints.forEach((point) => {
    if (point.r < rMin || point.r > rMax || point.x < xMin || point.x > xMax) return;
    const px = rScale(point.r);
    const py = xScale(point.x);
    ctx.save();
    ctx.strokeStyle = "#1d2527";
    ctx.fillStyle = "#f5f7f8";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(px, py, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(px - 10, py);
    ctx.lineTo(px + 10, py);
    ctx.moveTo(px, py - 10);
    ctx.lineTo(px, py + 10);
    ctx.stroke();
    ctx.restore();
  });

  if (result.parameter >= rMin && result.parameter <= rMax) {
    const currentR = rScale(result.parameter);
    ctx.save();
    ctx.strokeStyle = colors.curve;
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(currentR, plot.top);
    ctx.lineTo(currentR, plot.bottom);
    ctx.stroke();
    ctx.restore();
  }

  result.equilibria.forEach((item) => {
    if (item.x < xMin || item.x > xMax) return;
    ctx.save();
    ctx.fillStyle = colors[item.stability] || colors.unknown;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(rScale(result.parameter), xScale(item.x), 5.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  });
}

function linear2dPayload() {
  const entries = [
    ["a", els.linearAInput],
    ["b", els.linearBInput],
    ["c", els.linearCInput],
    ["d", els.linearDInput],
  ];
  const values = {};
  entries.forEach(([key, input]) => {
    const value = Number(input.value);
    if (!Number.isFinite(value)) {
      throw new Error("Todos los valores de la matriz deben ser numericos.");
    }
    values[key] = value;
  });
  return values;
}

async function calculateLinear2d() {
  setLinearError("");
  const response = await fetch("/api/linear2d", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(linear2dPayload()),
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.error || "No se pudo analizar el sistema 2D.");
  }
  linear2dResult = result;
  renderLinear2d(result);
}

function renderLinear2d(result) {
  els.linearMatrixSummary.replaceChildren(
    pill(`[${formatNumber(result.matrix[0][0])}, ${formatNumber(result.matrix[0][1])}]`),
    pill(`[${formatNumber(result.matrix[1][0])}, ${formatNumber(result.matrix[1][1])}]`),
  );

  els.linearClassificationSummary.replaceChildren(
    pill(result.classification.type, result.classification.stability),
    pill(result.classification.detail),
  );

  els.linearInvariantSummary.replaceChildren(
    pill(`tr = ${formatNumber(result.trace)}`),
    pill(`det = ${formatNumber(result.determinant)}`),
    pill(`Delta = ${formatNumber(result.discriminant)}`),
  );

  els.linearEigenList.replaceChildren();
  result.eigenvectors.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "result-row";
    const multiplicity = item.multiplicity > 1 ? `, multiplicidad ${item.multiplicity}` : "";
    const title = document.createElement("strong");
    title.textContent = `lambda ${index + 1} = ${item.eigenvalueText}${multiplicity}`;
    const vector = document.createElement("span");
    vector.textContent = `v = ${item.vectorText}`;
    row.append(title, vector);
    els.linearEigenList.append(row);
  });

  els.linearSolutionBox.replaceChildren();
  const casePill = pill(result.solution.case);
  els.linearSolutionBox.append(casePill, buildSolutionFormula(result.solution));

  renderNullclines(result);
  renderLinearPhase(result);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function vectorColumn(values) {
  return `
    <span class="column-vector">
      <span>${formatNumber(values[0])}</span>
      <span>${formatNumber(values[1])}</span>
    </span>
  `;
}

function buildSolutionFormula(solution) {
  const formula = solution.formula || {};
  const card = document.createElement("div");
  card.className = "formula-card";
  const condition = document.createElement("p");
  condition.className = "formula-condition";
  condition.innerHTML = `<strong>Condicion:</strong> ${escapeHtml(solution.case)}.`;
  const equation = document.createElement("div");
  equation.className = "formula-equation";

  if (formula.kind === "realDistinct") {
    equation.innerHTML = `
      <span class="formula-x">X(t)</span> =
      c<sub>1</sub> e<sup>${escapeHtml(formula.lambda1)}t</sup>
      <span class="formula-v1">${vectorColumn(formula.v1)}</span>
      +
      c<sub>2</sub> e<sup>${escapeHtml(formula.lambda2)}t</sup>
      <span class="formula-v2">${vectorColumn(formula.v2)}</span>
    `;
  } else if (formula.kind === "realRepeatedDiagonalizable") {
    equation.innerHTML = `
      <span class="formula-x">X(t)</span> =
      c<sub>1</sub> e<sup>${escapeHtml(formula.lambda)}t</sup>
      <span class="formula-v1">${vectorColumn(formula.v1)}</span>
      +
      c<sub>2</sub> e<sup>${escapeHtml(formula.lambda)}t</sup>
      <span class="formula-v2">${vectorColumn(formula.v2)}</span>
    `;
  } else if (formula.kind === "realRepeatedDefective") {
    equation.innerHTML = `
      <span class="formula-x">X(t)</span> =
      c<sub>1</sub> e<sup>${escapeHtml(formula.lambda)}t</sup>
      <span class="formula-v1">${vectorColumn(formula.v1)}</span>
      +
      c<sub>2</sub> e<sup>${escapeHtml(formula.lambda)}t</sup>
      <span class="formula-group">(t <span class="formula-v1">${vectorColumn(formula.v1)}</span> +
      <span class="formula-v2">${vectorColumn(formula.v2)}</span>)</span>
    `;
  } else if (formula.kind === "complexConjugate") {
    equation.innerHTML = `
      <span class="formula-x">X(t)</span> =
      e<sup>${escapeHtml(formula.alpha)}t</sup>
      { c<sub>1</sub>(<span class="formula-v1">${vectorColumn(formula.p)}</span> cos(${escapeHtml(formula.beta)}t)
      - <span class="formula-v2">${vectorColumn(formula.q)}</span> sin(${escapeHtml(formula.beta)}t))
      + c<sub>2</sub>(<span class="formula-v1">${vectorColumn(formula.p)}</span> sin(${escapeHtml(formula.beta)}t)
      + <span class="formula-v2">${vectorColumn(formula.q)}</span> cos(${escapeHtml(formula.beta)}t)) }
    `;
  } else {
    equation.textContent = solution.text;
  }

  card.append(condition, equation);
  return card;
}

function drawAxes(ctx, plot, xScale, yScale) {
  ctx.save();
  ctx.strokeStyle = colors.axis;
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  ctx.moveTo(plot.left, yScale(0));
  ctx.lineTo(plot.right, yScale(0));
  ctx.moveTo(xScale(0), plot.top);
  ctx.lineTo(xScale(0), plot.bottom);
  ctx.stroke();
  ctx.fillStyle = colors.text;
  ctx.font = "13px Inter, system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText("x", plot.right, yScale(0) - 8);
  ctx.textAlign = "left";
  ctx.fillText("y", xScale(0) + 8, plot.top + 12);
  ctx.restore();
}

function lineEndpoints(p, q, limit) {
  const eps = 1e-10;
  if (Math.abs(p) < eps && Math.abs(q) < eps) return [];
  if (Math.abs(q) < eps) return [[0, -limit], [0, limit]];
  if (Math.abs(p) < eps) return [[-limit, 0], [limit, 0]];

  const candidates = [
    [-limit, (p * limit) / q],
    [limit, (-p * limit) / q],
    [(-q * limit) / p, limit],
    [(q * limit) / p, -limit],
  ].filter(([x, y]) => x >= -limit - eps && x <= limit + eps && y >= -limit - eps && y <= limit + eps);

  const unique = [];
  candidates.forEach((point) => {
    if (!unique.some((other) => Math.hypot(other[0] - point[0], other[1] - point[1]) < 1e-6)) {
      unique.push(point);
    }
  });
  return unique.slice(0, 2);
}

function drawLinearGrid(canvas) {
  const { ctx, width, height } = resizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const plot = { left: 46, right: width - 18, top: 18, bottom: height - 38 };
  const limit = 5;
  const xScale = (x) => plot.left + ((x + limit) / (2 * limit)) * (plot.right - plot.left);
  const yScale = (y) => plot.bottom - ((y + limit) / (2 * limit)) * (plot.bottom - plot.top);
  drawGrid(ctx, plot, ticks(-limit, limit, 5), ticks(-limit, limit, 5), xScale, yScale);
  drawAxes(ctx, plot, xScale, yScale);
  return { ctx, width, height, plot, limit, xScale, yScale };
}

function drawOrigin(ctx, xScale, yScale) {
  ctx.save();
  ctx.fillStyle = colors.text;
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(xScale(0), yScale(0), 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function renderNullclines(result) {
  const { ctx, limit, xScale, yScale } = drawLinearGrid(els.nullclineCanvas);
  const palette = { dx: colors.nullclineX, dy: colors.nullclineY };

  result.nullclines.forEach((line) => {
    const [p, q] = line.coefficients;
    const endpoints = lineEndpoints(p, q, limit);
    if (endpoints.length < 2) return;
    ctx.save();
    ctx.strokeStyle = palette[line.id];
    ctx.lineWidth = 2.8;
    ctx.setLineDash(line.id === "dy" ? [8, 6] : []);
    ctx.beginPath();
    ctx.moveTo(xScale(endpoints[0][0]), yScale(endpoints[0][1]));
    ctx.lineTo(xScale(endpoints[1][0]), yScale(endpoints[1][1]));
    ctx.stroke();
    ctx.restore();
  });

  drawOrigin(ctx, xScale, yScale);

  ctx.save();
  ctx.font = "12px Inter, system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  result.nullclines.forEach((line, index) => {
    ctx.fillStyle = palette[line.id];
    ctx.fillText(`${line.label}: ${line.equation} (${line.description})`, 54, 28 + index * 18);
  });
  ctx.restore();
}

function drawEigenvectorLines(ctx, vectorLines, limit, xScale, yScale) {
  const palette = [colors.eigenV1, colors.eigenV2, "#0891b2", "#db2777"];
  (vectorLines || []).forEach((item, index) => {
    const [vx, vy] = item.vector || [];
    if (!Number.isFinite(vx) || !Number.isFinite(vy) || Math.hypot(vx, vy) < 1e-9) return;
    const endpoints = lineEndpoints(-vy, vx, limit);
    if (endpoints.length < 2) return;
    const color = palette[index % palette.length];
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 3;
    ctx.globalAlpha = 0.86;
    ctx.setLineDash(index === 1 ? [12, 7] : []);
    ctx.beginPath();
    ctx.moveTo(xScale(endpoints[0][0]), yScale(endpoints[0][1]));
    ctx.lineTo(xScale(endpoints[1][0]), yScale(endpoints[1][1]));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = "700 13px Inter, system-ui, sans-serif";
    const labelPoint = endpoints[1];
    ctx.fillText(item.label || `v${index + 1}`, xScale(labelPoint[0]) - 24, yScale(labelPoint[1]) + 18);
    ctx.restore();
  });
}

function drawVectorArrow(ctx, x1, y1, x2, y2, color, width = 1.5) {
  const angle = Math.atan2(y2 - y1, x2 - x1);
  const head = 6;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - head * Math.cos(angle - Math.PI / 6), y2 - head * Math.sin(angle - Math.PI / 6));
  ctx.lineTo(x2 - head * Math.cos(angle + Math.PI / 6), y2 - head * Math.sin(angle + Math.PI / 6));
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function renderLinearPhase(result) {
  const { ctx, limit, xScale, yScale } = drawLinearGrid(els.linearPhaseCanvas);
  const [[a, b], [c, d]] = result.matrix;

  for (let ix = -4; ix <= 4; ix += 1) {
    for (let iy = -4; iy <= 4; iy += 1) {
      const vx = a * ix + b * iy;
      const vy = c * ix + d * iy;
      const norm = Math.hypot(vx, vy);
      if (norm < 1e-9) continue;
      const length = 0.34;
      const dx = (vx / norm) * length;
      const dy = (vy / norm) * length;
      drawVectorArrow(ctx, xScale(ix - dx / 2), yScale(iy - dy / 2), xScale(ix + dx / 2), yScale(iy + dy / 2), colors.vector, 1.05);
    }
  }

  drawEigenvectorLines(ctx, result.phase.vectorLines, limit, xScale, yScale);

  result.phase.trajectories.forEach((trajectory) => {
    if (trajectory.length < 2) return;
    ctx.save();
    ctx.strokeStyle = colors.trajectory;
    ctx.lineWidth = 2.4;
    ctx.globalAlpha = 0.9;
    ctx.beginPath();
    trajectory.forEach((point, index) => {
      const px = xScale(point.x);
      const py = yScale(point.y);
      if (index === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
    ctx.restore();

    const end = trajectory[trajectory.length - 1];
    const prev = trajectory[Math.max(0, trajectory.length - 4)];
    drawVectorArrow(ctx, xScale(prev.x), yScale(prev.y), xScale(end.x), yScale(end.y), colors.trajectory, 1.5);
  });

  result.nullclines.forEach((line) => {
    const [p, q] = line.coefficients;
    const endpoints = lineEndpoints(p, q, limit);
    if (endpoints.length < 2) return;
    ctx.save();
    ctx.strokeStyle = line.id === "dx" ? colors.nullclineX : colors.nullclineY;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 2;
    ctx.setLineDash(line.id === "dy" ? [8, 6] : []);
    ctx.beginPath();
    ctx.moveTo(xScale(endpoints[0][0]), yScale(endpoints[0][1]));
    ctx.lineTo(xScale(endpoints[1][0]), yScale(endpoints[1][1]));
    ctx.stroke();
    ctx.restore();
  });

  drawOrigin(ctx, xScale, yScale);
}

async function init() {
  const response = await fetch("/api/models");
  const data = await response.json();
  models = data.models;
  els.modelSelect.replaceChildren(
    ...models.map((model) => {
      const option = document.createElement("option");
      option.value = model.key;
      option.textContent = model.label;
      return option;
    }),
  );
  applyModel(models[0]);
  await analyze();
}

els.modelSelect.addEventListener("change", () => {
  stopAnimation();
  applyModel(selectedModel());
  scheduleAnalyze();
});

els.expressionInput.addEventListener("input", () => {
  stopAnimation();
  if (els.modelSelect.value !== "manual") {
    els.modelSelect.value = "manual";
  }
  scheduleAnalyze();
});

els.parameterInput.addEventListener("input", () => {
  els.parameterSlider.value = els.parameterInput.value;
  scheduleFrameRefresh(Number(els.parameterInput.value));
});

els.parameterSlider.addEventListener("input", () => {
  els.parameterInput.value = els.parameterSlider.value;
  scheduleFrameRefresh(Number(els.parameterSlider.value));
});

[els.xMinInput, els.xMaxInput, els.rMinInput, els.rMaxInput].forEach((input) => {
  input.addEventListener("input", () => {
    stopAnimation();
    els.parameterSlider.min = els.rMinInput.value;
    els.parameterSlider.max = els.rMaxInput.value;
    scheduleAnalyze();
  });
});

els.analyzeButton.addEventListener("click", () => {
  stopAnimation();
  analyze().catch((error) => setError(error.message));
});

els.playPauseButton.addEventListener("click", toggleAnimation);
els.restartButton.addEventListener("click", restartAnimation);

window.addEventListener("resize", () => {
  if (activeTab === "oneD" && activeResult) {
    renderPhase(activeResult);
    renderBifurcation(activeResult);
  }
  if (activeTab === "linear2d" && linear2dResult) {
    renderLinear2d(linear2dResult);
  }
});

els.oneDTabButton.addEventListener("click", () => setActiveTab("oneD"));
els.linear2dTabButton.addEventListener("click", () => setActiveTab("linear2d"));

els.linearCalculateButton.addEventListener("click", () => {
  calculateLinear2d().catch((error) => setLinearError(error.message));
});

[els.linearAInput, els.linearBInput, els.linearCInput, els.linearDInput].forEach((input) => {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      calculateLinear2d().catch((error) => setLinearError(error.message));
    }
  });
});

init().catch((error) => setError(error.message));
