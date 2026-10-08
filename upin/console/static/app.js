// UPIN Console. Shows what the UPIN server reports, nothing else.
// Rule: no number is made up here. A value the server does not send is
// shown as missing, never filled in. (tests/test_console.py checks this
// file contains no random-number calls.)
"use strict";

const $ = (id) => document.getElementById(id);
const MPD = 111320; // metres per degree of latitude

let CONFIG = { tiles: null, tiles_attribution: "" };
let STATE = null;
let lastOk = 0;

// ---------- formatting: missing stays missing ----------
function na(el, text) { el.textContent = text; el.classList.add("na"); }
function put(el, text) { el.textContent = text; el.classList.remove("na"); }
function num(v, d) { return (v === null || v === undefined) ? null : Number(v).toFixed(d); }
function setVal(id, v, missing) {
  const el = $(id);
  if (v === null || v === undefined) na(el, missing || "not available");
  else put(el, v);
}
function pos(lat, lon) {
  if (lat === null || lat === undefined) return null;
  return lat.toFixed(6) + ", " + lon.toFixed(6);
}
function age(s) { return s === null || s === undefined ? "" : " (" + s.toFixed(1) + " s old)"; }
const FIX = { 0: "no fix", 1: "no fix", 2: "2-D", 3: "3-D", 4: "GNSS + dead reckoning", 5: "time only", 6: "DGPS", 7: "RTK float", 8: "RTK fixed" };

// ---------- map: our own Web Mercator renderer ----------
const canvas = $("map");
const ctx = canvas.getContext("2d");
const view = { lat: null, lon: null, zoom: 17, follow: true };
const tiles = new Map();

function worldPx(lat, lon, z) {
  const s = 256 * Math.pow(2, z);
  const x = (lon + 180) / 360 * s;
  const r = lat * Math.PI / 180;
  const y = (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * s;
  return [x, y];
}
function fromWorld(x, y, z) {
  const s = 256 * Math.pow(2, z);
  const lon = x / s * 360 - 180;
  const n = Math.PI - 2 * Math.PI * y / s;
  return [180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n))), lon];
}
function toScreen(lat, lon) {
  const [cx, cy] = worldPx(view.lat, view.lon, view.zoom);
  const [x, y] = worldPx(lat, lon, view.zoom);
  return [x - cx + canvas.clientWidth / 2, y - cy + canvas.clientHeight / 2];
}
function pxPerMetre() {
  return Math.pow(2, view.zoom) * 256 / (40075016.686 * Math.cos(view.lat * Math.PI / 180));
}

function resize() {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}
window.addEventListener("resize", resize);

function niceStep(m) {
  const p = Math.pow(10, Math.floor(Math.log10(m)));
  for (const k of [1, 2, 5, 10]) if (k * p >= m) return k * p;
  return 10 * p;
}

function drawTiles(w, h) {
  if (!CONFIG.tiles) return false;
  const tz = Math.max(0, Math.min(19, Math.round(view.zoom)));
  const scale = Math.pow(2, view.zoom - tz);
  const [cx, cy] = worldPx(view.lat, view.lon, tz);
  const size = 256 * scale;
  const x0 = Math.floor((cx - w / 2 / scale) / 256), x1 = Math.floor((cx + w / 2 / scale) / 256);
  const y0 = Math.floor((cy - h / 2 / scale) / 256), y1 = Math.floor((cy + h / 2 / scale) / 256);
  for (let tx = x0; tx <= x1; tx++) for (let ty = y0; ty <= y1; ty++) {
    const url = CONFIG.tiles.replace("{z}", tz).replace("{x}", tx).replace("{y}", ty);
    let img = tiles.get(url);
    if (!img) { img = new Image(); img.onload = draw; img.src = url; tiles.set(url, img); }
    if (img.complete && img.naturalWidth) {
      ctx.drawImage(img, (tx * 256 - cx) * scale + w / 2, (ty * 256 - cy) * scale + h / 2, size, size);
    }
  }
  return true;
}

function drawGrid(w, h) {
  const ppm = pxPerMetre();
  const step = niceStep(110 / ppm);
  const [lat0, lon0] = [view.lat, view.lon];
  const originN = Math.floor(lat0 * MPD / step) * step;
  ctx.strokeStyle = "rgba(90,169,255,0.10)";
  ctx.lineWidth = 1;
  const mPerDegLon = MPD * Math.cos(lat0 * Math.PI / 180);
  const originE = Math.floor(lon0 * mPerDegLon / step) * step;
  const nLines = Math.ceil(Math.max(w, h) / (step * ppm)) + 2;
  for (let k = -nLines; k <= nLines; k++) {
    const [, yy] = toScreen((originN + k * step) / MPD, lon0);
    ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(w, yy); ctx.stroke();
    const [xx] = toScreen(lat0, (originE + k * step) / mPerDegLon);
    ctx.beginPath(); ctx.moveTo(xx, 0); ctx.lineTo(xx, h); ctx.stroke();
  }
  return step;
}

function circle(lat, lon, radiusM, stroke, fill, dash) {
  const [x, y] = toScreen(lat, lon);
  const r = radiusM * pxPerMetre();
  ctx.beginPath(); ctx.arc(x, y, Math.max(r, 0.5), 0, 2 * Math.PI);
  ctx.setLineDash(dash || []);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1.5; ctx.stroke(); }
  ctx.setLineDash([]);
}
function dot(lat, lon, r, color) {
  const [x, y] = toScreen(lat, lon);
  ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fillStyle = color; ctx.fill();
}
function label(lat, lon, text, color) {
  const [x, y] = toScreen(lat, lon);
  ctx.font = "11px -apple-system, sans-serif"; ctx.fillStyle = color;
  ctx.fillText(text, x + 9, y - 7);
}

const MODE_COLOR = { TRUSTED: "#3ddc84", DEGRADED: "#ffb020", NO_FIX: "#ff5468" };

function draw() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  ctx.fillStyle = "#0a101c"; ctx.fillRect(0, 0, w, h);
  if (view.lat === null) return;
  const usedTiles = drawTiles(w, h);
  const step = usedTiles ? null : drawGrid(w, h);
  const s = STATE;
  if (s) {
    const css = getComputedStyle(document.documentElement);
    // reachable region
    if (s.region) {
      const r = s.region;
      circle(r.speed_centre[0], r.speed_centre[1], r.speed_radius_m, "rgba(255,176,32,0.35)", null, [3, 6]);
      circle(r.manoeuvre_centre[0], r.manoeuvre_centre[1], r.manoeuvre_radius_m, "rgba(255,176,32,0.9)", "rgba(255,176,32,0.05)", [8, 6]);
    }
    // truth (simulation only)
    if (s.truth_trail && s.truth_trail.length) {
      ctx.strokeStyle = "rgba(255,255,255,0.25)"; ctx.lineWidth = 1; ctx.beginPath();
      s.truth_trail.forEach((p, i) => { const [x, y] = toScreen(p[0], p[1]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    }
    // input fixes
    (s.input_trail || []).forEach((p) => dot(p[0], p[1], 1.6, "rgba(90,169,255,0.45)"));
    // UPIN trail, coloured by mode
    const tr = s.trail || [];
    for (let i = 1; i < tr.length; i++) {
      const [x0, y0] = toScreen(tr[i - 1][0], tr[i - 1][1]);
      const [x1, y1] = toScreen(tr[i][0], tr[i][1]);
      ctx.strokeStyle = MODE_COLOR[tr[i][2]] || "#888"; ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    }
    // current input and second receivers
    if (s.input && s.input.lat !== null) {
      dot(s.input.lat, s.input.lon, 4.5, css.getPropertyValue("--info"));
      if (s.input.h_acc_m) circle(s.input.lat, s.input.lon, s.input.h_acc_m * 2.4477, "rgba(90,169,255,0.6)", null, [2, 3]);
      (s.input.second_fixes || []).forEach((f) => {
        const [x, y] = toScreen(f.lat, f.lon);
        ctx.save(); ctx.translate(x, y); ctx.rotate(Math.PI / 4);
        ctx.fillStyle = css.getPropertyValue("--second"); ctx.fillRect(-4, -4, 8, 8); ctx.restore();
      });
    }
    // truth marker
    if (s.truth) {
      const [x, y] = toScreen(s.truth.lat, s.truth.lon);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath();
      ctx.moveTo(x - 6, y - 6); ctx.lineTo(x + 6, y + 6); ctx.moveTo(x + 6, y - 6); ctx.lineTo(x - 6, y + 6); ctx.stroke();
    }
    // UPIN output
    if (s.output) {
      const c = MODE_COLOR[s.mode] || "#888";
      if (s.output.r95_m) circle(s.output.lat, s.output.lon, s.output.r95_m, c, c + "22");
      dot(s.output.lat, s.output.lon, 6, c);
      label(s.output.lat, s.output.lon, "UPIN", c);
    }
  }
  // scale bar
  const ppm = pxPerMetre();
  const bar = niceStep(100 / ppm);
  ctx.fillStyle = "#e6ecf7"; ctx.fillRect(14, h - 22, bar * ppm, 3);
  ctx.font = "11px -apple-system, sans-serif";
  ctx.fillText(bar >= 1000 ? (bar / 1000) + " km" : bar + " m", 14, h - 28);
  if (step) ctx.fillText("grid " + (step >= 1000 ? step / 1000 + " km" : step + " m"), 14 + bar * ppm + 10, h - 18);
  // north arrow
  ctx.fillText("N ↑", w - 34, h - 18);
}

// interaction
let drag = null;
canvas.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener("pointermove", (e) => {
  if (!drag || view.lat === null) return;
  const [cx, cy] = worldPx(view.lat, view.lon, view.zoom);
  [view.lat, view.lon] = fromWorld(cx - (e.clientX - drag.x), cy - (e.clientY - drag.y), view.zoom);
  drag = { x: e.clientX, y: e.clientY };
  setFollow(false); draw();
});
canvas.addEventListener("pointerup", () => { drag = null; });
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  view.zoom = Math.max(3, Math.min(21, view.zoom - e.deltaY * 0.002)); draw();
}, { passive: false });
$("z-in").onclick = () => { view.zoom = Math.min(21, view.zoom + 1); draw(); };
$("z-out").onclick = () => { view.zoom = Math.max(3, view.zoom - 1); draw(); };
function setFollow(on) { view.follow = on; $("follow").classList.toggle("on", on); }
$("follow").onclick = () => { setFollow(!view.follow); if (view.follow) centre(); draw(); };
function centre() {
  const s = STATE; if (!s) return;
  const p = s.output || (s.input && s.input.lat !== null ? s.input : null) || s.truth;
  if (p) { view.lat = p.lat; view.lon = p.lon; }
}

// ---------- panels ----------
function badge(id, text, cls) { const b = $(id); b.textContent = text; b.className = "badge " + (cls || ""); }

function render(s) {
  const src = s.source;
  badge("b-source", src.label, src.simulated ? "sim" : "info");
  $("sim-banner").classList.toggle("hidden", !src.simulated);
  document.querySelectorAll(".sim-only").forEach((el) => el.classList.toggle("hidden", !src.simulated));
  $("source-note").textContent = src.note;
  $("browser-card").classList.toggle("hidden", src.kind !== "browser");
  renderControls(src);

  if (s.waiting) { $("map-status").textContent = "Waiting for the first epoch…"; return; }

  const mcls = { TRUSTED: "good", DEGRADED: "warn", NO_FIX: "bad" }[s.mode];
  badge("b-mode", s.mode, mcls);
  const m = $("mode"); m.textContent = s.mode; m.className = "mode " + s.mode;
  const inp = s.input;
  if (!inp) badge("b-gnss", "GNSS IN —");
  else if (inp.denied_in_software) badge("b-gnss", "GNSS DENIED (SOFTWARE)", "bad");
  else badge("b-gnss", "GNSS IN " + (FIX[inp.fix_type] || inp.fix_type), inp.fix_type >= 3 ? "good" : "bad");
  badge("b-sent", s.sent.sending ? ("TO FC: GPS " + s.sent.gps_instance + (s.sent.fix_type ? " FIX" : " NO FIX")) : "TO FC: NOT SENDING",
        s.sent.sending ? (s.sent.fix_type ? "good" : "warn") : "");

  const o = s.output;
  setVal("o-pos", o ? pos(o.lat, o.lon) : null, "no position (NO_FIX)");
  setVal("o-acc", o && o.h_acc_m !== null ? num(o.h_acc_m, 1) + " m" : null, "—");
  setVal("o-r95", o && o.r95_m !== null ? num(o.r95_m, 1) + " m" : null, "—");
  setVal("o-vel", o && o.vel_ned_ms ? num(o.vel_ned_ms[0], 1) + " / " + num(o.vel_ned_ms[1], 1) + " m/s" : null, "—");
  setVal("o-sent", s.sent.sending
    ? ("GPS " + s.sent.gps_instance + ", " + (s.sent.fix_type ? "3-D fix, accuracy " + num(s.sent.horiz_accuracy, 1) + " m" : "no fix (failsafe decides)"))
    : null, "nothing (listen only)");
  if (s.truth) {
    setVal("o-err", s.truth.error_m !== null ? num(s.truth.error_m, 1) + " m" : null, "no output to compare");
    setVal("o-maxerr", s.truth.max_error_m !== null ? num(s.truth.max_error_m, 1) + " m" : null, "—");
  }

  const ul = $("reasons"); ul.innerHTML = "";
  (s.reasons || []).forEach((r) => { const li = document.createElement("li"); li.textContent = r; ul.appendChild(li); });
  $("caveat").textContent = s.caveat || "";

  const ch = $("checks"); ch.innerHTML = "";
  (s.checks || []).forEach((c) => {
    const row = document.createElement("div"); row.className = "check";
    const pill = document.createElement("div"); pill.className = "pill " + c.status.split(" ")[0];
    pill.textContent = c.status;
    const txt = document.createElement("div");
    const n = document.createElement("div"); n.className = "name"; n.textContent = c.check;
    const d = document.createElement("div"); d.className = "detail"; d.textContent = c.detail;
    txt.append(n, d); row.append(pill, txt); ch.appendChild(row);
  });
  if (!(s.checks || []).length) ch.innerHTML = '<div class="muted">Not run this epoch (validating or no fix).</div>';

  setVal("i-fix", inp ? (FIX[inp.fix_type] || String(inp.fix_type)) + (inp.denied_in_software ? " — denied in software" : "") : null, "no input");
  setVal("i-pos", inp ? pos(inp.lat, inp.lon) : null, "no fix");
  setVal("i-acc", inp && inp.h_acc_m !== null ? num(inp.h_acc_m, 1) + " m (1σ)" : null, "not stated");
  setVal("i-sv", inp && inp.num_sv ? String(inp.num_sv) : null, "not reported");
  setVal("i-jam", inp && inp.jamming_state !== "unknown" ? inp.jamming_state : null, "not reported by this receiver");
  setVal("i-second", inp && inp.second_fixes.length ? inp.second_fixes.map((f) => f.name).join(", ") : null, "none — cross-check not run");

  const sn = s.sensors || {};
  setVal("s-hdg", sn.heading ? num(sn.heading.deg, 1) + "°" + age(sn.heading.age_s) : null, "not connected");
  setVal("s-baro", sn.baro ? num(sn.baro.pressure_alt_m, 1) + " m (" + num(sn.baro.press_hpa, 2) + " hPa)" : null, "not connected");
  setVal("s-flow", sn.flow ? num(sn.flow.forward_ms, 2) + " / " + num(sn.flow.right_ms, 2) + " m/s, q " + sn.flow.quality : null, "not connected");
  setVal("s-range", sn.range ? num(sn.range.m, 2) + " m" + age(sn.range.age_s) : null, "not connected");
  setVal("s-gps", sn.fc_gps ? (FIX[sn.fc_gps.fix_type] || sn.fc_gps.fix_type) + (sn.fc_gps.h_acc_m !== null ? ", ±" + num(sn.fc_gps.h_acc_m, 1) + " m" : ", accuracy not stated") : null, "not connected");
  const circ = sn.ignored_circular || {};
  setVal("s-circ", Object.keys(circ).length ? Object.entries(circ).map(([k, v]) => k + " ×" + v).join(", ") : null, "none received");

  setVal("p-epochs", String(s.epochs));
  setVal("p-rate", s.rate_hz !== null ? num(s.rate_hz, 2) + " Hz" : null, "needs 2 epochs");
  setVal("p-ms", s.processing_ms !== null ? num(s.processing_ms, 2) + " ms" : null, "—");

  renderEvents(s.events || []);
  $("map-status").textContent = s.region
    ? "Reachable region: " + num(s.region.seconds_since_anchor, 0) + " s since last trusted fix, radius " + num(s.region.manoeuvre_radius_m, 0) + " m"
    : "No trusted fix yet: no reachable region to draw";
}

function renderEvents(evs) {
  const box = $("events");
  if (!evs.length) { box.innerHTML = '<div class="muted">None yet.</div>'; return; }
  box.innerHTML = "";
  evs.slice(0, 60).forEach((e) => {
    const d = document.createElement("div"); d.className = "ev " + e.level;
    const t = document.createElement("time"); t.textContent = new Date(e.t * 1000).toLocaleTimeString();
    d.append(t, document.createTextNode(e.text)); box.appendChild(d);
  });
}

const CONTROL_LABEL = {
  spoof_jump: "Spoof: 500 m jump", spoof_drag: "Spoof: slow drag 1 m/s",
  deny: "Deny GNSS", flow: "Optical flow on/off", reset: "Reset",
};
let controlsKey = "";
const active = {};
function renderControls(src) {
  const list = src.controls || [];
  $("controls-card").classList.toggle("hidden", !list.length);
  const key = list.join(",");
  if (key === controlsKey) return;
  controlsKey = key;
  const box = $("controls"); box.innerHTML = "";
  list.forEach((a) => {
    const b = document.createElement("button"); b.textContent = CONTROL_LABEL[a] || a;
    if (a === "flow") active.flow = true;
    b.onclick = async () => {
      const r = await fetch("api/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: a }) });
      const j = await r.json();
      $("control-result").textContent = j.result || j.error || "";
      if (a === "reset") { Object.keys(active).forEach((k) => { active[k] = k === "flow"; }); box.querySelectorAll("button").forEach((x) => x.classList.remove("active")); }
      else if (a !== "flow") { active[a] = !active[a]; b.classList.toggle("active", active[a]); }
      else { active.flow = !active.flow; b.classList.toggle("active", !active.flow); }
    };
    box.appendChild(b);
  });
}

// ---------- this device's location (browser source) ----------
let watchId = null;
$("geo-start").onclick = () => {
  if (!("geolocation" in navigator)) { $("geo-status").textContent = "This browser has no location service."; return; }
  if (watchId !== null) return;
  $("geo-status").textContent = "Asking for permission…";
  watchId = navigator.geolocation.watchPosition(async (p) => {
    const c = p.coords;
    const body = { lat: c.latitude, lon: c.longitude, accuracy: c.accuracy, altitude: c.altitude,
                   speed: c.speed, heading: c.heading, timestamp: p.timestamp };
    try {
      const r = await fetch("api/browser_fix", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json();
      $("geo-status").textContent = "Sent fix: ±" + c.accuracy.toFixed(0) + " m (95%) → " + (j.result || j.error);
    } catch (err) { $("geo-status").textContent = "Could not reach UPIN: " + err; }
  }, (err) => {
    // No fallback: if the location is refused or unavailable, nothing is sent.
    $("geo-status").textContent = "No location: " + err.message + ". Nothing is sent. (Browsers share location only on localhost or https.)";
    watchId = null;
  }, { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
};

// ---------- polling ----------
async function poll() {
  try {
    const r = await fetch("api/state", { cache: "no-store" });
    STATE = await r.json();
    lastOk = Date.now();
    badge("b-link", "CONNECTED", "good");
    render(STATE);
    if (view.lat === null || view.follow) centre();
    draw();
  } catch (e) {
    badge("b-link", "UPIN NOT REACHABLE", "bad");
  }
  setTimeout(poll, 500);
}

(async function init() {
  try { CONFIG = await (await fetch("api/config")).json(); } catch (e) { /* defaults */ }
  if (CONFIG.tiles) $("attrib").textContent = CONFIG.tiles_attribution || "";
  resize();
  poll();
})();
