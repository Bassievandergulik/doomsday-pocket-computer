// Inertial navigation for a phone: a JavaScript port of app/ins.py and the dead reckoning in app/deadreck.py.
//
// What a phone gyro can and cannot do: it drifts tens of degrees per hour, so acceleration is NOT
// integrated into position (that is kilometres off within minutes). It does what a MEMS gyro is good at:
//   1. ALIGN  Hold still ~30 s (at sea ~60 s, rocking is tolerated): the gyro zero offset is measured,
//             "up" comes from gravity and north from the compass, like an aircraft IRS alignment.
//   2. NAV    A gyro-stabilised heading: a small Kalman filter (heading + gyro bias) that trusts the gyro
//             short term and the compass / GPS course slowly long term.
//   3. SPOOF  Every GPS fix is cross-checked against what the sensors felt. A suspect GPS is not used
//             for position; dead reckoning carries on from the last trusted fix.
//
// Axes inside this module: x towards the top of the device, y to its left, z out of the screen.
// Units: accel in g, gyro in deg/s, headings in degrees clockwise from true north, time in seconds.
// No browser APIs here, so the same file runs in the phone and in Node tests.

export const G = 9.80665;
const RAD = Math.PI / 180;

// gyro white noise (deg/sqrt(s)) and bias random walk (deg/s/sqrt(s)), real-world values
const MODELS = {
  "ICM-42688-P": { noise: [0.01, 0.0003], pull: 0.05, blim: 0.05, dvTol: 2.0 },
  phone: { noise: [0.02, 0.001], pull: 0.15, blim: 0.2, dvTol: 3.0 },
  default: { noise: [0.05, 0.002], pull: 0.4, blim: 0.6, dvTol: 3.5 },
};

// How you travel decides how the INS aligns, how fast GPS may plausibly move, whether steps count,
// and how quickly the dead-reckoning error grows (metres: base + perDist x distance + perSec x seconds).
export const TRAVEL = {
  foot: { align: "still", maxSpeed: 60, steps: true, err: [10, 0.05, 0] },
  bike: { align: "vehicle", maxSpeed: 60, err: [30, 0.1, 0.5] },
  car: { align: "vehicle", maxSpeed: 90, err: [50, 0.15, 1.0] },
  boat: { align: "sea", maxSpeed: 60, err: [50, 0.1, 0.25] },    // current and leeway: ~0.5 kn unknown drift
  plane: { align: "vehicle", maxSpeed: 350, err: [300, 0.03, 5.0] }, // wind changes
  off: { align: "still", maxSpeed: 60, steps: true, err: [0, 0, 0] },
};
export const VEHICLES = new Set(["bike", "car", "boat", "plane"]);
// still: any movement restarts the count. sea: rocking is fine, moving seconds are skipped.
// vehicle: engine vibration and small bumps are fine, seconds with real turns or bumps are skipped.
const ALIGN = { still: [30, 0.8, 0.08, false], sea: [60, 8.0, 0.35, true], vehicle: [45, 2.0, 0.25, true] };

export const wrap180 = (d) => ((((d + 180) % 360) + 360) % 360) - 180;
const mod360 = (d) => ((d % 360) + 360) % 360;

export function circMean(angles) {
  if (!angles.length) return null;
  let s = 0, c = 0;
  for (const a of angles) { s += Math.sin(a * RAD); c += Math.cos(a * RAD); }
  return mod360(Math.atan2(s, c) / RAD);
}

const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
function norm(a) { const n = Math.sqrt(dot(a, a)) || 1; return [a[0] / n, a[1] / n, a[2] / n]; }

export function distM(lat1, lon1, lat2, lon2) {
  const dn = (lat2 - lat1) * 111320;
  const de = (lon2 - lon1) * 111320 * Math.cos(((lat1 + lat2) / 2) * RAD);
  return Math.hypot(dn, de);
}

export function bearing(lat1, lon1, lat2, lon2) {
  const p1 = lat1 * RAD, p2 = lat2 * RAD, dl = (lon2 - lon1) * RAD;
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return mod360(Math.atan2(y, x) / RAD);
}

/** Great-circle distance in metres (for waypoints far away). */
export function haversine(lat1, lon1, lat2, lon2) {
  const p1 = lat1 * RAD, p2 = lat2 * RAD, dp = (lat2 - lat1) * RAD, dl = (lon2 - lon1) * RAD;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Point dist_m metres from (lat, lon) towards bearing (flat earth, fine for short steps). */
export function move(lat, lon, distM_, bearingDeg) {
  const b = bearingDeg * RAD;
  return [lat + (distM_ * Math.cos(b)) / 111320,
    lon + (distM_ * Math.sin(b)) / (111320 * Math.max(0.01, Math.cos(lat * RAD)))];
}

// ------------------------------------------------------------------------------------------ spoof checks
export class SpoofMonitor {
  constructor({ maxSpeed = 60, holdS = 300, dvTol = 2.0 } = {}) {
    Object.assign(this, { maxSpeed, holdS, dvTol });
    this.prev = null;
    this.hist = [];
    this.suspectUntil = 0;
    this.latched = false;
    this.reasons = [];
    this.notes = [];
    this.trustUntil = 0;
    this.flagsTotal = 0;
  }

  static vel(f) {
    const sp = f.speed, tr = f.track;
    if (sp == null) return null;
    if (sp < 0.3 || tr == null) return sp < 0.3 ? [0, 0] : null;
    return [sp * Math.sin(tr * RAD), sp * Math.cos(tr * RAD)];
  }

  /** snap: {psi, dv: [E, N] m/s accumulated, amax, aligned, psiSigma}. Returns [[points, text], ...]. */
  check(t, f, snap, steps = null) {
    const tfix = f.time_local ?? t;
    const cur = { t, tfix, lat: f.lat, lon: f.lon, speed: f.speed ?? null, track: f.track ?? null,
      v: SpoofMonitor.vel(f), psi: snap.psi, dv: snap.dv, amax: snap.amax || 0, steps };
    const flags = [];
    const prev = this.prev;
    if (prev && tfix - prev.tfix >= 0.2 && tfix - prev.tfix <= 5) {
      const dt = tfix - prev.tfix;
      const d = distM(prev.lat, prev.lon, cur.lat, cur.lon);
      if (d / dt > this.maxSpeed) {
        flags.push([3, `GPS jumped ${Math.round(d)} m in ${Math.round(dt)} s`]);
      } else if (prev.v && cur.v) {
        const ve = (prev.v[0] + cur.v[0]) / 2, vn = (prev.v[1] + cur.v[1]) / 2;
        const de = (cur.lon - prev.lon) * 111320 * Math.cos(cur.lat * RAD);
        const dn = (cur.lat - prev.lat) * 111320;
        const resid = Math.hypot(de - ve * dt, dn - vn * dt);
        if (resid > 20 + 3 * dt) flags.push([2, `GPS position moved ${Math.round(resid)} m more than its own speed explains`]);
      }
    } else if (prev && tfix - prev.tfix > 5) {
      this.hist = []; // a gap: start comparing afresh
    }
    this.hist.push(cur);
    if (this.hist.length > 14) this.hist.shift();
    this.prev = cur;
    const aligned = snap.aligned;
    const at = (age, tol = 1.0) => {
      let best = null;
      for (const h of this.hist) {
        const e = Math.abs(t - h.t - age);
        if (e <= tol && (best === null || e < Math.abs(t - best.t - age))) best = h;
      }
      return best;
    };
    let old = at(3.0);
    if (aligned && old && old.v && cur.v && old.dv && cur.dv) {
      const dvg = [cur.v[0] - old.v[0], cur.v[1] - old.v[1]];
      const dvi = [cur.dv[0] - old.dv[0], cur.dv[1] - old.dv[1]];
      const resid = Math.hypot(dvg[0] - dvi[0], dvg[1] - dvi[1]);
      const felt = Math.max(cur.amax, old.amax);
      if (resid > this.dvTol + felt && Math.max(Math.hypot(...dvg), Math.hypot(...dvi)) > 2) {
        flags.push([2, `GPS speed changed ${Math.hypot(...dvg).toFixed(1)} m/s but the sensors felt ${Math.hypot(...dvi).toFixed(1)}`]);
      }
    }
    old = at(6.0, 1.5);
    if (aligned && old && cur.speed > 2 && old.speed > 2 && cur.track != null && old.track != null
        && cur.psi != null && old.psi != null) {
      const dc = wrap180(cur.track - old.track), dp = wrap180(cur.psi - old.psi);
      if (Math.abs(wrap180(dc - dp)) > 25) flags.push([2, `GPS course turned ${Math.round(dc)}° but the gyro felt ${Math.round(dp)}°`]);
    }
    if (aligned && snap.courseRef !== false && snap.psi != null && (snap.psiSigma || 99) < 20 && (cur.speed || 0) > 3 && cur.track != null
        && Math.abs(wrap180(cur.track - snap.psi)) > 70) {
      flags.push([1, `GPS course differs ${Math.round(Math.abs(wrap180(cur.track - snap.psi)))}° from the heading`]);
    }
    old = at(10.0, 1.5);
    if (steps != null && old && old.steps != null && steps - old.steps >= 15
        && this.hist.filter((h) => t - h.t <= 11).every((h) => (h.speed || 0) < 0.3)) {
      flags.push([2, `GPS says standing still but ${steps - old.steps} steps counted`]);
    }
    return flags;
  }

  /** Run check() and update the verdict. ref: [lat, lon, err_m] of the dead-reckoning estimate. */
  evaluate(t, f, snap, steps = null, ref = null) {
    const flags = this.check(t, f, snap, steps);
    const score = flags.reduce((s, [p]) => s + p, 0);
    this.notes = score < 2 ? flags.filter(([p]) => p < 2).map(([, x]) => x) : [];
    if (score >= 2 && t >= this.trustUntil) {
      this.flagsTotal += 1;
      this.reasons = flags.map(([, x]) => x);
      this.suspectUntil = t + this.holdS;
      this.latched = true;
    } else if (this.latched && t >= this.suspectUntil && score === 0) {
      // quiet for the hold time: accept GPS again only if it agrees with our own estimate
      if (!ref || distM(ref[0], ref[1], f.lat, f.lon) < Math.min(5000, Math.max(300, 2 * ref[2]))) this.latched = false;
    }
    return score >= 2;
  }

  suspect(t) { return this.latched && t >= this.trustUntil; }

  trust(t, minutes = 30) {
    this.trustUntil = t + minutes * 60;
    this.latched = false;
    this.reasons = [];
  }
}

// ------------------------------------------------------------------------------------------ alignment
class Align {
  constructor(need, rms, aTol, lenient, t0, profile) {
    Object.assign(this, { need, rms, aTol, lenient, t0, profile });
    this.block = [];
    this.blockComp = [];
    this.n = 0;
    this.sumG = [0, 0, 0];
    this.sumA = [0, 0, 0];
    this.comp = [];
    this.tBlock = null;
  }

  add(a, g) { this.block.push([a, g]); }

  closeBlock() {
    const b = this.block, bc = this.blockComp;
    this.block = [];
    this.blockComp = [];
    if (b.length < 5) return;
    const n = b.length;
    const mg = [0, 1, 2].map((i) => b.reduce((s, x) => s + x[1][i], 0) / n);
    const ma = [0, 1, 2].map((i) => b.reduce((s, x) => s + x[0][i], 0) / n);
    let ss = 0;
    for (const x of b) for (let i = 0; i < 3; i++) ss += (x[1][i] - mg[i]) ** 2;
    const rms = Math.sqrt(ss / n);
    const adev = Math.max(...b.map((x) => Math.abs(Math.sqrt(dot(x[0], x[0])) - 1)));
    if (rms < this.rms && adev < this.aTol) {
      for (let i = 0; i < 3; i++) { this.sumG[i] += mg[i]; this.sumA[i] += ma[i]; }
      this.n += 1;
      this.comp.push(...bc);
    } else if (!this.lenient) {
      this.n = 0;
      this.sumG = [0, 0, 0];
      this.sumA = [0, 0, 0];
      this.comp = [];
    }
  }

  get pct() { return Math.min(100, Math.floor((100 * this.n) / this.need)); }
  done() { return this.n >= this.need; }
  result() {
    const n = Math.max(1, this.n);
    return [this.sumG.map((x) => x / n), this.sumA.map((x) => x / n), circMean(this.comp)];
  }
}

// ------------------------------------------------------------------------------------------ the INS
export class INS {
  /**
   * opts: model ("phone", "ICM-42688-P" or "default"), getAlign() -> "still", "sea" or "vehicle"
   * (or getSea() -> true at sea), courseRef() -> true when the device points the way you travel, so the
   * GPS course may correct the heading, getSteps() -> step count,
   * getRef() -> [lat, lon, err_m] of the dead-reckoning estimate, clock() -> seconds,
   * spoofAction ("switch" = stop using a suspect GPS, "warn" = only show it), compassSigma, maxSpeed.
   */
  constructor(opts = {}) {
    const o = { model: "phone", getSea: () => false, getSteps: () => null, getRef: () => null,
      courseRef: () => true, clock: () => Date.now() / 1000, spoofAction: "switch", compassSigma: 6.0, maxSpeed: 60, ...opts };
    this.model = o.model;
    this.getAlign = o.getAlign || (() => (o.getSea() ? "sea" : "still"));
    this.courseRef = o.courseRef; this.getSteps = o.getSteps; this.getRef = o.getRef; this.clock = o.clock;
    this.spoofAction = o.spoofAction; this.compassSigma = o.compassSigma;
    const m = MODELS[o.model] || MODELS.default;
    [this.qpsi, this.qb] = m.noise;
    this.pull = m.pull;   // max degrees per reference update once the heading is known
    this.blim = m.blim;   // residual gyro bias after alignment, deg/s
    this.monitor = new SpoofMonitor({ maxSpeed: o.maxSpeed, dvTol: m.dvTol });
    this.vetKey = undefined;
    this.vetResult = false;
    this.reset(this.clock());
  }

  reset(t) {
    this.psi = null;
    this.b = 0;
    this.p00 = 180 ** 2; this.p01 = 0; this.p11 = 0.5 ** 2;
    this.u = [0, 0, 1];          // "up" in device axes
    this.bias = [0, 0, 0];       // gyro zero offset, deg/s
    this.dv = [0, 0];            // accumulated horizontal velocity change (E, N), m/s
    this.amax = 0; this.amaxRun = 0;
    this.comp = []; this.compT = null;
    this.degraded = false;
    this.rate = 0; this.tilt = 0;
    this.lastT = null;
    const profile = ALIGN[this.getAlign()] ? this.getAlign() : "still";
    const [need, rms, aTol, lenient] = ALIGN[profile];
    this.align = new Align(need, rms, aTol, lenient, t, profile);
    this.state = "align";
  }

  realign() { this.reset(this.clock()); }

  /** Steering-compass heading typed in by hand becomes the reference. */
  setHeading(deg) {
    if (this.state === "nav" || this.state === "nav-degraded") { this.psi = mod360(deg); this.p00 = 3 ** 2; }
  }

  /** Fastest plausible GPS movement in m/s (an airliner is ~250 m/s). */
  setMaxSpeed(v) { this.monitor.maxSpeed = v; }

  trustGps(minutes = 30) { this.monitor.trust(this.clock(), minutes); this.vetKey = undefined; }

  /** Gyro-stabilised true heading, or null when not aligned or still unsure. */
  heading() {
    if ((this.state === "nav" || this.state === "nav-degraded") && this.psi != null && this.p00 < 30 ** 2) {
      return Math.round(this.psi * 10) / 10;
    }
    return null;
  }

  /** One IMU sample in module axes (g, deg/s). */
  feed(t, a, g) {
    if (this.state === "align") { this.feedAlign(t, a, g); return; }
    if (this.lastT === null) { this.lastT = t; return; }
    const dt = t - this.lastT;
    this.lastT = t;
    if (dt <= 0 || dt > 0.5) return;
    const w = [0, 1, 2].map((i) => (g[i] - this.bias[i]) * RAD);
    const am = Math.sqrt(dot(a, a));
    const ah = am > 0.3 ? norm(a) : this.u;
    const wt = Math.max(0, 1 - Math.abs(am - 1) / 0.4);      // trust gravity only near 1 g
    const e = cross(this.u, ah);
    const kp = 0.02 * wt, ki = 0.0002 * wt;                 // gentle: a steady push must not look like tilt
    const wc = [0, 1, 2].map((i) => w[i] - kp * e[i]);
    const d = cross(wc, this.u);
    this.u = norm([this.u[0] - d[0] * dt, this.u[1] - d[1] * dt, this.u[2] - d[2] * dt]);
    if (wt > 0) for (let i = 0; i < 3; i++) this.bias[i] += (ki * e[i] * dt) / RAD;
    this.tilt = Math.acos(Math.max(-1, Math.min(1, this.u[2]))) / RAD;
    // rotation about the true vertical (counter-clockwise positive) makes the heading fall
    const rate = -dot(w, this.u) / RAD;
    this.rate = rate;
    this.predict(rate, dt);
    if (this.psi != null) {
      let lin = [a[0] - this.u[0], a[1] - this.u[1], a[2] - this.u[2]];
      const vert = dot(lin, this.u);
      lin = [lin[0] - vert * this.u[0], lin[1] - vert * this.u[1], lin[2] - vert * this.u[2]];
      const fwd = norm([1 - this.u[0] * this.u[0], -this.u[0] * this.u[1], -this.u[0] * this.u[2]]);
      const left = cross(this.u, fwd);
      const af = dot(lin, fwd) * G, al = dot(lin, left) * G;
      const s = Math.sin(this.psi * RAD), c = Math.cos(this.psi * RAD);
      const ae = af * s - al * c, an = af * c + al * s;
      this.dv[0] += ae * dt;
      this.dv[1] += an * dt;
      this.amaxRun = Math.max(this.amaxRun, Math.hypot(ae, an));
    }
  }

  predict(rate, dt) {
    if (this.psi == null) return;
    this.psi = mod360(this.psi + (rate - this.b) * dt);
    const { p00, p01, p11 } = this;
    this.p00 = p00 - 2 * dt * p01 + dt * dt * p11 + this.qpsi ** 2 * dt;
    this.p01 = p01 - dt * p11;
    this.p11 = p11 + this.qb ** 2 * dt;
  }

  update(z, sigma, gate = null) {
    if (this.psi == null) { this.psi = mod360(z); this.p00 = sigma ** 2; return true; }
    const y = wrap180(z - this.psi);
    if (gate != null && Math.abs(y) > gate && this.p00 < 30 ** 2) return false;
    const s = this.p00 + sigma ** 2;
    const k0 = this.p00 / s, k1 = this.p01 / s;
    let mv = k0 * y;
    if (this.p00 < 30 ** 2) mv = Math.max(-this.pull, Math.min(this.pull, mv)); // references only nudge
    this.psi = mod360(this.psi + mv);
    this.b = Math.max(-this.blim, Math.min(this.blim, this.b + k1 * y));
    this.p11 -= k1 * this.p01;
    this.p01 *= 1 - k0;
    this.p00 *= 1 - k0;
    return true;
  }

  /** Compass sample (true heading). Ignored when tilted or turning fast; averaged to one update a second. */
  feedCompass(t, heading) {
    if (heading == null || Number.isNaN(heading)) return;
    if (this.state === "align") { this.align.blockComp.push(heading); return; }
    if (this.tilt < 25 && Math.abs(this.rate) < 60) {
      this.comp.push(heading);
      if (this.compT === null) this.compT = t;
      if (t - this.compT >= 1) {
        const z = circMean(this.comp);
        this.comp = []; this.compT = t;
        this.update(z, this.compassSigma, 30);
      }
    }
  }

  feedAlign(t, a, g) {
    const al = this.align;
    if (this.lastT === null) { this.lastT = t; al.tBlock = t; }
    al.add(a, g);
    if (t - al.tBlock >= 1) {
      al.tBlock = t;
      al.closeBlock();
      if (al.done()) this.finishAlign(t);
      else if (t - al.t0 > (al.lenient ? 240 : 150)) this.finishAlign(t, true);
    }
  }

  finishAlign(t, degraded = false) {
    const al = this.align;
    const [g, a, comp] = al.result();
    if (al.n >= 1) { this.bias = g.slice(); this.u = norm(a); }
    this.degraded = degraded || al.n < al.need;
    this.lastT = t;
    this.psi = null;
    this.p00 = 180 ** 2;
    this.b = 0; this.p01 = 0; this.p11 = (this.blim * (this.degraded ? 2 : 0.2)) ** 2;
    if (comp != null) { this.psi = comp; this.p00 = this.compassSigma ** 2; }
    this.state = this.degraded ? "nav-degraded" : "nav";
    this.alignDone = al;
    this.align = null;
  }

  snapshot() {
    return { psi: this.psi, dv: [this.dv[0], this.dv[1]], amax: this.amax,
      aligned: (this.state === "nav" || this.state === "nav-degraded") && this.psi != null,
      psiSigma: Math.sqrt(Math.max(this.p00, 0)) };
  }

  /** True if this GPS fix may be used for position. Evaluated once per new fix. */
  vet(f) {
    if (!f || (f.mode || 0) < 2 || f.lat == null || f.stale) return true;
    const key = f.time_local;
    if (key === this.vetKey) return this.vetResult;
    this.vetKey = key;
    const t = this.clock();
    this.amax = this.amaxRun; this.amaxRun = 0;
    this.monitor.evaluate(t, f, { ...this.snapshot(), courseRef: this.courseRef() }, this.getSteps(), this.getRef());
    this.vetResult = !(this.spoofAction === "switch" && this.monitor.suspect(t));
    if (this.vetResult && this.courseRef() && (this.state === "nav" || this.state === "nav-degraded") && !this.monitor.suspect(t)) {
      const sp = f.speed, tr = f.track;
      if (sp != null && tr != null && sp > 1.5 && (f.hdop || 1) < 3) this.update(tr, 12 + 20 / sp, 60);
    }
    return this.vetResult;
  }

  status() {
    const t = this.clock(), m = this.monitor;
    const gps = m.suspect(t) ? "suspect" : t < m.trustUntil ? "trusted-by-hand" : "ok";
    return { model: this.model, state: this.state, alignPct: this.align ? this.align.pct : 100,
      alignProfile: this.align ? this.align.profile : null, degraded: this.degraded, heading: this.heading(),
      headingSigma: this.psi != null ? Math.round(Math.sqrt(Math.max(this.p00, 0)) * 10) / 10 : null,
      gyroBias: this.bias.map((x) => Math.round(x * 1000) / 1000), tilt: Math.round(this.tilt * 10) / 10,
      turnDps: Math.round(this.rate * 100) / 100, gps, reasons: gps === "suspect" ? m.reasons.slice() : [],
      notes: m.notes.slice(), flagsTotal: m.flagsTotal, action: this.spoofAction };
  }
}

// ------------------------------------------------------------------------------------------ steps
/** A step is a rise above ~1.12 g then a fall below ~0.95 g, at least 0.28 s after the last one. */
export class StepDetector {
  constructor(high = 1.12, low = 0.95, minGap = 0.28) {
    Object.assign(this, { high, low, minGap });
    this.armed = false; this.lastStep = 0; this.smooth = 1; this.count = 0;
  }

  feed(t, ax, ay, az) {
    const m = Math.sqrt(ax * ax + ay * ay + az * az);
    this.smooth += 0.35 * (m - this.smooth);
    if (!this.armed && this.smooth > this.high) this.armed = true;
    else if (this.armed && this.smooth < this.low) {
      this.armed = false;
      if (t - this.lastStep >= this.minGap) { this.lastStep = t; this.count += 1; return true; }
    }
    return false;
  }
}

// ------------------------------------------------------------------------------------------ dead reckoning
/**
 * On foot: each step moves the estimate one step length along the heading (step length learns from GPS).
 * By bike, car, boat or plane: the estimate carries on with the last trusted GPS speed and course, or one you type in,
 * and the gyro rotates that course by every turn felt since.
 * store: {get(key), set(key, value)} for settings that should survive a restart.
 */
export class DeadReckoner {
  constructor({ getFix, getHeading, getManual = () => null, store, ins = null, clock = () => Date.now() / 1000 }) {
    Object.assign(this, { getFix, getHeading, getManual, store, ins, clock });
    this.steps = new StepDetector();
    this.stepLen = store.get("dr_step_len") || 0.72;
    this.anchor = null;      // {lat, lon, t, source}
    this.pos = null;
    this.dist = 0;
    this.lastGood = null;    // [t, lat, lon, speed, course]
    this.refHeading = null;
    this.cal = null;
    this.lastT = clock();
    this.track = [];
  }

  get mode() { return this.store.get("dr_mode") || "foot"; }

  setMode(mode, speedKn = null, course = null) {
    if (!TRAVEL[mode]) throw new Error("mode must be one of " + Object.keys(TRAVEL).join(", "));
    this.store.set("dr_mode", mode);
    if (VEHICLES.has(mode)) {
      this.store.set("dr_vehicle", speedKn != null
        ? { speed_kn: speedKn, course, ref_heading: this.insHeading(), set: this.clock() } : null);
    }
  }

  insHeading() { return this.ins ? this.ins.heading() : null; }

  fixOk(f) {
    return !!f && (f.mode || 0) >= 2 && f.lat != null && !f.stale && (f.hdop == null || f.hdop < 5)
      && (!this.ins || this.ins.vet(f));
  }

  /** Once a second: follow GPS while it has a trusted fix, otherwise extrapolate in a vehicle or boat.
   * Only turns felt since the last fix are used, so the phone may sit in any fixed position. */
  tick(t = this.clock()) {
    const dt = t - this.lastT;
    this.lastT = t;
    const f = this.getFix();
    if (this.fixOk(f)) {
      this.lastGood = [t, f.lat, f.lon, f.speed || 0, f.track ?? null];
      this.refHeading = this.insHeading();
      this.anchor = { lat: f.lat, lon: f.lon, t, source: "gps" };
      this.pos = [f.lat, f.lon];
      this.dist = 0;
      this.learnStep(f);
      this.log(t);
      return;
    }
    this.cal = null;
    const m = this.getManual();
    if (m && (!this.anchor || (m.set || 0) > this.anchor.t)) {
      this.anchor = { lat: m.lat, lon: m.lon, t: m.set || t, source: "manual" };
      this.pos = [m.lat, m.lon];
      this.dist = 0;
    }
    if (!this.pos || !VEHICLES.has(this.mode) || dt <= 0 || dt > 30) return;
    const boat = this.store.get("dr_vehicle") || {};
    let speed, course, ref;
    if (boat.speed_kn != null) [speed, course, ref] = [boat.speed_kn * 0.514444, boat.course, boat.ref_heading];
    else if (this.lastGood) [speed, course, ref] = [this.lastGood[3], this.lastGood[4], this.refHeading];
    else return;
    const now = this.insHeading();
    if (course != null && ref != null && now != null) course = mod360(course + wrap180(now - ref));
    if (course == null) course = this.getHeading();
    if (course == null || speed < 0.05) return;
    this.pos = move(this.pos[0], this.pos[1], speed * dt, course);
    this.dist += speed * dt;
    this.log(t);
  }

  onStep(t = this.clock()) {
    if (this.mode !== "foot" || !this.pos || !this.anchor) return;
    if (this.anchor.source === "gps" && this.fixOk(this.getFix())) return;
    const h = this.getHeading();
    if (h == null) return;
    this.pos = move(this.pos[0], this.pos[1], this.stepLen, h);
    this.dist += this.stepLen;
    this.log(t);
  }

  learnStep(f) {
    if (this.mode !== "foot" || (f.hdop || 1) > 2.5) return;
    if (!this.cal) { this.cal = [this.steps.count, f.lat, f.lon]; return; }
    const n = this.steps.count - this.cal[0];
    if (n < 100) return;
    const d = distM(this.cal[1], this.cal[2], f.lat, f.lon);
    if (d > 60) {
      const sl = d / n;  // straight line, so it can only underestimate on winding paths: be gentle
      if (sl > 0.4 && sl < 1.1) {
        this.stepLen = Math.round((0.8 * this.stepLen + 0.2 * sl) * 1000) / 1000;
        this.store.set("dr_step_len", this.stepLen);
      }
    }
    this.cal = [this.steps.count, f.lat, f.lon];
  }

  log(t) {
    const last = this.track[this.track.length - 1];
    if (!last || t - last[0] > 15) {
      this.track.push([t, this.pos[0], this.pos[1]]);
      if (this.track.length > 5000) this.track.splice(0, this.track.length - 5000);
    }
  }

  /** The estimate while GPS is missing or distrusted, or null if GPS is fine or there is nothing to go on. */
  estimate() {
    if (!this.pos || !this.anchor || this.mode === "off") return null;
    if (this.anchor.source === "gps" && this.dist === 0 && this.fixOk(this.getFix())) return null;
    const age = this.clock() - this.anchor.t;
    const [e0, ed, et] = TRAVEL[this.mode].err;
    let err = e0 + ed * this.dist + et * age;
    if (this.anchor.source === "manual") err += 100;
    return { lat: this.pos[0], lon: this.pos[1], err_m: Math.round(err), mode: this.mode,
      dist_m: Math.round(this.dist), since: this.anchor.t, from: this.anchor.source,
      step_len: this.stepLen, steps: this.steps.count };
  }
}
