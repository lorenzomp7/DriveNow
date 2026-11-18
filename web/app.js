// DriveNow live map. Talks to drivenow/server.py: /api/network once, then /api/stream.
"use strict";

const C = {
  go: "#22c55e", slow: "#f59e0b", stop: "#ef4444", cap: "#818cf8",
  road: "#252d38", lane: "#3a4452", node: "#2b333e", text: "#e6edf3",
  dn: "#38bdf8", nn: "#9aa5b4", bg: "#0d1117",
};
const KIND = ["free", "go", "slow", "stop", "cap"];
const $ = (id) => document.getElementById(id);

let NET = null;
const edges = new Map();
const nodes = new Map();
let frame = null, prevFrame = null, frameAt = 0, frameDur = 200;
let field = {};
let selected = null;
let follow = true;

// ---------------------------------------------------------------- geometry
function prepEdge(e) {
  let acc = 0;
  e.segs = [];
  for (let i = 0; i + 1 < e.shape.length; i++) {
    const [ax, ay] = e.shape[i], [bx, by] = e.shape[i + 1];
    const L = Math.hypot(bx - ax, by - ay);
    e.segs.push([ax, ay, bx, by, acc, L]);
    acc += L;
  }
  e.geo = acc;
}
function pointAt(e, pos) {
  const s = e.len > 0 ? pos * (e.geo / e.len) : 0;
  for (const [ax, ay, bx, by, acc, L] of e.segs) {
    if (s <= acc + L) {
      const f = L ? Math.min(Math.max((s - acc) / L, 0), 1) : 0;
      return [ax + (bx - ax) * f, ay + (by - ay) * f, Math.atan2(by - ay, bx - ax)];
    }
  }
  const last = e.shape[e.shape.length - 1];
  return [last[0], last[1], 0];
}

// ---------------------------------------------------------------- view
const canvas = $("map");
const ctx = canvas.getContext("2d");
const view = { cx: 0, cy: 0, s: 1, W: 0, H: 0 };
function resize() {
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
  view.W = r.width; view.H = r.height;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
const toScreen = (x, y) => [(x - view.cx) * view.s + view.W / 2, view.H / 2 - (y - view.cy) * view.s];
const toWorld = (px, py) => [(px - view.W / 2) / view.s + view.cx, view.cy - (py - view.H / 2) / view.s];
function fit() {
  const [x0, y0, x1, y1] = NET.bounds;
  view.cx = (x0 + x1) / 2; view.cy = (y0 + y1) / 2;
  view.s = Math.min(view.W / (x1 - x0 + 80), view.H / (y1 - y0 + 80));
}

// ---------------------------------------------------------------- interaction
let drag = null;
canvas.addEventListener("pointerdown", (ev) => {
  drag = { x: ev.clientX, y: ev.clientY, cx: view.cx, cy: view.cy, moved: false };
  canvas.setPointerCapture(ev.pointerId);
});
canvas.addEventListener("pointermove", (ev) => {
  if (!drag) return;
  const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
  if (Math.hypot(dx, dy) > 4) {
    drag.moved = true;
    canvas.classList.add("dragging");
    setFollow(false);
  }
  view.cx = drag.cx - dx / view.s; view.cy = drag.cy + dy / view.s;
});
canvas.addEventListener("pointerup", (ev) => {
  canvas.classList.remove("dragging");
  if (drag && !drag.moved) pick(ev);
  drag = null;
});
canvas.addEventListener("wheel", (ev) => {
  ev.preventDefault();
  const r = canvas.getBoundingClientRect();
  const [wx, wy] = toWorld(ev.clientX - r.left, ev.clientY - r.top);
  const k = Math.exp(-ev.deltaY * 0.0015);
  view.s = Math.min(Math.max(view.s * k, 0.15), 12);
  if (!follow) {
    const [nx, ny] = toWorld(ev.clientX - r.left, ev.clientY - r.top);
    view.cx += wx - nx; view.cy += wy - ny;
  }
}, { passive: false });

function pick(ev) {
  if (!frame) return;
  const r = canvas.getBoundingClientRect();
  const px = ev.clientX - r.left, py = ev.clientY - r.top;
  let best = null, bd = 22;
  for (const v of frame.vehicles) {
    const [sx, sy] = toScreen(v[1], v[2]);
    const d = Math.hypot(sx - px, sy - py);
    if (d < bd) { bd = d; best = v[0]; }
  }
  if (best !== null) { selected = best; setFollow(true); updateHud(); }
}
function setFollow(on) {
  follow = on;
  $("btn-follow").setAttribute("aria-pressed", on ? "true" : "false");
}
$("btn-fit").onclick = () => { setFollow(false); fit(); };
$("btn-follow").onclick = () => setFollow(!follow);
$("btn-next").onclick = () => { pickEquipped(true); setFollow(true); };

function pickEquipped(other) {
  if (!frame) return;
  // Prefer a DriveNow car heading for a traffic light, where the advice is most interesting.
  let pool = frame.vehicles.filter((v) => v[5] === 1 && v[0] !== selected && v[7] >= 1 && v[7] <= 3);
  if (!pool.length) pool = frame.vehicles.filter((v) => v[5] === 1 && v[0] !== selected && v[7] >= 1);
  const any = frame.vehicles.filter((v) => v[5] === 1 && (!other || v[0] !== selected));
  const list = pool.length ? pool : any;
  if (list.length) selected = list[Math.floor(Math.random() * list.length)][0];
}

// ---------------------------------------------------------------- settings
function post(settings) {
  fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings) });
}
for (const b of document.querySelectorAll("#speed-seg button")) {
  b.onclick = () => post({ speed: Number(b.dataset.speed) });
}
$("pen").oninput = (e) => { $("pen-val").textContent = e.target.value + "%"; };
$("pen").onchange = (e) => post({ penetration: Number(e.target.value) / 100 });
$("dem").oninput = (e) => { $("dem-val").textContent = e.target.value; };
$("dem").onchange = (e) => post({ demand: Number(e.target.value) });
let settingsSynced = false;

// ---------------------------------------------------------------- drawing
function category(lo, hi, limit, isSignal) {
  if (isSignal) {
    if (lo === null && hi === null) return "stop";
    return hi >= limit - 1 ? "go" : "slow";
  }
  return hi >= limit - 1 ? null : "cap";
}

function strokePath(pts, width, color) {
  ctx.beginPath();
  pts.forEach(([x, y], i) => {
    const [sx, sy] = toScreen(x, y);
    i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy);
  });
  ctx.lineWidth = width; ctx.strokeStyle = color; ctx.stroke();
}

function lanePart(e, s0, s1) {
  const pts = [pointAt(e, s0)];
  for (const [ax, ay, , , acc] of e.segs) {
    const pos = acc * (e.len / e.geo);
    if (pos > s0 && pos < s1) pts.push([ax, ay]);
  }
  pts.push(pointAt(e, s1));
  return pts;
}

function pill(x, y, text, color) {
  ctx.font = "600 11px ui-sans-serif, system-ui, sans-serif";
  const w = ctx.measureText(text).width + 10;
  ctx.fillStyle = "rgba(13,17,23,.88)";
  ctx.strokeStyle = color; ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.roundRect(x - w / 2, y - 9, w, 18, 9);
  ctx.fill(); ctx.stroke();
  ctx.fillStyle = color; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + 0.5);
}

function draw() {
  requestAnimationFrame(draw);
  if (!NET) return;
  const vs = interpolated();
  if (follow && selected !== null) {
    const me = vs.find((v) => v[0] === selected);
    if (me) {
      view.cx += (me[1] - view.cx) * 0.15;
      view.cy += (me[2] - view.cy) * 0.15;
    }
  }
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, view.W, view.H);
  const m = view.s;

  // Asphalt along each lane's own shape, so curved streets stay curved.
  ctx.lineJoin = "round"; ctx.lineCap = "round";
  for (const e of edges.values()) strokePath(e.shape, Math.max(6.5 * m, 3), C.road);
  ctx.lineCap = "butt";
  for (const n of nodes.values()) {
    if (n.kind === "border") continue;
    const [sx, sy] = toScreen(n.x, n.y);
    ctx.fillStyle = C.node;
    ctx.beginPath(); ctx.arc(sx, sy, Math.max(Math.min(n.r + 3, 14) * m, 3), 0, 7); ctx.fill();
    if (n.kind === "roundabout") {
      ctx.fillStyle = "#16301e";
      ctx.beginPath(); ctx.arc(sx, sy, Math.max((n.r - 6) * m, 2), 0, 7); ctx.fill();
    }
  }

  // Lanes, coloured by the speed field.
  const laneW = Math.max(3 * m, 2);
  for (const e of edges.values()) {
    strokePath(e.shape, laneW, C.lane);
    const f = field[e.id];
    if (!f) continue;
    const node = nodes.get(e.to);
    const isSignal = node.kind === "signal";
    for (let i = 0; i < f.length; i++) {
      const [s, lo, hi] = f[i];
      const s1 = i + 1 < f.length ? f[i + 1][0] : e.len;
      const cat = category(lo, hi, e.kmh, isSignal);
      if (!cat) continue;
      strokePath(lanePart(e, s, s1), laneW, C[cat]);
    }
  }

  // Signal heads and countdowns; give-way marks.
  for (const e of edges.values()) {
    const node = nodes.get(e.to);
    const [x, y] = e.shape[e.shape.length - 1];
    const [sx, sy] = toScreen(x, y);
    if (node.kind === "signal" && frame && frame.signals[node.id]) {
      const g = node.groups[e.id];
      const st = frame.signals[node.id][g];
      if (!st) continue;
      const col = st[0] === "G" ? C.go : st[0] === "y" ? "#facc15" : C.stop;
      const sure = st[3] !== false;  // false: a timing learnt from the cars, still only suspected
      ctx.beginPath(); ctx.arc(sx, sy, Math.max(2.6 * m, 3.5), 0, 7);
      if (sure) { ctx.fillStyle = col; ctx.fill(); }
      else { ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.stroke(); }
      if (m > 0.75 && st[1] !== null) {
        ctx.font = "600 10px ui-sans-serif, system-ui, sans-serif";
        ctx.fillStyle = col; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        const [, , h] = pointAt(e, e.len);
        const ox = Math.cos(h + Math.PI / 2) * -9, oy = -Math.sin(h + Math.PI / 2) * -9;
        ctx.fillText((sure ? "" : "~") + Math.ceil(st[1]) + "s", sx + ox, sy + oy);
      }
    } else if ((node.kind === "priority" && !node.major.includes(e.id)) || node.kind === "roundabout") {
      ctx.strokeStyle = "#e6edf3"; ctx.lineWidth = 1.5;
      const r = Math.max(2.4 * m, 3);
      ctx.beginPath(); ctx.moveTo(sx - r, sy - r * 0.6); ctx.lineTo(sx + r, sy - r * 0.6); ctx.lineTo(sx, sy + r); ctx.closePath(); ctx.stroke();
    }
  }

  // Speed labels along the approaches.
  if (m > 0.9) {
    for (const e of edges.values()) {
      const f = field[e.id];
      if (!f) continue;
      const isSignal = nodes.get(e.to).kind === "signal";
      for (const target of [70, 190]) {
        if (target > e.len - 10) continue;
        let best = f[0];
        for (const row of f) if (Math.abs(e.len - row[0] - target) < Math.abs(e.len - best[0] - target)) best = row;
        const [, lo, hi] = best;
        const cat = category(lo, hi, e.kmh, isSignal);
        if (!cat) continue;
        const text = cat === "stop" ? "rosso" : cat === "cap" ? "≤ " + hi : lo + "–" + hi;
        const [x, y, h] = pointAt(e, best[0]);
        const off = 11 / m;
        const [px, py] = toScreen(x + Math.sin(h) * off, y - Math.cos(h) * off);
        pill(px, py, text, C[cat]);
      }
    }
  }

  // Vehicles.
  for (const v of vs) {
    const [id, x, y, h, , eq] = v;
    const [sx, sy] = toScreen(x, y);
    const me = id === selected;
    const L = Math.max(4.5 * m, me ? 13 : 7), W = Math.max(2 * m, me ? 6 : 3.5);
    ctx.save();
    ctx.translate(sx, sy); ctx.rotate(-h);
    if (me) {
      ctx.fillStyle = "rgba(56,189,248,.25)";
      ctx.beginPath(); ctx.arc(0, 0, L, 0, 7); ctx.fill();
    }
    ctx.fillStyle = me ? "#ffffff" : eq ? C.dn : C.nn;
    ctx.beginPath(); ctx.roundRect(-L / 2, -W / 2, L, W, Math.min(2, W / 2)); ctx.fill();
    if (me) {  // nose, to show the direction of travel
      ctx.fillStyle = eq ? C.dn : C.nn;
      ctx.beginPath(); ctx.moveTo(L / 2 + 5, 0); ctx.lineTo(L / 2 + 1, -W / 2); ctx.lineTo(L / 2 + 1, W / 2); ctx.closePath(); ctx.fill();
    }
    ctx.restore();
  }
}

function interpolated() {
  if (!frame) return [];
  if (!prevFrame) return frame.vehicles;
  const f = Math.min((performance.now() - frameAt) / frameDur, 1);
  const prev = new Map(prevFrame.vehicles.map((v) => [v[0], v]));
  return frame.vehicles.map((v) => {
    const p = prev.get(v[0]);
    if (!p || Math.hypot(v[1] - p[1], v[2] - p[2]) > 40) return v;
    const out = v.slice();
    out[1] = p[1] + (v[1] - p[1]) * f;
    out[2] = p[2] + (v[2] - p[2]) * f;
    let dh = v[3] - p[3];
    dh = Math.atan2(Math.sin(dh), Math.cos(dh));
    out[3] = p[3] + dh * f;
    return out;
  });
}

// ---------------------------------------------------------------- HUD
function gaugePoint(v, max) {
  const th = Math.PI * (1 - Math.min(Math.max(v / max, 0), 1));
  return [110 + 90 * Math.cos(th), 115 - 90 * Math.sin(th)];
}
const NEXT_NAME = { signal: "Semaforo", roundabout: "Rotonda", yield: "Precedenza", queue: "Coda" };
const COLOR_NAME = { G: "verde", y: "giallo", r: "rosso" };

let lastAnnounce = { id: null, n: 0 };
function updateHud() {
  if (!frame) return;
  let v = frame.vehicles.find((r) => r[0] === selected);
  if (!v) { pickEquipped(false); v = frame.vehicles.find((r) => r[0] === selected); }
  if (!v) return;
  const [, , , , speed, eq, limit, kc, lo, hi, target, nk, nn, nd, ng, ann] = v;
  // A new announcement for the same car: flash the advice once (a voice or a chime would go here).
  if (ann !== undefined && v[0] === lastAnnounce.id && ann > lastAnnounce.n) {
    const hud = $("hud"); hud.classList.remove("flash"); void hud.offsetWidth; hud.classList.add("flash");
  }
  lastAnnounce = { id: v[0], n: ann };
  const kind = KIND[kc] || "free";
  const tag = $("veh-tag");
  tag.textContent = eq ? "Segue DriveNow" : "Non segue il consiglio";
  tag.className = "tag" + (eq ? " dn" : "");

  $("target").textContent = target ?? "—";
  const labels = { free: "Strada libera", go: "Verde in arrivo", slow: "Rallenta senza frenare", stop: "Rosso inevitabile", cap: "Alza il piede" };
  const giveWay = nk === "yield";
  if (giveWay) labels.stop = "Dai precedenza";
  if (nk === "queue") labels.cap = Number(ng) < 8 ? "Coda ferma più avanti" : "Traffico lento più avanti";
  const k = $("kind"); k.textContent = labels[kind]; k.className = "kind " + kind;

  const node = nn ? nodes.get(nn) : null;
  const where = node ? node.name : "";
  const texts = giveWay ? {
    free: "Strada principale libera: guida normalmente entro il limite.",
    go: `Strada principale libera: puoi tenere fino a ${hi} km/h.`,
    slow: `Sulla strada principale arriva un'auto: scendi a circa ${target} km/h (tra ${lo} e ${hi}) e arrivi all'incrocio quando è passata, senza fermarti.`,
    stop: "La strada principale è trafficata: lascia scorrere l'auto fino alla linea e dai la precedenza.",
    cap: `Precedenza tra ${nd} m, strada principale libera: non superare ${hi} km/h e rallenterai solo rilasciando l'acceleratore.`,
  } : {
    free: "Niente semafori o rotonde a breve: guida normalmente entro il limite.",
    go: `Il verde ti aspetta: puoi tenere fino a ${hi} km/h e passi senza fermarti.`,
    slow: `Lascia l'acceleratore e scendi a circa ${target} km/h. Tra ${lo} e ${hi} km/h arrivi al semaforo quando scatta il verde, senza frenare.`,
    stop: "Nessuna velocità ragionevole prende il verde: lascia scorrere l'auto e arriverai piano alla linea, senza frenate brusche.",
    cap: `${NEXT_NAME[nk] || "Incrocio"} tra ${nd} m: non superare ${hi} km/h e rallenterai solo rilasciando l'acceleratore.`,
  };
  const sig = nk === "signal" && frame.signals[nn] ? frame.signals[nn][ng] : null;
  const unsure = sig && sig[3] === false;
  if (unsure && (kind === "free" || kind === "cap"))
    texts[kind] = kind === "free"
      ? "L'orario di questo semaforo è ancora incerto: guida normalmente entro il limite."
      : `L'orario del semaforo è ancora incerto. Più avanti c'è una coda o un incrocio: non superare ${hi} km/h e rallenterai solo rilasciando l'acceleratore.`;
  if (nk === "queue" && kind === "cap")
    texts.cap = Number(ng) < 8
      ? `Coda ferma tra ${nd} m: alza il piede, non superare ${hi} km/h e arriverai in fondo alla coda senza frenare.`
      : `Traffico a circa ${ng} km/h tra ${nd} m: alza il piede, non superare ${hi} km/h e lo raggiungerai alla sua velocità senza frenare.`;
  $("advice").textContent = texts[kind];
  $("band").textContent = lo !== null && hi !== null ? `${lo}–${hi} km/h` : hi !== null ? `fino a ${hi} km/h` : "nessuna";
  $("speed").textContent = `${speed} km/h · limite ${limit}`;
  $("next").textContent = nk ? `${NEXT_NAME[nk]} · ${nd} m` : "—";
  $("next").title = where;

  let light = "—";
  if (nk === "signal" && frame.signals[nn] && frame.signals[nn][ng]) {
    const [st, dt, nx] = frame.signals[nn][ng];
    light = dt === null ? COLOR_NAME[st] : `${COLOR_NAME[st]}, ${COLOR_NAME[nx]} tra ${Math.ceil(dt)} s`;
    if (unsure) light += " (stima incerta)";
  }
  $("light").textContent = light;

  // Gauge
  const max = Math.max(limit + 20, 70);
  const band = $("g-band");
  let a = null, b = null, cls = "g-band";
  if (kind === "slow" || kind === "go") { a = lo ?? 0; b = hi; cls += kind === "slow" ? " slow" : ""; }
  else if (kind === "cap") { a = 0; b = hi; cls += " cap"; }
  else if (kind === "free") { a = 0; b = limit; }
  if (a !== null && b !== null && b > a) {
    const [x0, y0] = gaugePoint(a, max), [x1, y1] = gaugePoint(b, max);
    band.setAttribute("d", `M${x0} ${y0} A90 90 0 0 1 ${x1} ${y1}`);
  } else band.setAttribute("d", "");
  band.setAttribute("class", cls);
  const [nx2, ny2] = gaugePoint(speed, max);
  const needle = $("g-needle");
  needle.setAttribute("x2", 110 + (nx2 - 110) * 0.85); needle.setAttribute("y2", 115 + (ny2 - 115) * 0.85);
  const [lx, ly] = gaugePoint(limit, max);
  const lim = $("g-limit");
  lim.setAttribute("x1", 110 + (lx - 110) * 0.82); lim.setAttribute("y1", 115 + (ly - 115) * 0.82);
  lim.setAttribute("x2", 110 + (lx - 110) * 1.1); lim.setAttribute("y2", 115 + (ly - 115) * 1.1);
}

function updateStats() {
  const d = frame.stats.drivenow, n = frame.stats.normal;
  const rows = [
    ["stops", "stops", (x) => x.toFixed(2), true],
    ["brakes", "brake_events", (x) => x.toFixed(2), true],
    ["energy", "brake_energy_kj", (x) => x.toFixed(0) + " kJ", true],
    ["time", "travel_time", (x) => x.toFixed(0) + " s", true],
    ["trips", "trips", (x) => String(x), false],
  ];
  for (const [id, key, fmt, lowerBetter] of rows) {
    const cd = $("s-" + id + "-d"), cn = $("s-" + id + "-n");
    cd.textContent = d.trips ? fmt(d[key]) : "—";
    cn.textContent = n.trips ? fmt(n[key]) : "—";
    const both = d.trips && n.trips && lowerBetter;
    cd.className = both && d[key] < n[key] ? "better" : "";
    cn.className = both && n[key] < d[key] ? "better" : "";
  }
}

function updateMeta() {
  if (frame.clock) {
    // Real recording: show Hamburg's local time of that moment.
    $("clock").textContent = new Date(frame.clock * 1000).toLocaleString("it-IT", {
      timeZone: "Europe/Berlin", weekday: "short", day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } else {
    const t = Math.floor(frame.t);
    $("clock").textContent = `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
  }
  for (const b of document.querySelectorAll("#speed-seg button")) b.classList.toggle("on", Number(b.dataset.speed) === frame.speed);
  if (!settingsSynced) {
    settingsSynced = true;
    const pen = Math.round(frame.penetration * 100);
    $("pen").value = pen; $("pen-val").textContent = pen + "%";
    if (frame.demand === null) $("demand-row").style.display = "none";
    else { $("dem").value = frame.demand; $("dem-val").textContent = Math.round(frame.demand); }
  }
}

// ---------------------------------------------------------------- data
function loadNetwork(net) {
  NET = net;
  for (const n of NET.nodes) nodes.set(n.id, n);
  for (const e of NET.edges) { prepEdge(e); edges.set(e.id, e); }
  $("net-name").textContent = NET.name;
  fit();
  requestAnimationFrame(draw);
}

function showFrame(f) {
  prevFrame = frame;
  frame = f;
  frameAt = performance.now();
  if (selected === null) {
    pickEquipped(false);
    if (selected !== null) view.s = Math.max(view.s, 1.4);
  }
  updateHud(); updateStats(); updateMeta();
}

// Live: frames from the Python server.
async function startLive() {
  loadNetwork(await (await fetch("/api/network")).json());
  const es = new EventSource("/api/stream");
  es.onopen = () => $("live").classList.add("on");
  es.onerror = () => $("live").classList.remove("on");
  es.addEventListener("frame", (ev) => showFrame(JSON.parse(ev.data)));
  es.addEventListener("field", (ev) => { field = JSON.parse(ev.data).field; });
}

// Replay: a recording made by tools/record_replay.py, played back in a loop.
async function startReplay(url) {
  const data = await (await fetch(url)).json();
  loadNetwork(data.network);
  const fields = new Map(data.fields);
  const stepMs = data.dt * 1000;
  let i = 0, speed = 1, acc = 0, last = performance.now();
  const live = $("live");
  live.textContent = "REPLAY"; live.classList.add("on");
  live.title = "Registrazione della simulazione, riprodotta in ciclo";
  $("replay-note").hidden = false;
  $("replay-note").textContent = data.note;
  for (const id of ["pen-row", "demand-row"]) $(id).hidden = true;
  for (const b of document.querySelectorAll("#speed-seg button")) {
    b.onclick = () => { speed = Number(b.dataset.speed); };
  }
  const tick = (now) => {
    acc += (now - last) * speed;
    last = now;
    let next = null;
    while (acc >= stepMs) {
      acc -= stepMs;
      i = (i + 1) % data.frames.length;
      if (i === 0) { prevFrame = null; frame = null; }
      next = data.frames[i];
      if (fields.has(i)) field = fields.get(i);
    }
    if (next) {
      frameDur = stepMs / speed;
      next.speed = speed;
      showFrame(next);
    }
    requestAnimationFrame(tick);
  };
  field = fields.get(0) || {};
  data.frames[0].speed = speed;
  showFrame(data.frames[0]);
  requestAnimationFrame(tick);
}

function start() {
  resize();
  window.addEventListener("resize", resize);
  const host = document.querySelector("[data-replay]");
  return host ? startReplay(host.dataset.replay) : startLive();
}
start();
