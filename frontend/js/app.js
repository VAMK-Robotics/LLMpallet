import { api, debounce, renderLog } from "./api.js";
import { Preview3D, ROTATION_COLORS } from "./preview3d.js";
import { initSettings } from "./settings.js";

const $ = id => document.getElementById(id);

const NUMBER_FIELDS = ["box_length", "box_width", "box_height", "total_boxes", "layer_count", "gap",
  "border_x", "border_y", "interlayer_thickness", "max_overhang_pct"];
const INT_FIELDS = new Set(["total_boxes", "layer_count"]);
const SELECT_FIELDS = ["partial_layer_mode", "primary_axis"];

const PATTERN_HINTS = {
  column: "All boxes have the same orientation in a straight grid.",
  interlocked: "Block pattern. Every second layer (2nd, 4th, …) is turned 90° relative to the chosen rotation, so the layers interlock.",
  pinwheel: "Four blocks around the centre. Blocks 2–4 are turned +90°, +180° and +270° from block 1, so each block faces a different side of the pallet.",
  optimized: "Tetris: the software searches the layout with the most boxes. Choose which rotation the lengthwise and crosswise boxes use.",
};
const PATTERN_NAMES = { column: "Column", interlocked: "Interlocked", pinwheel: "Pinwheel", optimized: "Tetris" };

const state = { params: null, layout: null, active: 0, requestId: 0 };

const preview = new Preview3D($("canvas-wrap"), {
  tooltip: $("tooltip"),
  onSelectLayer: layer => selectLayer(layer),
});

// ------------------------------------------------------------------ parameters
function defaultLayer() { return { pattern: "column", rotation: 0, rot_long: 0, rot_cross: 90 }; }

function syncLayerArray() {
  const n = state.params.layer_count;
  const layers = state.params.layers;
  while (layers.length < n) layers.push({ ...(layers[layers.length - 1] || defaultLayer()) });
  layers.length = n;
  if (state.active >= n) state.active = n - 1;
}

function fillForm() {
  const p = state.params;
  for (const f of NUMBER_FIELDS) $(f).value = p[f];
  for (const f of SELECT_FIELDS) $(f).value = p[f];
  $("interlayer_bottom").checked = p.interlayer_bottom;
  $("filename").value = p.filename;
}

function readForm() {
  let valid = true;
  for (const f of NUMBER_FIELDS) {
    const el = $(f);
    const v = INT_FIELDS.has(f) ? parseInt(el.value, 10) : parseFloat(el.value);
    const min = parseFloat(el.min), max = parseFloat(el.max);
    const ok = Number.isFinite(v) && (!Number.isFinite(min) || v >= min) && (!Number.isFinite(max) || v <= max) &&
      (!INT_FIELDS.has(f) || String(v) === el.value.trim());
    el.classList.toggle("invalid", !ok);
    if (ok) state.params[f] = v; else valid = false;
  }
  for (const f of SELECT_FIELDS) state.params[f] = $(f).value;
  state.params.interlayer_bottom = $("interlayer_bottom").checked;
  state.params.filename = $("filename").value.trim() || "pallet.csv";
  return valid;
}

function renderLayerPanel() {
  const sel = $("active_layer");
  const n = state.params.layer_count;
  if (sel.options.length !== n) {
    sel.innerHTML = "";
    for (let i = 0; i < n; i++) sel.add(new Option(`Layer ${i + 1}`, i));
  }
  sel.value = state.active;
  const cfg = state.params.layers[state.active];
  $("layer_pattern").value = cfg.pattern;
  $("layer_rotation").value = cfg.rotation;
  $("layer_rot_long").value = cfg.rot_long;
  $("layer_rot_cross").value = cfg.rot_cross;
  const optimized = cfg.pattern === "optimized";
  $("row-rotation").hidden = optimized;
  $("row-rot-long").hidden = !optimized;
  $("row-rot-cross").hidden = !optimized;
  $("rotation-label").textContent = cfg.pattern === "pinwheel" ? "Rotation of block 1" :
    cfg.pattern === "interlocked" ? "Rotation (odd layers)" : "Rotation";
  let hint = PATTERN_HINTS[cfg.pattern];
  if (cfg.pattern === "interlocked") {
    const eff = state.active % 2 === 1 ? normRot(cfg.rotation + 90) : cfg.rotation;
    hint += ` This layer uses ${eff}°.`;
  }
  $("pattern-hint").textContent = hint;
}

function normRot(r) { const m = ((r % 360) + 360) % 360; return m === 270 ? -90 : m; }

function readLayerPanel() {
  const cfg = state.params.layers[state.active];
  cfg.pattern = $("layer_pattern").value;
  cfg.rotation = parseInt($("layer_rotation").value, 10);
  cfg.rot_long = parseInt($("layer_rot_long").value, 10);
  cfg.rot_cross = parseInt($("layer_rot_cross").value, 10);
}

function selectLayer(i) {
  state.active = Math.max(0, Math.min(i, state.params.layer_count - 1));
  renderLayerPanel();
  preview.setActiveLayer(state.active);
  renderResults();
}

// ------------------------------------------------------------------ compute & render
const saveJob = debounce(() => api.saveJob(state.params).catch(() => { }), 800);

async function recompute() {
  const id = ++state.requestId;
  try {
    const layout = await api.layout(state.params);
    if (id !== state.requestId) return; // a newer request is on its way
    const firstRender = !state.layout;
    state.layout = layout;
    preview.setLayout(layout, state.params);
    if (firstRender) preview.setView("iso");
    renderResults();
    if (!firstRender) clearGenerateLog();
    saveJob();
  } catch (e) {
    if (id !== state.requestId) return;
    showMessages([{ level: "error", text: e.message }]);
  }
}
const recomputeSoon = debounce(recompute, 120);

// The log under "Generate CSV" belongs to the parameters it was generated with: clear it as soon as
// the layout changes, so an old result is never mistaken for a message about the current settings.
function clearGenerateLog() {
  if (!$("gen-log").children.length) return;
  $("gen-log").innerHTML = "";
  $("download").hidden = true;
}

function onParamsChanged() {
  if (!readForm()) {
    showMessages([{ level: "error", text: "Fix the highlighted fields." }]);
    return;
  }
  syncLayerArray();
  renderLayerPanel();
  recomputeSoon();
}

function showMessages(list) {
  const ul = $("messages");
  ul.innerHTML = "";
  for (const m of list) {
    const li = document.createElement("li");
    li.className = m.level;
    li.textContent = m.text;
    ul.appendChild(li);
  }
}

function renderResults() {
  const L = state.layout;
  if (!L) return;
  const p = state.params;
  $("summary").innerHTML =
    `<b>${L.total_boxes}</b> boxes placed (requested ${p.total_boxes}, capacity ${L.capacity})<br>` +
    `Stack height <b>${L.stack_height.toFixed(1)}</b> mm above pallet deck`;
  showMessages([...L.errors.map(t => ({ level: "error", text: t })), ...L.warnings.map(t => ({ level: "warning", text: t }))]);
  $("generate").disabled = L.errors.length > 0;

  const tb = $("layer-table").tBodies[0];
  tb.innerHTML = "";
  for (const info of L.layers) {
    const tr = tb.insertRow();
    tr.className = info.index === state.active ? "active" : "";
    tr.insertCell().textContent = info.index + 1;
    tr.insertCell().textContent = `${PATTERN_NAMES[info.pattern]} ${info.rotations.map(r => r + "°").join("/")}`;
    tr.insertCell().textContent = `${info.count}/${info.capacity}`;
    tr.insertCell().textContent = info.z_top.toFixed(1);
    tr.addEventListener("click", () => selectLayer(info.index));
  }

  const pb = $("pos-table").tBodies[0];
  pb.innerHTML = "";
  for (const b of L.placements.filter(b => b.layer === state.active)) {
    const tr = pb.insertRow();
    for (const v of [b.index, b.x.toFixed(1), b.y.toFixed(1), b.z.toFixed(1), b.rotation, Math.round(b.support_pct)]) {
      tr.insertCell().textContent = v;
    }
  }
}

// ------------------------------------------------------------------ generate
async function generate() {
  const btn = $("generate");
  const log = $("gen-log");
  btn.disabled = true;
  btn.textContent = "Sending to robot…";
  log.innerHTML = "";
  $("download").hidden = true;
  try {
    const res = await api.generate(state.params, $("filename").value.trim());
    $("filename").value = res.filename;
    state.params.filename = res.filename;
    renderLog(log, res.steps);
    if (res.csv) {
      const a = $("download");
      if (a.href) URL.revokeObjectURL(a.href);
      a.href = URL.createObjectURL(new Blob([res.csv], { type: "text/csv" }));
      a.download = res.filename;
      a.textContent = `Download ${res.filename} (${res.rows} rows)`;
      a.hidden = false;
    }
  } catch (e) {
    renderLog(log, [{ name: "Generate CSV", ok: false, message: e.message }]);
  } finally {
    btn.textContent = "Generate CSV";
    btn.disabled = !!(state.layout && state.layout.errors.length);
  }
}

// ------------------------------------------------------------------ wiring
function addRotationLegend() {
  const div = document.createElement("div");
  div.style.cssText = "position:absolute;right:10px;bottom:8px;font-size:12px;display:flex;gap:8px;pointer-events:none";
  for (const [rot, color] of Object.entries(ROTATION_COLORS)) {
    const s = document.createElement("span");
    s.innerHTML = `<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#${color.toString(16).padStart(6, "0")}"></span> ${rot}°`;
    div.appendChild(s);
  }
  $("viewer").appendChild(div);
}

async function main() {
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === t));
    document.querySelectorAll(".page").forEach(p => p.classList.toggle("active", p.id === `page-${t.dataset.page}`));
    if (t.dataset.page === "palletizer") preview.resize();
  }));

  const [config, pallet] = await Promise.all([api.getConfig(), api.pallet()]);
  state.params = config.job;
  if (!state.params.filename) state.params.filename = config.robot.default_filename;
  syncLayerArray();
  fillForm();
  renderLayerPanel();
  preview.setPallet(pallet);
  initSettings(config.robot);
  addRotationLegend();

  for (const f of [...NUMBER_FIELDS, ...SELECT_FIELDS, "interlayer_bottom", "filename"]) {
    $(f).addEventListener("input", onParamsChanged);
    $(f).addEventListener("change", onParamsChanged);
  }
  for (const f of ["layer_pattern", "layer_rotation", "layer_rot_long", "layer_rot_cross"]) {
    $(f).addEventListener("change", () => { readLayerPanel(); renderLayerPanel(); recomputeSoon(); });
  }
  $("active_layer").addEventListener("change", e => selectLayer(parseInt(e.target.value, 10)));
  $("apply_all").addEventListener("click", () => {
    const cfg = state.params.layers[state.active];
    state.params.layers = state.params.layers.map(() => ({ ...cfg }));
    recomputeSoon();
  });
  document.querySelectorAll("#view-buttons button").forEach(b => b.addEventListener("click", () => preview.setView(b.dataset.view)));
  $("show_numbers").addEventListener("change", e => preview.setOptions({ showNumbers: e.target.checked }));
  $("fade_others").addEventListener("change", e => preview.setOptions({ fadeOthers: e.target.checked }));
  $("generate").addEventListener("click", generate);

  await recompute();
  const view = new URLSearchParams(location.hash.slice(1)).get("view"); // e.g. http://host:8000/#view=top
  if (["iso", "top", "front"].includes(view)) preview.setView(view);
}

main().catch(e => showMessages([{ level: "error", text: `Cannot reach the backend: ${e.message}` }]));
