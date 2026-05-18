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
};

const colors = {
  stable: "#138a5b",
  unstable: "#c7473f",
  semistable: "#b7791f",
  unknown: "#6b7280",
  axis: "#6f7d80",
  grid: "#dfe7e5",
  curve: "#0f766e",
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
  if (!activeResult) return;
  renderPhase(activeResult);
  renderBifurcation(activeResult);
});

init().catch((error) => setError(error.message));
