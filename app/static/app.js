// UI glue for the pocket survival computer.
"use strict";

const $ = (s) => document.querySelector(s);
// Every change on screen is sent over the slow SPI link to the 3.5" LCD: only touch what changed.
function setText(el, s) { if (el.textContent !== s) el.textContent = s; }

if (/[?&]kiosk=1/.test(location.search)) {
  document.body.classList.add("kiosk");
  // Chromium won't make its window narrower than ~500 px, so on the 480 px screen
  // the right edge would fall off: lay the page out at the screen's own width.
  const fit = () => {
    const w = screen.width && screen.width < innerWidth ? screen.width + "px" : "";
    document.documentElement.style.width = w;
  };
  fit(); addEventListener("resize", fit);
}
const api = (url, body) => fetch(url, body === undefined ? {} : {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
}).then(r => r.json());

const S = {
  fix: null, heading: null, target: load("target"), follow: true, page: "map",
  waypoints: [], status: null, cat: "water",
};
function load(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } }
function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } }

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add("hidden"), 2500);
}
function fmtDist(m) {
  if (m == null) return "--";
  return m < 1000 ? Math.round(m) + " m" : (m < 10000 ? (m / 1000).toFixed(2) : (m / 1000).toFixed(1)) + " km";
}
const COMPASS_PTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const cardinal = (b) => COMPASS_PTS[Math.round(b / 45) % 8];
function haversine(a, b) {
  const R = 6371008.8, r = Math.PI / 180;
  const dp = (b.lat - a.lat) * r, dl = (b.lon - a.lon) * r;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
function bearing(a, b) {
  const r = Math.PI / 180, p1 = a.lat * r, p2 = b.lat * r, dl = (b.lon - a.lon) * r;
  const x = Math.sin(dl) * Math.cos(p2), y = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (Math.atan2(x, y) / r + 360) % 360;
}
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
// GPS fix if there is one, else the position set by hand ("I am here" on the map)
// GPS fix, else the dead-reckoning estimate, else the position set by hand
function myPos() {
  const p = S.fix || S.dr || S.manual;
  return p ? { lat: p.lat, lon: p.lon } : null;
}
function arrowFor(b) {
  // arrow relative to where the device points when we know the heading, else relative to north
  const rel = S.heading != null ? (b - S.heading + 360) % 360 : b;
  return `<span class="arrow" style="display:inline-block;transform:rotate(${rel}deg)">&#8593;</span>`;
}

// ---------------------------------------------------------------- tabs
function show(p) {
  S.page = p;
  document.querySelectorAll(".page").forEach(e => e.classList.toggle("active", e.id === "p-" + p));
  document.querySelectorAll("#tabs button[data-p]").forEach(b => b.classList.toggle("active", b.dataset.p === p));
  if (p === "map") map.resize();
  if (p === "go") { loadWaypoints(); drRefresh(); }
  if (p === "find") loadNearest();
  if (p === "radio") { radioRefresh(); swRefresh(); airRefresh(); }
  if (p === "wx") { loadWeather(); loadForecast(); }
  if (p === "info" && !$("#lib-index").innerHTML) loadLibraryIndex();
  if (p === "share") { hotspotRefresh(); meshRefresh(); }
}
document.querySelectorAll("#tabs button[data-p]").forEach(b => b.onclick = () => show(b.dataset.p));
$("#night").onclick = () => { document.body.classList.toggle("night"); save("night", document.body.classList.contains("night")); };
if (load("night")) document.body.classList.add("night");

// ---------------------------------------------------------------- map
const map = new OfflineMap($("#map"));
const view = load("view");
map.onMove = () => { save("view", [map.lat, map.lon, map.zoom]); updateMapInfo(); };
map.onPan = () => { if (S.follow) { S.follow = false; $("#follow").classList.remove("on"); } };
$("#zin").onclick = () => map.setView(map.lat, map.lon, Math.round(map.zoom) + 1);
$("#zout").onclick = () => map.setView(map.lat, map.lon, Math.round(map.zoom) - 1);
$("#follow").onclick = () => {
  S.follow = !S.follow; $("#follow").classList.toggle("on", S.follow);
  const p = myPos();
  if (S.follow && p) map.setView(p.lat, p.lon, Math.max(map.zoom, 15));
  else if (S.follow) toast("No position yet: long-press the map where you are and choose \"I am here\"");
};
$("#follow").classList.toggle("on", S.follow);
$("#layer").onclick = () => {
  if (!S.status || !S.status.raster) return toast("No raster map (data/map.mbtiles) installed");
  map.useRaster = !map.useRaster; map.redraw();
  $("#map-attr").textContent = "© OpenStreetMap" + (map.useRaster && S.status.raster_attribution ? " | " + S.status.raster_attribution : "");
};
function updateMapInfo() {
  $("#map-info").textContent = map.lat.toFixed(5) + ", " + map.lon.toFixed(5) + "  z" + map.zoom.toFixed(1);
}

let menuAt = null;
map.onLongPress = (lat, lon) => {
  const ap = map.airportNear(lat, lon);
  if (ap) { lat = ap.lat; lon = ap.lon; }
  menuAt = { lat, lon, name: ap ? ap.name : null };
  const p = myPos();
  $("#mm-title").textContent = [ap ? "✈ " + ap.name : lat.toFixed(5) + ", " + lon.toFixed(5),
    p ? fmtDist(haversine(p, menuAt)) + " " + cardinal(bearing(p, menuAt)) : ""].filter(Boolean).join("  ·  ");
  $("#mm-info").textContent = ap ? ap.info : "";
  $("#mm-info").classList.toggle("hidden", !ap);
  $("#map-menu").classList.remove("hidden");
  map.overlay.marks = [{ lat, lon, mark: true }]; map.redraw();
};
$("#map-menu").onclick = async (e) => {
  const act = e.target.dataset.act;
  if (!act) return;
  $("#map-menu").classList.add("hidden");
  map.overlay.marks = [];
  if (act === "wp") {
    const name = await askText("Waypoint name", menuAt.name || "");
    if (name === null) { map.redraw(); return; }
    await api("/api/waypoints", { lat: menuAt.lat, lon: menuAt.lon, name });
    toast("Waypoint saved"); loadWaypoints();
  } else if (act === "go") {
    setTarget({ name: menuAt.name || "Map point", lat: menuAt.lat, lon: menuAt.lon }); show("go");
  } else if (act === "near") {
    S.nearAt = menuAt; show("find");
  } else if (act === "here") {
    await api("/api/position", { lat: menuAt.lat, lon: menuAt.lon });
    toast("Your position is set here"); pollGps();
  }
  map.redraw();
};

function setTarget(t) {
  S.target = t; save("target", t);
  map.overlay.target = t; map.redraw(); updateGo();
  if (t) toast("Navigating to " + (t.name || "point"));
}

// ---------------------------------------------------------------- GPS / status polling
async function pollGps() {
  try {
    const g = await api("/api/gps");
    const ok = g.mode >= 2 && g.lat != null && !g.stale;
    S.fix = ok ? g : null;
    S.heading = g.heading;
    S.gpsRaw = g;
    S.manual = g.manual_pos || null;
    S.dr = ok ? null : (g.dr || null);
    const st = $("#st-gps");
    const cls = ok ? "fix" : (S.dr || S.manual ? "" : "nofix");
    if (st.className !== cls) st.className = cls;
    setText(st, ok ? `GPS ${g.mode}D ${g.sats ?? ""}sat`
      : S.dr ? `Estimated ±${fmtDist(S.dr.err_m)}` : (S.manual ? "Position set by hand" : (g.source === "none" ? "No position" : "GPS searching")));
    const p = myPos();
    setText($("#st-pos"), p ? p.lat.toFixed(5) + ", " + p.lon.toFixed(5) : "");
    map.overlay.pos = S.fix || S.dr || (S.manual ? { lat: S.manual.lat, lon: S.manual.lon, manual: true } : null);
    map.overlay.heading = S.heading;
    const fp = myPos();
    if (fp && S.follow && S.page === "map" && (ok || !S.followedEst || Math.abs(fp.lat - S.followedEst.lat) + Math.abs(fp.lon - S.followedEst.lon) > 1e-5)) {
      map.setView(fp.lat, fp.lon, map.zoom < 13 ? 15 : map.zoom);
      S.followedEst = ok ? null : fp;  // estimates: only move the map when the estimate moves
    }
    else if (S.page === "map") {
      // redraw only when the position marker or heading actually moved
      const key = JSON.stringify([map.overlay.pos, map.overlay.heading]);
      if (key !== S.drawnKey) { S.drawnKey = key; map.redraw(); }
    }
    if (S.page === "go") updateGo();
  } catch (e) { /* server restarting */ }
}
setInterval(pollGps, 1000);
setInterval(() => { setText($("#st-clock"), new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })); }, 1000);

// ---------------------------------------------------------------- clock
// The Pi has no clock battery and this build has no GPS, so after a long power-off
// the time can be wrong. Tap the clock to set it; a computer on the hotspot sets it by itself.
const pad2 = (n) => String(n).padStart(2, "0");
$("#st-clock").onclick = async () => {
  const d = new Date();
  const now = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  const v = await askText("Date and time now (YYYY-MM-DD HH:MM, local time)", now);
  if (v === null) return;
  const m = v.trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})$/);
  if (!m) return toast("Use the form 2026-10-31 14:05");
  const t = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  const r = await api("/api/clock", { epoch: t.getTime() / 1000 });
  toast(r.error ? "Could not set the clock: " + r.error : "Clock set");
};
if (!["127.0.0.1", "localhost"].includes(location.hostname)) {
  api("/api/clock", { epoch: Date.now() / 1000 }).catch(() => {});
}
setInterval(async () => { try { map.overlay.track = await api("/api/track"); } catch (e) { /* */ } }, 15000);

async function loadStatus() {
  S.status = await api("/api/status");
  const bat = S.status.battery || {};
  $("#st-bat").textContent = bat.available && bat.percent != null ? "🔋" + bat.percent + "%" : "";
  $("#st-bat").className = bat.percent != null && bat.percent <= 15 ? "low" : "";
  if (bat.shutting_down) toast("Battery empty: shutting down safely. Charge to restart.");
  if (!view && !S.fix) { const v = S.status.start_view; map.setView(v[0], v[1], v[2]); }
  if (!S.status.nav_db || !S.status.nav_db.source) toast("No map database: copy nav.db into data/");
}

// ---------------------------------------------------------------- GO page
function drawCompass(targetBrg) {
  const c = $("#compass"), ctx = c.getContext("2d"), W = c.width, R = W / 2 - 6;
  ctx.clearRect(0, 0, W, W);
  ctx.save(); ctx.translate(W / 2, W / 2);
  const night = document.body.classList.contains("night");
  const fg = night ? "#ff3b2f" : "#e8e6e1";
  const rot = S.heading != null ? -S.heading : 0;  // rotate the card so the top is where you face
  ctx.rotate(rot * Math.PI / 180);
  ctx.beginPath(); ctx.arc(0, 0, R, 0, 7); ctx.strokeStyle = fg; ctx.lineWidth = 2; ctx.stroke();
  for (let a = 0; a < 360; a += 10) {
    ctx.save(); ctx.rotate(a * Math.PI / 180);
    ctx.beginPath(); ctx.moveTo(0, -R); ctx.lineTo(0, -R + (a % 30 ? 6 : 12));
    ctx.strokeStyle = fg; ctx.lineWidth = a % 90 ? 1 : 3; ctx.stroke();
    if (a % 90 === 0) {
      ctx.fillStyle = a === 0 ? "#e53935" : fg; ctx.font = "bold 18px sans-serif"; ctx.textAlign = "center";
      ctx.fillText(["N", "E", "S", "W"][a / 90], 0, -R + 30);
    }
    ctx.restore();
  }
  if (targetBrg != null) {
    ctx.save(); ctx.rotate(targetBrg * Math.PI / 180);
    ctx.beginPath(); ctx.moveTo(0, -R + 36); ctx.lineTo(-16, 10); ctx.lineTo(0, 0); ctx.lineTo(16, 10); ctx.closePath();
    ctx.fillStyle = "#f0a020"; ctx.fill(); ctx.restore();
  }
  ctx.restore();
  // fixed lubber line = direction the device points
  ctx.beginPath(); ctx.moveTo(W / 2, 2); ctx.lineTo(W / 2 - 7, 14); ctx.lineTo(W / 2 + 7, 14); ctx.closePath();
  ctx.fillStyle = S.heading != null ? "#4caf50" : "#8d949b"; ctx.fill();
}

function updateGo() {
  const p = myPos(), t = S.target;
  $("#go-target").textContent = t ? (t.name || "Target") : "No target";
  let brg = null;
  if (p && t) {
    const d = haversine(p, t); brg = bearing(p, t);
    $("#go-dist").textContent = fmtDist(d);
    $("#go-brg").textContent = `Bearing ${Math.round(brg)}° ${cardinal(brg)} · back ${Math.round((brg + 180) % 360)}°`;
    const walkH = d / 4500;
    $("#go-eta").textContent = `Walking ~${walkH < 1 ? Math.round(walkH * 60) + " min" : walkH.toFixed(1) + " h"} (straight line)`;
  } else {
    $("#go-dist").textContent = "--"; $("#go-brg").textContent = t ? "Waiting for GPS position" : "Pick a waypoint, a search result or long-press the map";
    $("#go-eta").textContent = "";
  }
  const g = S.gpsRaw || {};
  $("#go-head").textContent = S.heading != null
    ? `Facing ${Math.round(S.heading)}° ${cardinal(S.heading)} (${g.source === "gps-course" ? "GPS course" : g.compass ? "compass" : "GPS course"})`
    : (g.compass ? "Compass: hold flat" : "No compass: the arrow is relative to north, walk to get a GPS course");
  drawCompass(brg);
  const st = S.status;
  let html = "";
  if (p) {
    html += `<b>${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}</b>`;
    if (st && st.utm) html += ` · UTM ${esc(st.utm)}`;
    html += `<br>Alt ${g.alt != null ? Math.round(g.alt) + " m" : "--"} · Speed ${g.speed != null ? (g.speed * 3.6).toFixed(1) + " km/h" : "--"} · Sats ${g.sats ?? "--"}`;
  } else html += "No GPS position.";
  if (!S.fix && S.dr) html += `<br>Estimated by ${S.dr.mode === "boat" ? "speed and course" : S.dr.steps + " counted steps"}: ` +
    `${fmtDist(S.dr.dist_m)} since the last ${S.dr.from === "gps" ? "GPS fix" : "position you entered"} ` +
    `${Math.round((Date.now() / 1000 - S.dr.since) / 60)} min ago, may be off by ${fmtDist(S.dr.err_m)}.`;
  if (st && st.sun) {
    const f = (s) => s ? new Date(s).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "--";
    html += `<br>Sunrise ${f(st.sun.sunrise)} · Sunset ${f(st.sun.sunset)} · Last light ${f(st.sun.dusk)}`;
  }
  if (st && st.track_km) html += ` · Walked ${st.track_km} km`;
  $("#go-pos").innerHTML = html;
}

async function loadWaypoints() {
  S.waypoints = await api("/api/waypoints");
  map.overlay.waypoints = S.waypoints; map.redraw();
  if (S.page !== "go") return;
  S.status = await api("/api/status");
  $("#wp-list").innerHTML = S.waypoints.length ? S.waypoints.map(w => `
    <div class="item" data-id="${w.id}">
      ${w.bearing != null ? arrowFor(w.bearing) : ""}
      <div class="grow"><div class="name">${esc(w.name)}</div>
      <div class="small">${w.dist_m != null ? fmtDist(w.dist_m) + " " + cardinal(w.bearing) + " · " : ""}${w.lat.toFixed(5)}, ${w.lon.toFixed(5)}</div></div>
      <button data-a="go">Go</button><button data-a="map">Map</button><button data-a="del">&#10005;</button>
    </div>`).join("") : '<div class="small">No waypoints yet. "Mark here" saves your position (camp, water, car).</div>';
  updateGo();
}
$("#wp-list").onclick = async (e) => {
  const a = e.target.dataset.a, it = e.target.closest(".item");
  if (!a || !it) return;
  const w = S.waypoints.find(x => x.id == it.dataset.id);
  if (a === "go") setTarget({ name: w.name, lat: w.lat, lon: w.lon });
  if (a === "map") { S.follow = false; $("#follow").classList.remove("on"); show("map"); map.setView(w.lat, w.lon, 16); }
  if (a === "del" && await askConfirm("Delete " + w.name + "?", "Delete")) { await api("/api/waypoints/delete", { id: w.id }); loadWaypoints(); }
};
$("#wp-here").onclick = async () => {
  const p = myPos();
  if (!p) return toast("No position yet: long-press the map where you are, \"I am here\"");
  const name = await askText("Name this place (camp, water, car...)", "");
  if (name === null) return;
  await api("/api/waypoints", { name, lat: p.lat, lon: p.lon }); toast("Saved"); loadWaypoints();
};
// ---- position without GPS: typed coordinates and dead reckoning
async function drRefresh() {
  const d = await api("/api/dr");
  S.drStatus = d;
  document.querySelectorAll("#dr-mode button").forEach(b => b.classList.toggle("on", b.dataset.m === d.mode));
  $("#dr-boat-row").classList.toggle("hidden", d.mode !== "boat");
  const b = d.boat;
  $("#dr-boat").textContent = b && b.speed_kn != null ? `Boat: ${b.speed_kn} kn, course ${b.course != null ? b.course + "°" : "from compass"} (change)` : "Boat: using last GPS speed and course (set by hand...)";
  $("#dr-info").textContent = (d.imu ? `Step counter: ${d.imu}, ${d.steps} steps, step length ${Math.round(d.step_len * 100)} cm (learns from GPS). `
    : "No step sensor found: on foot the estimate cannot move by itself. ") +
    "When GPS stops, the position is estimated from here on. Enter coordinates (from a chart, a sign, or a GPS that works) to correct it.";
}
$("#dr-enter").onclick = async () => {
  const p = myPos();
  const v = await askText("Your position: 52.3702 4.8952 · 52 22.2 N 4 53.7 E · 31U 629025 5803904", p ? p.lat.toFixed(5) + " " + p.lon.toFixed(5) : "");
  if (v === null || !v.trim()) return;
  const r = await api("/api/position", { text: v });
  if (r.error) return toast(r.error.replace("bad request: ", ""));
  toast("Position set: " + r.manual_pos.lat.toFixed(5) + ", " + r.manual_pos.lon.toFixed(5));
  pollGps(); loadStatus && loadStatus();
};
$("#dr-mode").onclick = async (e) => {
  if (!e.target.dataset.m) return;
  await api("/api/dr", { mode: e.target.dataset.m }); drRefresh();
};
$("#dr-boat").onclick = async () => {
  const b = (S.drStatus && S.drStatus.boat) || {};
  const v = await askText("Boat speed in knots and course in degrees (e.g. 5.5 230). Course empty = use the compass. Empty = last GPS speed and course.",
    b.speed_kn != null ? `${b.speed_kn} ${b.course ?? ""}`.trim() : "");
  if (v === null) return;
  const n = v.trim().split(/[\s,]+/).filter(Boolean).map(Number);
  if (n.some(isNaN) || n.length > 2) return toast("Type a speed and a course, e.g. 5.5 230");
  await api("/api/dr", { mode: "boat", speed_kn: n.length ? n[0] : null, course: n.length > 1 ? n[1] % 360 : null });
  drRefresh();
};
$("#go-clear").onclick = () => setTarget(null);
$("#cal-start").onclick = async () => {
  const r = await api("/api/compass/calibrate", { start: true });
  if (!r.calibrating) return toast("No compass sensor");
  toast("Turn the device slowly through 2 full circles, flat...");
  setTimeout(async () => { await api("/api/compass/calibrate", {}); toast("Compass calibrated"); }, 20000);
};

// ---------------------------------------------------------------- FIND page
const CATS = [["water", "Water"], ["shelter", "Shelter"], ["hospital", "Hospital"], ["doctor", "Doctor"],
  ["pharmacy", "Pharmacy"], ["aed", "AED"], ["police", "Police"], ["fire", "Fire stn"], ["food", "Food shop"],
  ["fuel", "Fuel"], ["hardware", "Hardware"], ["camp", "Camp"], ["toilet", "Toilet"], ["phone", "Phone"],
  ["peak", "Peak"], ["cave", "Cave"], ["airport", "Airport"]];
const CAT_LABEL = { water: "Drinking water / spring", shelter: "Shelter", hospital: "Hospital", doctor: "Doctor / clinic",
  pharmacy: "Pharmacy", aed: "AED defibrillator", police: "Police", fire: "Fire station", food: "Food shop", fuel: "Fuel station",
  hardware: "Hardware shop", camp: "Campsite", toilet: "Toilet", phone: "Phone", peak: "Summit", cave: "Cave",
  airport: "Airport", country: "Country", sea: "Sea", ocean: "Ocean", lake: "Lake" };
$("#cats").innerHTML = CATS.map(c => `<button data-c="${c[0]}">${c[1]}</button>`).join("");
$("#cats").onclick = (e) => { if (e.target.dataset.c) { S.cat = e.target.dataset.c; loadNearest(); } };

// how far to zoom in when showing a search result on the map
const KIND_ZOOM = { country: 5, ocean: 3, sea: 5, lake: 8, airport: 13 };
function zoomFor(kind) { return KIND_ZOOM[kind] || 16; }
function resultRow(r, i) {
  const sub = [CAT_LABEL[r.kind] || r.kind || CAT_LABEL[r.cat] || r.cat, r.dist_m != null ? fmtDist(r.dist_m) + " " + cardinal(r.bearing) : "",
    r.tags && r.tags.opening_hours ? r.tags.opening_hours : "", r.info || ""].filter(Boolean).join(" · ");
  return `<div class="item" data-i="${i}">${r.bearing != null ? arrowFor(r.bearing) : ""}
    <div class="grow"><div class="name">${esc(r.name || CAT_LABEL[r.cat] || r.kind)}</div><div class="small">${esc(sub)}</div></div>
    <button data-a="go">Go</button><button data-a="map">Map</button></div>`;
}
async function loadNearest() {
  document.querySelectorAll("#cats button").forEach(b => b.classList.toggle("on", b.dataset.c === S.cat));
  const at = S.nearAt || myPos() || { lat: map.lat, lon: map.lon };
  const fromMap = !S.nearAt && !myPos();
  S.nearAt = null;
  $("#find-list").innerHTML = '<div class="small">Searching...</div>';
  const r = await api(`/api/nearest?cat=${S.cat}&lat=${at.lat}&lon=${at.lon}&limit=15`);
  S.results = Array.isArray(r) ? r : [];
  $("#find-list").innerHTML = (fromMap ? '<div class="small">No GPS: distances from the map centre.</div>' : "") +
    (S.results.length ? S.results.map(resultRow).join("") : `<div class="small">${esc(r.error || "Nothing found within 50 km.")}</div>`);
}
async function doSearch() {
  const q = $("#find-q").value.trim();
  if (!q) return;
  const r = await api("/api/search?q=" + encodeURIComponent(q));
  S.results = r;
  document.querySelectorAll("#cats button").forEach(b => b.classList.remove("on"));
  $("#find-list").innerHTML = r.length ? r.map(resultRow).join("") : '<div class="small">No match.</div>';
}
$("#find-go").onclick = doSearch;
$("#find-q").onkeydown = (e) => { if (e.key === "Enter") doSearch(); };
$("#find-list").onclick = (e) => {
  const a = e.target.dataset.a, it = e.target.closest(".item");
  if (!a || !it) return;
  const r = S.results[it.dataset.i];
  if (a === "go") { setTarget({ name: r.name || r.cat, lat: r.lat, lon: r.lon }); show("go"); }
  if (a === "map") { S.follow = false; $("#follow").classList.remove("on"); show("map"); map.setView(r.lat, r.lon, zoomFor(r.kind)); }
};

// ---------------------------------------------------------------- RADIO page
let radio = null;
function radioRender(st) {
  radio = Object.assign(radio || {}, st);
  if (!radio.available) {
    $("#radio-on").classList.add("hidden");
    $("#radio-off").classList.remove("hidden");
    $("#radio-off").innerHTML = "<b>Radio not detected.</b><br>" + esc(radio.error || "") +
      "<br><span class='small'>Check the radio module wiring (SDA GPIO2, SCL GPIO3, 3.3 V, GND), that I2C is enabled, and radio_chip in config.json.</span>";
    return;
  }
  $("#radio-on").classList.remove("hidden"); $("#radio-off").classList.add("hidden");
  $("#r-busy").classList.toggle("hidden", !st.busy);
  $("#r-busy").textContent = st.busy ? st.busy + " (the controls are locked until it's done)" : "";
  $("#r-fine").classList.toggle("hidden", !(radio.mode === "usb" || radio.mode === "lsb"));
  $("#r-freq").textContent = radio.label + (radio.bfo ? (radio.bfo > 0 ? " +" : " ") + radio.bfo + " Hz" : "");
  $("#r-rds").textContent = radio.rds || radio.band;
  $("#r-rssi").textContent = radio.rssi + " dBµV";
  $("#r-snr").textContent = [radio.snr != null ? "SNR " + radio.snr + " dB" : "", radio.stereo ? "stereo" : "",
    radio.valid ? "station" : ""].filter(Boolean).join(" · ");
  $("#r-bar").style.width = Math.min(100, radio.rssi * 1.6) + "%";
  if (radio.volume_max) $("#r-vol").max = radio.volume_max;
  $("#r-vol").value = radio.volume;
  $("#r-bands").classList.toggle("hidden", !radio.bands || radio.bands.length < 2);
  if (radio.bands) $("#r-bands").innerHTML = radio.bands.map(b => `<button data-b="${b}" class="${b === radio.band ? "on" : ""}">${b}</button>`).join("");
  if (radio.presets) $("#r-presets").innerHTML = radio.presets.map(p => `
    <div class="item" data-id="${p.id}"><div class="grow"><div class="name">${esc(p.name)}</div>
    <div class="small">${p.band} · ${p.band === "FM" ? (p.freq / 100).toFixed(1) + " MHz" : p.freq + " kHz"}</div></div>
    <button data-a="play" data-band="${p.band}" data-freq="${p.freq}">Play</button><button data-a="del">&#10005;</button></div>`).join("")
    || '<div class="small">No presets. Use "Scan band" to find stations, or tune and "Save preset".</div>';
}
async function radioRefresh() { radioRender(await api("/api/radio")); }
async function radioDo(body) { radioRender(await api("/api/radio", body)); }
document.querySelectorAll("[data-r]").forEach(b => b.onclick = () => radioDo({ action: b.dataset.r, dir: +b.dataset.dir }));
$("#r-bands").onclick = (e) => { if (e.target.dataset.b) radioDo({ action: "band", band: e.target.dataset.b }); };
$("#r-vol").onchange = (e) => radioDo({ action: "volume", volume: +e.target.value });
$("#r-mute").onclick = () => { radio.muted = !radio.muted; $("#r-mute").textContent = radio.muted ? "Unmute" : "Mute"; radioDo({ action: "mute", on: radio.muted }); };
$("#r-save").onclick = async () => { const n = await askText("Preset name", radio.rds || radio.label); if (n === null) return; await api("/api/radio/preset", { name: n }); radioRefresh(); };
$("#r-scan").onclick = async () => { toast("Scanning " + (radio.band || "FM") + "... (up to a minute)"); const r = await api("/api/radio", { action: "scan" }); toast("Found " + (r.stations || []).length + " stations"); radioRefresh(); };
$("#r-presets").onclick = async (e) => {
  const a = e.target.dataset.a, it = e.target.closest(".item");
  if (!a || !it) return;
  if (a === "play") {
    if (e.target.dataset.band !== radio.band) await api("/api/radio", { action: "band", band: e.target.dataset.band });
    radioDo({ action: "tune", freq: +e.target.dataset.freq });
  }
  if (a === "del") { await api("/api/radio/preset", { delete: it.dataset.id }); radioRefresh(); }
};
setInterval(() => { if (S.page === "radio" && radio && radio.available) api("/api/radio").then(radioRender); }, 2000);
document.querySelectorAll("[data-bfo]").forEach(b => b.onclick = () => {
  const d = +b.dataset.bfo;
  radioDo({ action: "bfo", bfo: d === 0 ? 0 : (radio.bfo || 0) + d });
});

// ---------------------------------------------------------------- weather by shortwave
const SW = { station: load("sw_station") || "dwd-fax-7880", minutes: load("sw_minutes") || 12, data: null };
async function swRefresh() {
  let d;
  try { d = await api("/api/sw"); } catch (e) { return; }
  SW.data = d;
  $("#sw-off").classList.toggle("hidden", d.ready || !!d.job);
  $("#sw-off").innerHTML = d.ready ? "" : "<b>Can't receive yet.</b> " + esc(d.reason || "") +
    "<br>Needed: the Si4732 radio, its SSB patch, the USB sound stick and the long wire antenna. See the guide page <i>Weather fax and text by radio</i>.";
  $("#sw-form").classList.toggle("hidden", !d.ready || !!d.job);
  const j = d.job;
  $("#sw-job").classList.toggle("hidden", !j);
  if (j) {
    const words = { tuning: "Tuning...", recording: "Recording", decoding: "Decoding (a minute or two)..." };
    const el = j.elapsed_s || 0;
    $("#sw-job").innerHTML = `<div class="big">${esc(j.name)}</div>
      <div>${words[j.state] || j.state}${j.state === "recording" ? ` ${Math.floor(el / 60)}:${pad2(el % 60)} of ${j.minutes}:00` : ""}</div>
      ${j.state === "recording" ? `<div class="small">Signal ${j.rssi ?? "--"} dBµV · SNR ${j.snr ?? "--"} dB · sound level</div>
      <div class="bar"><i style="width:${Math.round((j.level || 0) * 100)}%"></i></div>` : ""}
      ${j.state !== "decoding" ? '<div class="row"><button id="sw-stop">Stop</button></div>' : ""}`;
    const b = $("#sw-stop"); if (b) b.onclick = async () => { await api("/api/sw/stop", {}); toast("Stopping..."); };
  }
  const cur = d.stations.find(s => s.id === SW.station) || d.stations[0];
  SW.region = SW.region || cur.region;
  $("#sw-regions").innerHTML = d.regions.map(r => `<button data-r2="${r}" class="${r === SW.region ? "on" : ""}">${r}</button>`).join("");
  $("#sw-stations").innerHTML = d.stations.filter(s => s.region === SW.region)
    .map(s => `<button data-s="${s.id}" class="${s.id === SW.station ? "on" : ""}">${esc(s.short)}</button>`).join("");
  $("#sw-min").innerHTML = [5, 12, 20, 30].map(m => `<button data-m="${m}" class="${m === SW.minutes ? "on" : ""}">${m}</button>`).join("");
  const st = d.stations.find(s => s.id === SW.station);
  const name = (id) => (d.stations.find(s => s.id === id) || { short: id }).short;
  $("#sw-sched").innerHTML = d.schedule.length ? d.schedule.map(s => `<div class="item" data-id="${s.id}"><div class="grow">
      <div class="name">Every day ${s.time} UTC</div><div class="small">${esc(name(s.station))} · ${s.minutes} min</div></div>
      <button data-a="del">&#10005;</button></div>`).join("") : "";
  $("#sw-last").textContent = (st ? st.name + " (radio dial " + st.dial + " kHz USB). " : "") +
    "Now " + d.utc + " UTC." + (d.last ? " Last reception: " + d.last.message : "");
  $("#sw-results").innerHTML = d.results.map((r, i) => `<div class="item" data-i="${i}">
      ${r.kind === "fax" ? `<img src="/sw/${esc(r.small)}" class="sw-thumb" data-a="open">` : '<div class="sw-thumb sw-txt" data-a="open">TXT</div>'}
      <div class="grow" data-a="open"><div class="name" data-a="open">${esc(name(r.station))}</div>
      <div class="small" data-a="open">${swTime(r.time_utc)} UTC · ${r.kind === "fax" ? r.lines + " lines" + (r.complete ? "" : ", partly") : r.chars + " characters"}</div></div>
      <button data-a="open">Open</button></div>`).join("") ||
    '<div class="small">No charts or texts yet. Pick a station and "Receive now", or add a daily time from the broadcast schedule.</div>';
}
function swTime(t) { return t ? `${t.slice(6, 8)}-${t.slice(4, 6)} ${t.slice(9, 11)}:${t.slice(11, 13)}` : ""; }
// ---------------------------------------------------------------- airband (RTL-SDR)
const AIR = { sel: load("air_sel") || 121.5, sq: load("air_sq") || "low", data: null };
async function airRefresh() {
  let d; try { d = await api("/api/air"); } catch (e) { return; }
  AIR.data = d;
  $("#air-off").classList.toggle("hidden", d.ready);
  $("#air-off").innerHTML = d.ready ? "" : "<b>Airband receiver not ready.</b> " + esc(d.reason || "") +
    "<br>Needs the SDR stick with its antenna, in one of the Pi's USB ports. See the guide page <i>Listening to aircraft</i>.";
  $("#air-on").classList.toggle("hidden", !d.ready);
  const L = d.listening;
  $("#air-now").classList.toggle("hidden", !L);
  if (L) $("#air-now").innerHTML = `<div class="big">${L.freqs.length > 1 ? "Scanning " + L.freqs.length + " channels" : L.freqs[0].toFixed(3) + " MHz"}</div>
    <div class="small">Squelch ${L.squelch}${d.error ? " · " + esc(d.error) : ""}</div><div class="row"><button id="air-stop">Stop</button></div>`;
  const b = $("#air-stop"); if (b) b.onclick = async () => { await api("/api/air", { action: "stop" }); airRefresh(); };
  $("#air-freqs").innerHTML = d.freqs.map(f => `<button data-f="${f.mhz}" class="${f.mhz === AIR.sel ? "on" : ""}">${esc(f.name)} ${f.mhz.toFixed(3)}</button>`).join("");
  $("#air-sq").innerHTML = d.squelch_levels.map(q => `<button data-q="${q}" class="${q === AIR.sq ? "on" : ""}">${q}</button>`).join("");
}
$("#air-freqs").onclick = async (e) => {
  const f = e.target.dataset.f; if (!f) return;
  if (+f === AIR.sel && await askConfirm("Remove " + (+f).toFixed(3) + " MHz from the list?", "Remove")) {
    await api("/api/air", { action: "remove", mhz: +f });
  }
  AIR.sel = +f; save("air_sel", AIR.sel); airRefresh();
};
$("#air-sq").onclick = (e) => { if (e.target.dataset.q) { AIR.sq = e.target.dataset.q; save("air_sq", AIR.sq); airRefresh(); } };
async function airDo(body) { const r = await api("/api/air", body); if (r.error) toast(r.error); airRefresh(); }
$("#air-listen").onclick = () => airDo({ action: "listen", mhz: [AIR.sel], squelch: AIR.sq });
$("#air-scan").onclick = () => airDo({ action: "listen", mhz: AIR.data.freqs.map(f => f.mhz), squelch: AIR.sq });
$("#air-add").onclick = async () => {
  const v = await askText("Frequency in MHz and a name, e.g. 118.275 Tower (from an aviation chart)", "");
  if (v === null || !v.trim()) return;
  const m = v.trim().match(/^(\d{3}[.,]\d{1,3})\s*(.*)$/);
  if (!m) return toast("Start with the frequency, e.g. 118.275");
  const r = await api("/api/air", { action: "add", mhz: +m[1].replace(",", "."), name: m[2] });
  if (r.error) return toast(r.error.replace("bad request: ", ""));
  AIR.sel = +(+m[1].replace(",", ".")).toFixed(3); save("air_sel", AIR.sel); airRefresh();
};
setInterval(() => { if (S.page === "radio") airRefresh(); }, 4000);
// ---------------------------------------------------------------- torch
function lightRender(d) {
  $("#light-msg").textContent = d.available ? (d.sos ? "Flashing SOS (... --- ...) with the white light." : "")
    : "Light not available: " + (d.error || "");
  $("#lt-white").classList.toggle("on", d.white.on); $("#lt-white").textContent = d.white.on ? "Torch OFF" : "Torch ON";
  $("#lt-red").classList.toggle("on", d.red.on); $("#lt-red").textContent = d.red.on ? "Red OFF" : "Red ON";
  $("#lt-wb").value = d.white.brightness; $("#lt-rb").value = d.red.brightness;
  $("#lt-sos").textContent = d.sos ? "Stop SOS" : "SOS signal";
  $("#torch").classList.toggle("lit", d.white.on || d.red.on || d.sos);
  S.light = d;
}
async function lightDo(b) { lightRender(await api("/api/light", b)); }
$("#torch").onclick = async () => { lightRender(await api("/api/light")); $("#light-sheet").classList.remove("hidden"); };
$("#lt-close").onclick = () => $("#light-sheet").classList.add("hidden");
$("#light-sheet").onclick = (e) => { if (e.target.id === "light-sheet") $("#light-sheet").classList.add("hidden"); };
$("#lt-white").onclick = () => lightDo({ which: "white", on: !S.light.white.on });
$("#lt-red").onclick = () => lightDo({ which: "red", on: !S.light.red.on });
$("#lt-wb").onchange = (e) => lightDo({ which: "white", brightness: +e.target.value });
$("#lt-rb").onchange = (e) => lightDo({ which: "red", brightness: +e.target.value });
$("#lt-sos").onclick = () => lightDo({ sos: !S.light.sos });
// ---------------------------------------------------------------- Meshtastic messages
async function meshRefresh() {
  let d; try { d = await api("/api/mesh"); } catch (e) { return; }
  $("#mesh-off").classList.toggle("hidden", d.available);
  $("#mesh-on").classList.toggle("hidden", !d.available);
  $("#mesh-off").innerHTML = "<b>No message radio.</b> " + esc(d.error || "") +
    "<br>Plug a Meshtastic node (Heltec or LilyGO LoRa board) into a USB port of the Pi.";
  if (!d.available) return;
  $("#mesh-msgs").innerHTML = d.messages.slice().reverse().map(m => `<div class="item"><div class="grow">
    <div class="name">${m.out ? "Me" : esc(m.from)}</div><div>${esc(m.text)}</div>
    <div class="small">${new Date(m.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}${m.snr != null ? " · SNR " + m.snr : ""}</div></div></div>`).join("")
    || '<div class="small">No messages yet.</div>';
  $("#mesh-nodes").textContent = d.nodes.length ? d.nodes.length + " nodes nearby: " +
    d.nodes.map(n => n.name).join(", ") : "No other nodes heard yet.";
}
async function meshDo(body) {
  const r = await api("/api/mesh", body);
  if (r.error) toast(r.error); meshRefresh();
}
$("#mesh-send").onclick = async () => {
  const t = await askText("Message (sent to all nodes nearby)", "");
  if (t === null || !t.trim()) return;
  meshDo({ action: "send", text: t });
};
$("#mesh-pos").onclick = () => meshDo({ action: "position" });
setInterval(() => { if (S.page === "share") meshRefresh(); }, 5000);
$("#wx-sw").onclick = () => { show("radio"); setTimeout(() => $("#sw-head").scrollIntoView(), 50); };
$("#sw-regions").onclick = (e) => { if (e.target.dataset.r2) { SW.region = e.target.dataset.r2; swRefresh(); } };
$("#sw-stations").onclick = (e) => { if (e.target.dataset.s) { SW.station = e.target.dataset.s; save("sw_station", SW.station); swRefresh(); } };
$("#sw-min").onclick = (e) => { if (e.target.dataset.m) { SW.minutes = +e.target.dataset.m; save("sw_minutes", SW.minutes); swRefresh(); } };
$("#sw-go").onclick = async () => {
  const r = await api("/api/sw/receive", { station: SW.station, minutes: SW.minutes });
  if (r.error) return toast(r.error);
  toast("Receiving for " + SW.minutes + " minutes"); swRefresh(); radioRefresh();
};
$("#sw-add").onclick = async () => {
  const v = await askText("Daily time in UTC (HH:MM), from the broadcast schedule", "");
  if (v === null) return;
  const r = await api("/api/sw/schedule", { time: v.trim(), station: SW.station, minutes: SW.minutes });
  if (r.error) return toast("Use the form 09:30");
  swRefresh();
};
$("#sw-sched").onclick = async (e) => {
  const it = e.target.closest(".item");
  if (e.target.dataset.a === "del" && it) { await api("/api/sw/schedule", { delete: it.dataset.id }); swRefresh(); }
};
$("#sw-results").onclick = (e) => {
  const it = e.target.closest(".item");
  if (e.target.dataset.a === "open" && it) swOpen(SW.data.results[it.dataset.i]);
};
let viewing = null;
async function swOpen(r) {
  viewing = r;
  $("#v-title").textContent = r.name + " · " + swTime(r.time_utc) + " UTC";
  $("#v-zoom").classList.toggle("hidden", r.kind !== "fax");
  if (r.kind === "fax") {
    $("#v-body").innerHTML = `<img src="/sw/${esc(r.small)}" class="fit">`;
  } else {
    const t = await fetch("/sw/" + r.file).then(x => x.text());
    $("#v-body").innerHTML = "<pre></pre>"; $("#v-body pre").textContent = t;
  }
  $("#viewer").classList.remove("hidden");
}
$("#v-close").onclick = () => { $("#viewer").classList.add("hidden"); $("#v-body").innerHTML = ""; };
$("#v-zoom").onclick = () => {
  const img = $("#v-body img"); if (!img) return;
  const big = img.classList.toggle("fit") === false;
  img.src = "/sw/" + (big ? viewing.file : viewing.small);
};
$("#v-del").onclick = async () => {
  if (!await askConfirm("Delete this " + (viewing.kind === "fax" ? "chart" : "text") + "?", "Delete")) return;
  await api("/api/sw/delete", { id: viewing.id }); $("#v-close").onclick(); swRefresh();
};
setInterval(() => { if (S.page === "radio") swRefresh(); }, 3000);

// ---------------------------------------------------------------- WEATHER page
async function loadWeather() {
  const w = await api("/api/weather");
  if (!w.available) {
    $("#wx-now").innerHTML = ""; $("#wx-fc").textContent = "No weather sensor detected (BME280 on I2C).";
    $("#wx-warn").innerHTML = ""; return;
  }
  if (w.temp_c == null) { $("#wx-fc").textContent = w.message; return; }
  const tr = w.trend_hpa_3h;
  const arrow = tr == null ? "" : tr <= -1.6 ? " ↓" : tr >= 1.6 ? " ↑" : " →";
  const uv = w.uv_index;
  const uvTxt = uv == null ? null : uv.toFixed(1) + (uv >= 6 ? " burn" : uv >= 3 ? " cover up" : "");
  $("#wx-uv").innerHTML = uv != null && uv >= 3
    ? `<div class="warn">UV index ${uv.toFixed(1)}: ${uv >= 8 ? "very high, sunburn in minutes. Stay in shade, cover skin and eyes." : "high, sunburn in under 30 minutes. Cover up and use shade."}</div>` : "";
  $("#wx-now").innerHTML = [
    ["Temp", w.temp_c + "°C"], ["Humidity", w.humidity != null ? Math.round(w.humidity) + "%" : "--"],
    ["Pressure", Math.round(w.pressure_msl_hpa) + arrow], ["Dew pt", w.dew_point_c != null ? w.dew_point_c + "°" : "--"],
    ...(uvTxt ? [["UV index", uvTxt]] : []),
    ...(w.air_quality != null ? [["Air", w.air_quality >= 70 ? "clean" : w.air_quality >= 40 ? "fair" : "poor"]] : []),
  ].map(x => `<div class="card"><div class="small">${x[0]}</div><div class="v">${x[1]}</div></div>`).join("");
  $("#wx-fc").innerHTML = esc(w.forecast) + (tr != null ? `<div class="small">Pressure ${tr > 0 ? "+" : ""}${tr} hPa in 3 h (sea level, alt ${Math.round(w.altitude_m)} m)</div>` : "");
  $("#wx-warn").innerHTML = (w.warnings || []).map(x => `<div class="warn">${esc(x)}</div>`).join("");
  drawWeatherChart(w.history || []);
}
function drawWeatherChart(h) {
  const c = $("#wx-chart"), r = c.getBoundingClientRect();
  c.width = r.width; const ctx = c.getContext("2d"), W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  if (h.length < 2) return;
  const ps = h.map(x => x[2]), lo = Math.min(...ps) - 1, hi = Math.max(...ps) + 1;
  const t0 = h[0][0], t1 = h[h.length - 1][0];
  ctx.strokeStyle = "#2c333a"; ctx.fillStyle = "#8d949b"; ctx.font = "10px sans-serif";
  ctx.fillText(hi.toFixed(0) + " hPa", 2, 10); ctx.fillText(lo.toFixed(0), 2, H - 2);
  ctx.fillText("last " + Math.round((t1 - t0) / 3600) + " h (station pressure)", W - 150, H - 2);
  ctx.beginPath();
  h.forEach((x, i) => { const px = 40 + (x[0] - t0) / (t1 - t0 || 1) * (W - 44), py = H - 12 - (x[2] - lo) / (hi - lo) * (H - 22); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
  ctx.strokeStyle = "#f0a020"; ctx.lineWidth = 2; ctx.stroke();
}
setInterval(() => { if (S.page === "wx") loadWeather(); }, 60000);

// ---------------------------------------------------------------- downloaded forecast grid
let FC = null, fcDay = 0;
const DAYNAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const windArrow = (dir) => dir == null ? "" :
  `<span style="display:inline-block;transform:rotate(${dir + 180}deg)">&#8593;</span>`;  // points where the wind blows to
function fmtAge(h) { return h < 1 ? Math.round(h * 60) + " min" : h < 48 ? Math.round(h) + " h" : Math.round(h / 24) + " days"; }
async function loadForecast() {
  FC = await api("/api/forecast");
  // offline device: only show this section if downloading is switched on or old data exists
  const show = FC.enabled || !!FC.days;
  ["#fc-head", "#fc-row", "#fc-grid"].forEach(s => $(s).classList.toggle("hidden", !show));
  $("#fc-update").classList.toggle("hidden", !FC.enabled);
  if (!show) return;
  if (!FC.days) {
    $("#fc-age").textContent = FC.busy ? "Downloading..." : (FC.error || FC.message);
    $("#fc-days").innerHTML = ""; $("#fc-hours").innerHTML = ""; $("#fc-grid-title").textContent = "";
    $("#fc-grid").getContext("2d").clearRect(0, 0, 9999, 9999);
    return;
  }
  $("#fc-age").textContent = `Downloaded ${fmtAge(FC.age_h)} ago` + (FC.error ? " · last update failed" : "");
  // drop days that are already over
  const today = new Date().toISOString().slice(0, 10);
  FC.days = FC.days.filter(d => d.date >= today);
  if (fcDay >= FC.days.length) fcDay = 0;
  $("#fc-warn").innerHTML = FC.age_h > 72
    ? `<div class="warn">This forecast is ${fmtAge(FC.age_h)} old. Days 1-5 after the download are fairly reliable, later days are only trends. Trust the barometer above for the next hours.</div>` : "";
  $("#fc-days").innerHTML = FC.days.map((d, i) => {
    const dt = new Date(d.date + "T12:00");
    return `<div class="fc-day ${i === fcDay ? "on" : ""}" data-i="${i}">
      <b>${i === 0 && d.date === today ? "Today" : DAYNAMES[dt.getDay()] + " " + dt.getDate()}</b>
      <div class="small">${esc(d.text)}</div>
      <div class="t">${d.tmax != null ? Math.round(d.tmax) : "-"}° <span class="small">${d.tmin != null ? Math.round(d.tmin) : "-"}°</span></div>
      <div>${d.rain != null ? d.rain.toFixed(1) : "-"} mm${d.rain_prob != null ? " · " + d.rain_prob + "%" : ""}</div>
      <div>${windArrow(d.wind_dir)} ${d.gust != null ? Math.round(d.gust) : "-"} km/h</div></div>`;
  }).join("");
  drawForecastGrid();
  renderHours();
}
$("#fc-days").onclick = (e) => { const c = e.target.closest(".fc-day"); if (c) { fcDay = +c.dataset.i; loadForecast(); } };
$("#fc-update").onclick = async () => {
  toast("Downloading forecast (needs WiFi or a phone hotspot)...");
  const r = await api("/api/forecast/update", {});
  toast(r.error ? r.error : "Forecast updated");
  loadForecast();
};
function drawForecastGrid() {
  const c = $("#fc-grid"), g = FC.grid || [];
  const r = c.getBoundingClientRect(); c.width = r.width;
  const ctx = c.getContext("2d"), W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  const day = FC.days[fcDay];
  const k = day && FC.grid_dates ? FC.grid_dates.indexOf(day.date) : -1;
  if (!g.length || k < 0) { $("#fc-grid-title").textContent = ""; return; }
  const lats = [...new Set(g.map(p => p.lat))].sort((a, b) => b - a);
  const lons = [...new Set(g.map(p => p.lon))].sort((a, b) => a - b);
  const cw = W / lons.length, ch = H / lats.length;
  const fg = document.body.classList.contains("night") ? "#ff3b2f" : "#e8e6e1";
  const pick = (arr) => arr ? arr[k] : null;
  for (const p of g) {
    const rain = pick(p.rain), gust = pick(p.gust), dir = pick(p.wind_dir), tmax = pick(p.tmax);
    const col = lons.indexOf(p.lon), row = lats.indexOf(p.lat);
    const x = col * cw, y = row * ch;
    ctx.fillStyle = `rgba(30,136,229,${0.08 + Math.min(1, (rain || 0) / 15) * 0.8})`;
    ctx.fillRect(x + 1, y + 1, cw - 2, ch - 2);
    ctx.fillStyle = fg; ctx.font = "11px sans-serif"; ctx.textAlign = "center";
    if (rain != null) ctx.fillText(rain.toFixed(0) + " mm", x + cw / 2, y + 13);
    if (tmax != null) ctx.fillText(Math.round(tmax) + "°", x + cw / 2, y + ch - 5);
    if (dir != null) {
      ctx.save(); ctx.translate(x + cw / 2, y + ch / 2 + 1); ctx.rotate((dir + 180) * Math.PI / 180);
      const len = Math.min(cw, ch) * 0.17;
      ctx.beginPath(); ctx.moveTo(0, len); ctx.lineTo(0, -len); ctx.lineTo(-4, -len + 6); ctx.moveTo(0, -len); ctx.lineTo(4, -len + 6);
      ctx.strokeStyle = gust >= 75 ? "#e5533d" : gust >= 50 ? "#f0a020" : fg;
      ctx.lineWidth = 2; ctx.stroke(); ctx.restore();
    }
    if (row === (lats.length - 1) / 2 && col === (lons.length - 1) / 2) {
      ctx.strokeStyle = "#f0a020"; ctx.lineWidth = 2; ctx.strokeRect(x + 2, y + 2, cw - 4, ch - 4);
    }
  }
  const km = Math.round((lats[0] - lats[lats.length - 1]) * 111);
  $("#fc-grid-title").textContent = `Area map for ${day.date}, about ${km} km north to south, you are in the orange box. ` +
    "Blue = rain, arrows = wind direction (orange 50+, red 75+ km/h gusts).";
}
function renderHours() {
  const hs = FC.hours || [];
  if (!hs.length) { $("#fc-hours").innerHTML = ""; return; }
  const rows = hs.filter((_, i) => i % 3 === 0).slice(0, 16).map(h => {
    const [t, temp, rain, prob, code, wind, gust, dir] = h;
    const d = new Date(t);
    return `<tr><td>${DAYNAMES[d.getDay()]} ${t.slice(11, 16)}</td><td>${temp != null ? Math.round(temp) + "°" : ""}</td>
      <td>${rain != null ? rain.toFixed(1) : ""} mm</td><td>${prob != null ? prob + "%" : ""}</td>
      <td>${windArrow(dir)} ${wind != null ? Math.round(wind) : ""}/${gust != null ? Math.round(gust) : ""}</td></tr>`;
  }).join("");
  $("#fc-hours").innerHTML = `<table class="fc-table"><tr><th>Time</th><th>Temp</th><th>Rain</th><th>Chance</th><th>Wind/gust km/h</th></tr>${rows}</table>`;
}
setInterval(() => { if (S.page === "wx") loadForecast(); }, 300000);

// ---------------------------------------------------------------- LIBRARY page
const SECTION_NAMES = { "00-emergency": "Emergency first", "my-pages": "My pages", firstaid: "First aid", water: "Water", food: "Food",
  shelter: "Shelter & fire", wild: "Wilderness", plants: "Plants & mushrooms", navigation: "Navigation", comms: "Signals & radio", signs: "Flags & signs", skills: "Skills & tools",
  general: "General" };
async function loadLibraryIndex() {
  let idx;
  try { idx = await api("/api/library"); } catch (e) {
    // the app server was restarting: say so instead of leaving the page blank
    $("#lib-index").innerHTML = '<button data-retry="1">Could not load the guide. Tap to try again.</button>';
    return;
  }
  const order = Object.keys(SECTION_NAMES);
  const rank = (s) => (order.indexOf(s) + 1) || 99;
  $("#lib-index").innerHTML = Object.keys(idx).sort((a, b) => rank(a) - rank(b)).map(sec => `<div class="sec"><h3>${esc(SECTION_NAMES[sec] || sec)}</h3>
    ${idx[sec].map(p => `<button data-page="${p.id}">${esc(p.title)}</button>`).join("")}</div>`).join("");
}
async function openPage(id) {
  const p = await api("/api/library/page?id=" + encodeURIComponent(id));
  $("#lib-body").innerHTML = p.html || "Not found";
  if (!$("#lib-index").classList.contains("hidden")) libIndexScroll = $("#p-info").scrollTop;
  $("#lib-index").classList.add("hidden"); $("#lib-page").classList.remove("hidden");
  $("#p-info").scrollTop = 0;
}
$("#lib-index").onclick = (e) => {
  if (e.target.dataset.retry) return loadLibraryIndex();
  const id = e.target.dataset.page; if (id) openPage(id);
};
$("#lib-body").onclick = (e) => { const id = e.target.dataset.page; if (id) { e.preventDefault(); openPage(id); } };
let libIndexScroll = 0;
$("#p-info").addEventListener("scroll", () => $("#lib-page").classList.toggle("scrolled", $("#p-info").scrollTop > 30));
$("#lib-back").onclick = () => {
  $("#lib-page").classList.add("hidden"); $("#lib-index").classList.remove("hidden");
  $("#p-info").scrollTop = libIndexScroll;  // back to where you were in the list
};
let libSize = load("libSize") || 15;
const applySize = () => { $("#lib-body").style.fontSize = libSize + "px"; save("libSize", libSize); };
$("#lib-bigger").onclick = () => { libSize = Math.min(24, libSize + 1); applySize(); };
$("#lib-smaller").onclick = () => { libSize = Math.max(11, libSize - 1); applySize(); };
applySize();
async function libSearch() {
  const q = $("#lib-q").value.trim();
  if (!q) { $("#lib-index").innerHTML = ""; return loadLibraryIndex(); }
  const r = await api("/api/library/search?q=" + encodeURIComponent(q));
  $("#lib-page").classList.add("hidden"); $("#lib-index").classList.remove("hidden");
  $("#lib-index").innerHTML = r.length ? r.map(h => `<div class="sec"><button data-page="${h.id}">${esc(h.title)}</button>
    <div class="small">...${esc(h.snippet)}...</div></div>`).join("") : '<div class="small">Nothing found.</div>';
}
$("#lib-go").onclick = libSearch;
$("#lib-q").onkeydown = (e) => { if (e.key === "Enter") libSearch(); };

// ---------------------------------------------------------------- SHARE (direct WiFi)
let HS = null;
function hotspotRender(h) {
  HS = h;
  $("#hs-toggle").textContent = h.active ? "Turn off" : "Turn on";
  $("#hs-toggle").classList.toggle("danger", !!h.active);
  let html = `<div class="small">WiFi name</div><div class="hs-big">${esc(h.ssid)}</div>
    <div class="small">Password</div><div class="hs-big">${esc(h.password)}</div>`;
  if (h.active) {
    html += `<div class="small">On the computer, open</div><div class="hs-big">${esc(h.files_url)}</div>
      <div class="small">${h.clients.length ? h.clients.length + " computer(s) connected" : "Waiting for a computer to join..."}</div>`;
  } else {
    html += '<div class="small">Hotspot is off. While it is on, the device cannot use other WiFi networks.</div>';
  }
  if (!h.nmcli) html += '<div class="warn">NetworkManager is not installed: run deploy/install.sh.</div>';
  if (h.error) html += `<div class="warn">${esc(h.error)}</div>`;
  $("#hs-info").innerHTML = html;
}
async function hotspotRefresh() { hotspotRender(await api("/api/hotspot")); }
$("#hs-toggle").onclick = async () => {
  $("#hs-toggle").textContent = "Please wait...";
  hotspotRender(await api("/api/hotspot", { action: HS && HS.active ? "off" : "on" }));
};
$("#hs-newpass").onclick = async () => {
  if (await askConfirm("Make a new hotspot password? Computers will need the new one.", "New password"))
    hotspotRender(await api("/api/hotspot", { action: "newpass" }));
};
setInterval(() => { if (S.page === "share") hotspotRefresh(); }, 5000);

// ---------------------------------------------------------------- SEARCH everything
const LANG_SHORT = { en: "EN", nl: "NL", es: "ES", de: "DE", fr: "FR", pt: "PT", it: "IT", pl: "PL", uk: "UK", ru: "RU", ar: "AR", tr: "TR" };
let findRun = 0;
function findRow(attrs, title, sub, snip, extra) {
  return `<div class="item" ${attrs}>${extra || ""}<div class="grow"><div class="name">${esc(title)}</div>
    ${sub ? `<div class="small">${esc(sub)}</div>` : ""}${snip ? `<div class="snip">${esc(snip)}</div>` : ""}</div></div>`;
}
async function findAll() {
  const q = $("#s-q").value.trim();
  if (!q) return;
  const run = ++findRun;
  findClose();
  $("#s-info").textContent = "Searching...";
  $("#s-results").innerHTML = "";
  const r = await api("/api/find?q=" + encodeURIComponent(q));
  if (run !== findRun) return;
  S.find = r;
  // what the search understood: typo fixes and the query in other languages
  let info = "";
  const fixes = r.understood.filter(u => u.corrected).map(u => `<b>${esc(u.corrected)}</b>`);
  if (fixes.length) info += `<div class="s-tr">Did you mean ${fixes.join(", ")}?</div>`;
  const tr = r.translations || {};
  const langs = [...new Set(["en", "nl", "es", ...r.books.map(b => b.lang)])].filter(l => tr[l] && l !== r.language);
  if (langs.length) info += `<div class="s-tr">Also searching: ${langs.slice(0, 6).map(l => `${LANG_SHORT[l]} <b>${esc(tr[l])}</b>`).join(" · ")}</div>`;
  $("#s-info").innerHTML = info;

  let html = "";
  if (r.guide.length) html += `<div class="s-sec list"><h3>Survival guide</h3>${r.guide.map(g =>
    findRow(`data-guide="${esc(g.id)}"`, g.title, "", g.snippet)).join("")}</div>`;
  if (r.places.length) html += `<div class="s-sec list"><h3>On the map</h3>${r.places.map((p, i) =>
    findRow(`data-place="${i}"`, p.name || CAT_LABEL[p.cat] || p.kind,
      [CAT_LABEL[p.kind] || p.kind, p.dist_m != null ? fmtDist(p.dist_m) + " " + cardinal(p.bearing) : "", p.info || ""].filter(Boolean).join(" · "),
      "", p.bearing != null ? arrowFor(p.bearing) : "")).join("")}</div>`;
  if (r.videos.length) html += `<div class="s-sec list"><h3>Videos</h3>${r.videos.map(v =>
    findRow(`data-video="${esc(v.url)}" data-title="${esc(v.title)}"`, "▶ " + v.title, v.subject, v.snippet)).join("")}</div>`;
  r.books.forEach((b, i) => {
    html += `<div class="s-sec list" id="s-book-${i}"><h3>${esc(b.title)} <span class="small">${LANG_SHORT[b.lang] || b.lang} · ${esc(b.query)}</span></h3>
      <div class="small">Searching...</div></div>`;
  });
  if (!r.books.length) html += '<div class="small" style="margin-top:10px">No Wikipedia or other offline library installed yet: copy .zim files to the zim folder (see README).</div>';
  if (!html) html = '<div class="small">Nothing found.</div>';
  $("#s-results").innerHTML = html;
  // the big libraries one after another, so the little Pi stays responsive
  for (let i = 0; i < r.books.length; i++) {
    const b = r.books[i];
    let w;
    try { w = await api(`/api/find/wiki?book=${encodeURIComponent(b.name)}&q=${encodeURIComponent(b.query)}`); }
    catch (e) { w = { results: [], error: "not reachable" }; }
    if (!w.results.length && b.alt && run === findRun) {  // what you typed found nothing: try the spelling fix
      try { w = await api(`/api/find/wiki?book=${encodeURIComponent(b.name)}&q=${encodeURIComponent(b.alt)}`); } catch (e) { /* keep first */ }
    }
    if (run !== findRun) return;
    const el = $("#s-book-" + i);
    if (!el) continue;
    el.lastElementChild.outerHTML = w.results.length ? w.results.map(a =>
      findRow(`data-url="${esc(a.url)}" data-title="${esc(a.title)}"`, a.title, "", a.snippet)).join("")
      : `<div class="small">${esc(w.error ? "Not searchable: " + w.error : "Nothing found.")}</div>`;
  }
}
function findOpen(title) {
  $("#s-rtitle").textContent = title || "";
  $("#s-main").classList.add("hidden"); $("#s-reader").classList.remove("hidden");
  $("#p-search").classList.add("reading");
}
function findClose() {
  $("#s-video").pause(); $("#s-video").removeAttribute("src"); $("#s-video").load();
  $("#s-frame").src = "about:blank";
  $("#s-reader").classList.add("hidden"); $("#s-main").classList.remove("hidden");
  $("#p-search").classList.remove("reading");
}
$("#s-go").onclick = findAll;
$("#s-q").onkeydown = (e) => { if (e.key === "Enter") findAll(); };
$("#s-back").onclick = findClose;
$("#s-results").onclick = (e) => {
  const it = e.target.closest(".item");
  if (!it) return;
  const d = it.dataset;
  if (d.guide) { show("info"); openPage(d.guide); }
  else if (d.place != null) {
    const p = S.find.places[d.place];
    if (["country", "sea", "ocean", "lake"].includes(p.kind)) {  // a whole area: show it, a compass arrow means little
      S.follow = false; $("#follow").classList.remove("on"); show("map"); map.setView(p.lat, p.lon, zoomFor(p.kind));
    } else { setTarget({ name: p.name || CAT_LABEL[p.cat] || p.kind, lat: p.lat, lon: p.lon }); show("go"); }
  } else if (d.url) {
    $("#s-video").classList.add("hidden"); $("#s-frame").classList.remove("hidden");
    $("#s-frame").src = d.url; findOpen(d.title);
  } else if (d.video) {
    $("#s-frame").classList.add("hidden"); $("#s-video").classList.remove("hidden");
    $("#s-video").src = d.video; findOpen(d.title); $("#s-video").play().catch(() => {});
  }
};
let frameZoom = load("frameZoom") || 1;
function applyFrameZoom() {
  save("frameZoom", frameZoom);
  try { $("#s-frame").contentDocument.body.style.zoom = frameZoom; } catch (e) { /* not loaded yet */ }
}
$("#s-frame").onload = applyFrameZoom;
$("#s-bigger").onclick = () => { frameZoom = Math.min(2, +(frameZoom + 0.1).toFixed(1)); applyFrameZoom(); };
$("#s-smaller").onclick = () => { frameZoom = Math.max(0.6, +(frameZoom - 0.1).toFixed(1)); applyFrameZoom(); };

// ---------------------------------------------------------------- start
if (view) map.setView(view[0], view[1], view[2]);
map.overlay.target = S.target;
loadStatus().then(() => { loadWaypoints(); pollGps(); });
setInterval(loadStatus, 60000);

// ---------------------------------------------------------------- scroll arrows
// Dragging a finger on the resistive screen is hit and miss; these buttons scroll by most of a screen.
function scrollTarget() {
  // returns [element that scrolls, element that should make room for the arrows]
  if (!$("#viewer").classList.contains("hidden")) return [$("#v-body"), $("#viewer")];
  if (S.page === "search" && !$("#s-reader").classList.contains("hidden")) {
    try {
      const d = $("#s-frame").contentDocument;
      if (d && d.scrollingElement && !$("#s-frame").classList.contains("hidden")) return [d.scrollingElement, $("#s-reader")];
    } catch (e) { /* other origin: no arrows */ }
    return [null, null];
  }
  const pg = $("#p-" + S.page);
  if (!pg || S.page === "map") return [null, null];
  return [pg, pg];
}
let saRoom = null;
function scrollArrowsUpdate() {
  const [el, room] = scrollTarget();
  const can = el && el.scrollHeight > el.clientHeight + 4;
  $("#scroll-arrows").classList.toggle("hidden", !can);
  if (saRoom !== room || !can) { if (saRoom) saRoom.classList.remove("scrolly"); saRoom = null; }
  if (can) {
    if (room && !room.classList.contains("scrolly")) { room.classList.add("scrolly"); saRoom = room; }
    $("#sa-up").disabled = el.scrollTop <= 0;
    $("#sa-down").disabled = el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
  }
}
function pageScroll(dir) {
  const [el] = scrollTarget(); if (!el) return;
  el.scrollTop += dir * 100;  // about 1.5 cm on the 3.5" screen (6.5 px per mm)
  scrollArrowsUpdate();
}
$("#sa-up").onclick = () => pageScroll(-1);
$("#sa-down").onclick = () => pageScroll(1);
document.addEventListener("scroll", scrollArrowsUpdate, true);
setInterval(scrollArrowsUpdate, 700);
