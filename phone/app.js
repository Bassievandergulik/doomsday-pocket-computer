// Pocket INS: the phone's sensors feed the INS core (core/ins.js). Everything runs on the phone, offline.
import { INS, DeadReckoner, haversine, bearing, wrap180 } from "./core/ins.js";
import { parseCoords, formatDM } from "./core/coords.js";
import { startDemo } from "./demo.js";

const $ = (s) => document.querySelector(s);
const now = () => Date.now() / 1000;

// ------------------------------------------------------------------ storage (survives restarts; may be unavailable)
const store = {
  get(k) { try { const v = localStorage.getItem("ins." + k); return v == null ? undefined : JSON.parse(v); } catch { return undefined; } },
  set(k, v) { try { localStorage.setItem("ins." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

// ------------------------------------------------------------------ state
const S = {
  fix: null, fixAt: 0,             // last GPS fix and when it arrived
  compass: null, compassAt: 0,     // true heading from the phone compass
  gSign: 0, signVotes: 0,          // +1 if accelerationIncludingGravity points up (spec), -1 if inverted
  up: null,                        // gravity direction from deviceorientation, for the sign check
  lastMotion: 0, gyro: true,
  manual: store.get("manual") || null,
  wps: store.get("waypoints") || [],
  target: store.get("target") || null,
  wake: null, demo: false,
};

const getFix = () => {
  if (!S.fix) return { mode: 0 };
  return now() - S.fixAt > 6 ? { ...S.fix, stale: true } : S.fix;
};

const ins = new INS({
  model: "phone",
  getSea: () => !!store.get("sea"),
  getSteps: () => dr.steps.count,
  getRef: () => { const e = dr.estimate(); return e ? [e.lat, e.lon, e.err_m] : null; },
  spoofAction: store.get("action") || "switch",
});

const headingNow = () => ins.heading() ?? (now() - S.compassAt < 3 ? S.compass : null);

const dr = new DeadReckoner({
  getFix, store, ins,
  getHeading: headingNow,
  getManual: () => S.manual,
});
dr.track = store.get("track") || [];

// ------------------------------------------------------------------ sensors
function onMotion(e) {
  const a = e.accelerationIncludingGravity, r = e.rotationRate;
  if (!a || a.x == null) return;
  const t = performance.now() / 1000;
  if (S.lastMotion && t - S.lastMotion > 3) resumeAfterGap(t - S.lastMotion);
  S.lastMotion = t;
  const G0 = 9.80665;
  let ax = a.x / G0, ay = a.y / G0, az = a.z / G0;
  // Some browsers report gravity inverted. Vote using the gravity direction from deviceorientation.
  if (S.signVotes < 40 && S.up) {
    const d = ax * S.up[0] + ay * S.up[1] + az * S.up[2];
    if (Math.abs(d) > 0.5) { S.gSign += Math.sign(d); S.signVotes++; }
  }
  const sg = S.gSign < 0 ? -1 : 1;
  ax *= sg; ay *= sg; az *= sg;
  // phone axes: x right, y top, z out of the screen. INS axes: x top, y left, z out of the screen.
  const acc = [ay, -ax, az];
  if (dr.steps.feed(t, ax, ay, az)) dr.onStep();
  if (!r || r.alpha == null) { S.gyro = false; return; }
  S.gyro = true;
  ins.feed(t, acc, [r.gamma, -r.beta, r.alpha]);
}

function onOrientation(e, absolute) {
  if (e.beta != null && e.gamma != null) {
    const b = e.beta * Math.PI / 180, g = e.gamma * Math.PI / 180;
    S.up = [-Math.cos(b) * Math.sin(g), Math.sin(b), Math.cos(b) * Math.cos(g)];
  }
  let mag = null;
  if (typeof e.webkitCompassHeading === "number" && e.webkitCompassHeading >= 0) mag = e.webkitCompassHeading; // iPhone
  else if ((absolute || e.absolute) && e.alpha != null) mag = (360 - e.alpha) % 360;                          // Android
  if (mag == null) return;
  const decl = Number(store.get("decl") || 0);
  S.compass = (mag + decl + 360) % 360;
  S.compassAt = now();
  ins.feedCompass(performance.now() / 1000, S.compass);
}

function onPosition(p) {
  const c = p.coords;
  const speed = c.speed != null && !Number.isNaN(c.speed) ? c.speed : null;
  const track = c.heading != null && !Number.isNaN(c.heading) && (speed ?? 0) > 0.3 ? c.heading : null;
  S.fix = { mode: 3, lat: c.latitude, lon: c.longitude, speed, track, acc: c.accuracy,
    hdop: c.accuracy != null ? c.accuracy / 5 : null, time_local: p.timestamp / 1000 };
  S.fixAt = now();
}

/** The sensors were paused (screen locked, app in the background): the heading may have changed meanwhile. */
function resumeAfterGap(seconds) {
  if (ins.state === "nav" || ins.state === "nav-degraded") {
    ins.p00 = Math.max(ins.p00, 45 ** 2);   // unsure again: the next compass or GPS course resets it
    toastGap = `Sensors were paused for ${Math.round(seconds)} s. Heading reset from the compass; realign for best results.`;
  }
}
let toastGap = "";

async function requestPermissions() {
  const asks = [];
  if (typeof DeviceMotionEvent !== "undefined" && typeof DeviceMotionEvent.requestPermission === "function") asks.push(DeviceMotionEvent.requestPermission());
  if (typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function") asks.push(DeviceOrientationEvent.requestPermission());
  const res = await Promise.all(asks);
  if (res.some((x) => x !== "granted")) throw new Error("Motion access was refused. On iPhone: Settings, Safari, Motion & Orientation Access, then reopen the app.");
}

async function startSensors() {
  if (!window.isSecureContext) throw new Error("The sensors only work over https or from the installed app.");
  await requestPermissions();
  window.addEventListener("devicemotion", onMotion);
  if ("ondeviceorientationabsolute" in window) window.addEventListener("deviceorientationabsolute", (e) => onOrientation(e, true));
  window.addEventListener("deviceorientation", (e) => onOrientation(e, false));
  if ("geolocation" in navigator) {
    navigator.geolocation.watchPosition(onPosition, (err) => { S.gpsErr = err.message || "GPS unavailable"; },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 30000 });
  } else S.gpsErr = "No GPS in this browser";
  keepAwake();
}

async function keepAwake() {
  if (!("wakeLock" in navigator)) { $("#wake").textContent = "This browser can't keep the screen on: set auto-lock to Never while navigating."; return; }
  try {
    S.wake = await navigator.wakeLock.request("screen");
    $("#wake").textContent = "Screen kept on while the app is open.";
    S.wake.addEventListener("release", () => { S.wake = null; });
  } catch { $("#wake").textContent = "Couldn't keep the screen on: set auto-lock to Never while navigating."; }
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && !S.wake && !$("#main").classList.contains("hidden")) keepAwake(); });

// ------------------------------------------------------------------ once a second: dead reckoning, GPS vetting, track
setInterval(() => {
  if ($("#main").classList.contains("hidden")) return;
  dr.tick();
  if (dr.track.length && (!dr._saved || dr.track.length !== dr._saved)) { store.set("track", dr.track); dr._saved = dr.track.length; }
}, 1000);

// ------------------------------------------------------------------ UI
const fmtDeg = (d) => (d == null ? "---°" : String(Math.round(d) % 360).padStart(3, "0") + "°");
const fmtDist = (m) => (m < 1000 ? Math.round(m) + " m" : m < 20000 ? (m / 1000).toFixed(2) + " km" : Math.round(m / 1000) + " km")
  + (m >= 1852 ? ` (${(m / 1852).toFixed(m < 18520 ? 1 : 0)} NM)` : "");
const ago = (t) => { const s = Math.max(0, now() - t); return s < 90 ? Math.round(s) + " s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h"; };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

(function drawTicks() {
  let h = "";
  for (let d = 0; d < 360; d += 10) {
    const r = (d * Math.PI) / 180, major = d % 30 === 0, r1 = major ? 80 : 85;
    h += `<line class="tick${major ? " major" : ""}" x1="${Math.sin(r) * r1}" y1="${-Math.cos(r) * r1}" x2="${Math.sin(r) * 92}" y2="${-Math.cos(r) * 92}"/>`;
  }
  $("#ticks").innerHTML = h;
})();

function best() {
  const st = ins.status();
  const f = getFix();
  const gpsUsable = f.mode >= 2 && !f.stale && (st.gps !== "suspect" || st.action === "warn");
  if (gpsUsable) return { lat: f.lat, lon: f.lon, src: "gps", err: f.acc };
  const e = dr.estimate();
  if (e) return { lat: e.lat, lon: e.lon, src: "dr", err: e.err_m, e };
  return null;
}

let lastRose = null;
function render() {
  const st = ins.status();
  const f = getFix();
  // chips
  const ci = $("#chip-ins");
  if (!S.gyro) { ci.textContent = "No gyro"; ci.className = "chip warn"; }
  else if (st.state === "align") { ci.textContent = `Aligning ${st.alignPct}%`; ci.className = "chip warn"; }
  else if (st.degraded) { ci.textContent = "INS rough"; ci.className = "chip warn"; }
  else { ci.textContent = "INS nav"; ci.className = "chip ok"; }
  const cg = $("#chip-gps");
  if (st.gps === "suspect") { cg.textContent = "GPS suspect"; cg.className = "chip bad"; }
  else if (f.mode < 2) { cg.textContent = S.gpsErr ? "GPS error" : "No GPS fix"; cg.className = "chip warn"; }
  else if (f.stale) { cg.textContent = "GPS lost"; cg.className = "chip warn"; }
  else if (st.gps === "trusted-by-hand") { cg.textContent = "GPS trusted"; cg.className = "chip warn"; }
  else { cg.textContent = "GPS ok"; cg.className = "chip ok"; }

  // alignment bar
  const ab = $("#align-bar");
  if (st.state === "align" && S.gyro) {
    ab.classList.remove("hidden");
    $("#align-fill").style.width = st.alignPct + "%";
    $("#align-text").textContent = st.alignSea ? `Aligning at sea ${st.alignPct}%, keep it in one place` : `Hold still, screen up: ${st.alignPct}%`;
  } else ab.classList.add("hidden");

  // heading
  const h = headingNow();
  $("#hdg").textContent = fmtDeg(h);
  $("#hdg-src").textContent = ins.heading() != null ? `gyro-stabilised ±${Math.max(1, Math.round(st.headingSigma))}°`
    : h != null ? "compass only" : st.state === "align" ? "aligning" : "no heading yet";
  if (h != null) {
    // rotate the dial the short way round so it never spins through 360
    lastRose = lastRose == null ? -h : lastRose + wrap180(-h - lastRose);
    $("#rose-dial").style.transform = `rotate(${lastRose}deg)`;
  }
  $("#turn").textContent = S.gyro ? `${st.turnDps > 0 ? "←" : st.turnDps < 0 ? "→" : ""} ${Math.abs(st.turnDps).toFixed(1)}°/s` : "-";
  $("#tilt").textContent = st.state === "align" ? "-" : Math.round(st.tilt) + "°";
  $("#comp").textContent = now() - S.compassAt < 3 ? fmtDeg(S.compass) : "-";

  // position
  const b = best();
  if (b) {
    $("#pos").textContent = formatDM(b.lat, b.lon);
    $("#pos-dec").textContent = `${b.lat.toFixed(5)}, ${b.lon.toFixed(5)}`;
    if (b.src === "gps") $("#pos-src").innerHTML = `<span style="color:var(--ok)">GPS</span> ±${Math.round(b.err || 0)} m`;
    else {
      const why = st.gps === "suspect" ? "GPS distrusted" : f.mode < 2 || f.stale ? "no GPS" : "";
      $("#pos-src").innerHTML = `<span style="color:var(--warn)">Dead reckoning</span> ±${fmtDist(b.err)} · ${fmtDist(b.e.dist_m)} since the last ${b.e.from === "gps" ? "good GPS fix" : "position you set"} ${ago(b.e.since)} ago${why ? " · " + why : ""}`;
    }
  } else {
    $("#pos").textContent = S.gpsErr ? "No GPS" : "Waiting for GPS";
    $("#pos-dec").textContent = S.gpsErr ? S.gpsErr + ". Type your position below to start dead reckoning." : "";
    $("#pos-src").textContent = "";
  }
  $("#spd").textContent = f.mode >= 2 && !f.stale && f.speed != null ? `${(f.speed * 1.94384).toFixed(1)} kn` : "-";
  $("#crs").textContent = f.mode >= 2 && !f.stale && f.track != null ? fmtDeg(f.track) : "-";
  $("#steps").textContent = dr.steps.count;

  // spoof alert
  const al = $("#alert");
  if (st.gps === "suspect") {
    al.classList.remove("hidden");
    $("#alert-reasons").innerHTML = st.reasons.map((r) => `<li>${esc(r)}</li>`).join("");
    $("#alert-action").textContent = st.action === "warn" ? "Warn-only mode: GPS is still being used." :
      "GPS is not used for position now; dead reckoning carries on from the last trusted fix. It is accepted again after 5 quiet minutes, if it agrees with the estimate.";
  } else al.classList.add("hidden");

  $("#ins-detail").textContent = `${st.state === "align" ? "aligning" : st.state}${st.notes.length ? " · " + st.notes.join("; ") : ""}`
    + ` · gyro offset ${st.gyroBias.map((x) => x.toFixed(2)).join(" / ")} °/s · ${st.flagsTotal} GPS alarm${st.flagsTotal === 1 ? "" : "s"}`
    + (toastGap ? " · " + toastGap : "");

  renderWaypoints(b, h);
}

// ------------------------------------------------------------------ dead reckoning controls
const MODE_HELP = {
  foot: "Each step moves the estimate one step length along the heading. Hold the phone pointing where you walk.",
  boat: "Carries on with the last good GPS speed and course, turned by every turn the gyro feels. Or type the log speed and course.",
  off: "No estimate without GPS.",
};
function renderMode() {
  const m = dr.mode;
  document.querySelectorAll("#mode-seg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
  $("#mode-help").textContent = MODE_HELP[m];
  $("#boat-box").classList.toggle("hidden", m !== "boat");
}
$("#mode-seg").addEventListener("click", (e) => { const m = e.target.dataset.mode; if (m) { dr.setMode(m); renderMode(); } });
$("#btn-boat").onclick = () => {
  const sp = parseFloat(String($("#boat-speed").value).replace(",", "."));
  const c = parseFloat($("#boat-course").value);
  if (!(sp >= 0)) return;
  dr.setMode("boat", sp, Number.isFinite(c) ? ((c % 360) + 360) % 360 : null);
  renderMode();
};
$("#btn-boat-gps").onclick = () => { dr.setMode("boat"); renderMode(); };
$("#btn-pos").onclick = () => {
  const p = parseCoords($("#pos-in").value);
  const err = $("#pos-err");
  if (!p) { err.textContent = "Couldn't read that. Try 52 22.2 N 4 53.4 E or 52.37, 4.89."; err.classList.remove("hidden"); return; }
  err.classList.add("hidden");
  S.manual = { lat: p.lat, lon: p.lon, set: now() };
  store.set("manual", S.manual);
  $("#pos-in").value = "";
  dr.tick();
};

// ------------------------------------------------------------------ INS controls
$("#btn-realign").onclick = () => { toastGap = ""; ins.realign(); };
$("#sea").onchange = (e) => { store.set("sea", e.target.checked); ins.realign(); };
$("#btn-hdg").onclick = () => {
  const v = parseFloat($("#hdg-in").value);
  if (!Number.isFinite(v)) return;
  if (ins.heading() == null && ins.state !== "align") ins.p00 = 29 ** 2;
  ins.setHeading(v);
  $("#hdg-in").value = "";
};
$("#btn-trust").onclick = () => ins.trustGps(30);

// ------------------------------------------------------------------ waypoints
function saveWps() { store.set("waypoints", S.wps); store.set("target", S.target); }
function addWp(name, lat, lon) {
  S.wps.push({ id: Date.now().toString(36), name: name || `WP ${S.wps.length + 1}`, lat, lon });
  saveWps();
}
$("#btn-wp").onclick = () => {
  const b = best();
  if (!b) return;
  addWp($("#wp-name").value.trim(), b.lat, b.lon);
  $("#wp-name").value = "";
};
$("#btn-wp-typed").onclick = () => {
  const p = parseCoords($("#wp-coords").value);
  if (!p) { $("#wp-coords").value = ""; $("#wp-coords").placeholder = "Couldn't read that, try again"; return; }
  addWp($("#wp-name").value.trim(), p.lat, p.lon);
  $("#wp-coords").value = ""; $("#wp-name").value = "";
};
$("#wps").addEventListener("click", (e) => {
  const li = e.target.closest("li"); if (!li) return;
  const id = li.dataset.id, a = e.target.dataset.a;
  if (a === "del") { S.wps = S.wps.filter((w) => w.id !== id); if (S.target === id) S.target = null; }
  else if (a === "go") S.target = S.target === id ? null : id;
  saveWps();
});
let wpKey = "";
function renderWaypoints(b, h) {
  const rows = S.wps.map((w) => {
    if (!b) return { w, txt: `${formatDM(w.lat, w.lon)}`, arrow: "" };
    const d = haversine(b.lat, b.lon, w.lat, w.lon), br = bearing(b.lat, b.lon, w.lat, w.lon);
    const rel = h != null ? wrap180(br - h) : null;
    return { w, d, br, txt: `${fmtDist(d)} · ${fmtDeg(br)}`, arrow: rel == null ? "" : `<span class="arrow" style="transform:rotate(${rel}deg)">↑</span>` };
  });
  const key = JSON.stringify(rows.map((r) => [r.w.id, r.txt, r.arrow, S.target]));
  if (key !== wpKey) {
    wpKey = key;
    $("#wps").innerHTML = rows.map((r) => `<li data-id="${r.w.id}" class="${S.target === r.w.id ? "sel" : ""}">${r.arrow}
      <div class="wp-main"><div class="wp-name">${esc(r.w.name)}</div><div class="small muted">${r.txt}</div></div>
      <button data-a="go">${S.target === r.w.id ? "Stop" : "Go to"}</button><button data-a="del">✕</button></li>`).join("")
      || `<li class="muted small">No waypoints yet.</li>`;
  }
  const t = S.wps.find((w) => w.id === S.target);
  const mark = $("#wp-mark");
  if (t && b) { mark.classList.remove("hidden"); mark.setAttribute("transform", `rotate(${bearing(b.lat, b.lon, t.lat, t.lon)})`); }
  else mark.classList.add("hidden");
}

// ------------------------------------------------------------------ settings
$("#set-decl").value = store.get("decl") ?? 0;
$("#set-decl").onchange = (e) => store.set("decl", parseFloat(String(e.target.value).replace(",", ".")) || 0);
$("#set-step").value = dr.stepLen;
$("#set-step").onchange = (e) => { const v = parseFloat(String(e.target.value).replace(",", ".")); if (v > 0.3 && v < 1.5) { dr.stepLen = v; store.set("dr_step_len", v); } };
$("#set-action").value = ins.spoofAction;
$("#set-action").onchange = (e) => { ins.spoofAction = e.target.value; store.set("action", e.target.value); };
$("#set-night").checked = !!store.get("night");
document.documentElement.dataset.night = store.get("night") ? "1" : "0";
$("#set-night").onchange = (e) => { store.set("night", e.target.checked); document.documentElement.dataset.night = e.target.checked ? "1" : "0"; };
$("#sea").checked = !!store.get("sea");
$("#start-sea").checked = !!store.get("sea");
$("#btn-clear").onclick = () => { dr.track = []; store.set("track", []); };
$("#btn-gpx").onclick = () => {
  const pts = dr.track.map(([t, la, lo]) => `<trkpt lat="${la.toFixed(6)}" lon="${lo.toFixed(6)}"><time>${new Date(t * 1000).toISOString()}</time></trkpt>`).join("\n");
  const wpts = S.wps.map((w) => `<wpt lat="${w.lat.toFixed(6)}" lon="${w.lon.toFixed(6)}"><name>${esc(w.name)}</name></wpt>`).join("\n");
  const gpx = `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Pocket INS" xmlns="http://www.topografix.com/GPX/1/1">\n${wpts}\n<trk><name>Pocket INS track</name><trkseg>\n${pts}\n</trkseg></trk>\n</gpx>\n`;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([gpx], { type: "application/gpx+xml" }));
  a.download = `pocket-ins-${new Date().toISOString().slice(0, 10)}.gpx`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
};

// ------------------------------------------------------------------ start
function showMain() {
  $("#start").classList.add("hidden");
  $("#main").classList.remove("hidden");
  renderMode();
  setInterval(render, 200);
  render();
}
$("#btn-start").onclick = async () => {
  store.set("sea", $("#start-sea").checked); $("#sea").checked = $("#start-sea").checked;
  ins.realign();
  try { await startSensors(); showMain(); }
  catch (err) { const e = $("#start-err"); e.textContent = err.message; e.classList.remove("hidden"); }
};
$("#btn-demo").onclick = () => {
  store.set("sea", $("#start-sea").checked); $("#sea").checked = $("#start-sea").checked;
  ins.realign();
  S.demo = true;
  startDemo({ onMotion, onOrientation, onPosition, ins });
  showMain();
};

if ("serviceWorker" in navigator && location.protocol !== "file:") {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
