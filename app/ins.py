"""Inertial navigation (INS) in the style of an aircraft IRS, scaled down to a MEMS chip.

What a MEMS gyro can and cannot do: an airliner's ring-laser gyros drift ~0.01 deg/h; the ICM-42688-P
drifts roughly 10-50 deg/h and the MPU-6050 far more. So this does NOT integrate acceleration into
position (that would be kilometres off within minutes). It does what a MEMS gyro is good at:

  1. ALIGN   Hold still ~30 s (on a boat: ~60 s, rocking is tolerated). The gyro zero-offset is measured,
             "up" is taken from gravity and north from the compass, like an IRS alignment.
  2. NAV     A gyro-stabilised heading: a small Kalman filter (heading + gyro bias) that trusts the gyro
             in the short term and the compass / GPS course slowly in the long term. A rolling boat or a
             magnet nearby barely moves it. Turns are tracked even with no GPS and a swinging compass.
  3. SPOOF   Every GPS fix is cross-checked against what the sensors felt: sudden position jumps,
             speed changes with no push on the accelerometer, a course change the gyro did not feel,
             steps counted while GPS says you stand still. A suspect GPS is not used for position; the
             dead-reckoning estimate (deadreck.py) carries on from the last trusted fix.

Limits (be honest): a slow drag of the GPS position at a steady speed feels like normal motion and is not
caught until it exceeds the dead-reckoning error. Position still comes from speed x heading; no affordable
sensor measures speed through the water or the current.

Axes: mount the chip flat, screen up, chip X axis towards the top of the device (or set ins_mount).
Units: accel in g, gyro in deg/s, headings in degrees clockwise from true north.
"""
import math
import threading
import time
from collections import deque

G = 9.80665
RAD = math.pi / 180.0

# gyro white noise (deg/sqrt(s)) and bias random walk (deg/s/sqrt(s)): real-world, not data-sheet, values
NOISE = {"ICM-42688-P": (0.01, 0.0003), "default": (0.05, 0.002)}


def wrap180(d):
    return (d + 180.0) % 360.0 - 180.0


def circ_mean(angles):
    if not angles:
        return None
    s = sum(math.sin(a * RAD) for a in angles)
    c = sum(math.cos(a * RAD) for a in angles)
    return math.degrees(math.atan2(s, c)) % 360.0


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _dist_m(lat1, lon1, lat2, lon2):
    dn = (lat2 - lat1) * 111320.0
    de = (lon2 - lon1) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dn, de)


class SpoofMonitor:
    """Cross-checks GPS fixes against the inertial sensors. One call to check() per new fix."""

    def __init__(self, max_speed=60.0, hold_s=300.0, dv_tol=2.0):
        self.max_speed, self.hold_s, self.dv_tol = max_speed, hold_s, dv_tol
        self.course_vs_heading = True   # off in vehicles: the device need not point where you travel
        self.prev = None
        self.hist = deque(maxlen=40)
        self.suspect_until = 0.0
        self.latched = False
        self.reasons = []
        self.notes = []
        self.trust_until = 0.0
        self.flags_total = 0

    @staticmethod
    def _vel(f):
        sp, tr = f.get("speed"), f.get("track")
        if sp is None:
            return None
        if sp < 0.3 or tr is None:
            return (0.0, 0.0) if sp < 0.3 else None
        return (sp * math.sin(tr * RAD), sp * math.cos(tr * RAD))

    def check(self, t, f, snap, steps=None):
        """snap: {"psi", "dv": (E, N) m/s accumulated, "amax", "aligned", "psi_sigma"}.
        Returns the list of (points, text) raised by this fix."""
        tfix = f.get("time_local") or t
        cur = {"t": t, "tfix": tfix, "lat": f["lat"], "lon": f["lon"], "speed": f.get("speed"),
               "track": f.get("track"), "v": self._vel(f), "psi": snap.get("psi"), "dv": snap.get("dv"),
               "amax": snap.get("amax", 0.0), "steps": steps}
        flags = []
        prev = self.prev
        if prev is not None and 0.2 <= tfix - prev["tfix"] <= 5.0:
            dt = tfix - prev["tfix"]
            d = _dist_m(prev["lat"], prev["lon"], cur["lat"], cur["lon"])
            if d / dt > self.max_speed:
                flags.append((3, "GPS jumped %d m in %.0f s" % (d, dt)))
            elif prev["v"] is not None and cur["v"] is not None:
                ve = (prev["v"][0] + cur["v"][0]) / 2
                vn = (prev["v"][1] + cur["v"][1]) / 2
                de = (cur["lon"] - prev["lon"]) * 111320.0 * math.cos(math.radians(cur["lat"]))
                dn = (cur["lat"] - prev["lat"]) * 111320.0
                resid = math.hypot(de - ve * dt, dn - vn * dt)
                if resid > 20.0 + 3.0 * dt + 0.1 * math.hypot(ve, vn) * dt:  # fast: allow for receiver lag
                    flags.append((2, "GPS position moved %d m more than its own speed explains" % resid))
        elif prev is not None and tfix - prev["tfix"] > 5.0:
            self.hist.clear()  # a gap (no fix for a while): start comparing afresh
        self.hist.append(cur)
        self.prev = cur
        aligned = snap.get("aligned")

        def at(age, tol=1.0):
            best = None
            for h in self.hist:
                if abs((t - h["t"]) - age) <= tol and (best is None or abs((t - h["t"]) - age) < abs((t - best["t"]) - age)):
                    best = h
            return best

        old = at(3.0)
        if aligned and old is not None and old["v"] and cur["v"] and old["dv"] and cur["dv"]:
            dvg = (cur["v"][0] - old["v"][0], cur["v"][1] - old["v"][1])
            dvi = (cur["dv"][0] - old["dv"][0], cur["dv"][1] - old["dv"][1])
            # a small tilt error (e.g. after a long push or a banked turn) leaks gravity into the sensed
            # acceleration as a slow, steady drift: remove the drift seen over the previous half minute
            base = at(33.0, 3.0)
            if base is not None and base["v"] and base["dv"] and old["t"] - base["t"] > 10:
                span = old["t"] - base["t"]
                k = (cur["t"] - old["t"]) / span
                for i in range(2):
                    leak = ((old["dv"][i] - base["dv"][i]) - (old["v"][i] - base["v"][i])) * k
                    dvi = (dvi[0] - leak, dvi[1]) if i == 0 else (dvi[0], dvi[1] - leak)
            resid = math.hypot(dvg[0] - dvi[0], dvg[1] - dvi[1])
            felt = max(cur["amax"], old["amax"])
            if resid > self.dv_tol + felt and max(math.hypot(*dvg), math.hypot(*dvi)) > 2.0:
                flags.append((2, "GPS speed changed %.1f m/s but the sensors felt %.1f"
                              % (math.hypot(*dvg), math.hypot(*dvi))))
        old = at(6.0, 1.5)
        if aligned and old is not None and cur["speed"] and old["speed"] and cur["speed"] > 2 and old["speed"] > 2 \
                and cur["track"] is not None and old["track"] is not None \
                and cur["psi"] is not None and old["psi"] is not None:
            dc = wrap180(cur["track"] - old["track"])
            dp = wrap180(cur["psi"] - old["psi"])
            if abs(wrap180(dc - dp)) > 25.0:
                flags.append((2, "GPS course turned %d deg but the gyro felt %d deg" % (round(dc), round(dp))))
        if self.course_vs_heading and aligned and snap.get("psi") is not None and (snap.get("psi_sigma") or 99) < 20 and (cur["speed"] or 0) > 3 \
                and cur["track"] is not None and abs(wrap180(cur["track"] - snap["psi"])) > 70:
            flags.append((1, "GPS course differs %d deg from the heading" % abs(wrap180(cur["track"] - snap["psi"]))))
        old = at(10.0, 1.5)
        if steps is not None and old is not None and old["steps"] is not None and steps - old["steps"] >= 15 \
                and all((h["speed"] or 0) < 0.3 for h in self.hist if t - h["t"] <= 11):
            flags.append((2, "GPS says standing still but %d steps counted" % (steps - old["steps"])))
        return flags

    def evaluate(self, t, f, snap, steps=None, ref=None):
        """Run check() and update the verdict. ref: (lat, lon, err_m) of the dead-reckoning estimate."""
        flags = self.check(t, f, snap, steps)
        score = sum(p for p, _ in flags)
        self.notes = [x for p, x in flags if p < 2] if score < 2 else []
        if score >= 2 and t >= self.trust_until:
            self.flags_total += 1
            self.reasons = [x for _, x in flags]
            self.suspect_until = t + self.hold_s
            self.latched = True
        elif self.latched and t >= self.suspect_until and score == 0:
            # quiet for the hold time: accept GPS again only if it agrees with our own estimate
            if ref is None or _dist_m(ref[0], ref[1], f["lat"], f["lon"]) < min(5000.0, max(300.0, 2.0 * ref[2])):
                self.latched = False
        return score >= 2

    def suspect(self, t):
        return self.latched and t >= self.trust_until

    def trust(self, t, minutes=30):
        self.trust_until = t + minutes * 60.0
        self.latched = False
        self.reasons = []


class _Align:
    """Collects still seconds. Land: any movement restarts. Sea: moving seconds are skipped."""

    def __init__(self, need, rms_dps, a_tol, sea, t0):
        self.need, self.rms, self.a_tol, self.sea, self.t0 = need, rms_dps, a_tol, sea, t0
        self.block = []
        self.n = 0
        self.sum_g = [0.0, 0.0, 0.0]
        self.sum_a = [0.0, 0.0, 0.0]
        self.comp = []
        self.block_comp = []

    def add(self, a, g, comp):
        self.block.append((a, g))
        if comp is not None:
            self.block_comp.append(comp)

    def close_block(self):
        b, bc = self.block, self.block_comp
        self.block, self.block_comp = [], []
        if len(b) < 5:
            return
        n = len(b)
        mg = [sum(s[1][i] for s in b) / n for i in range(3)]
        ma = [sum(s[0][i] for s in b) / n for i in range(3)]
        rms = math.sqrt(sum((s[1][i] - mg[i]) ** 2 for s in b for i in range(3)) / n)
        adev = max(abs(math.sqrt(_dot(s[0], s[0])) - 1.0) for s in b)
        if rms < self.rms and adev < self.a_tol:
            for i in range(3):
                self.sum_g[i] += mg[i]
                self.sum_a[i] += ma[i]
            self.n += 1
            self.comp.extend(bc)
        elif not self.sea:
            self.n = 0
            self.sum_g, self.sum_a, self.comp = [0.0] * 3, [0.0] * 3, []

    @property
    def pct(self):
        return min(100, int(100 * self.n / self.need))

    def done(self):
        return self.n >= self.need

    def result(self):
        n = max(1, self.n)
        return [x / n for x in self.sum_g], [x / n for x in self.sum_a], circ_mean(self.comp)


class INS:
    def __init__(self, imu, get_compass, get_fix, settings, get_sea=lambda: False, get_steps=lambda: None,
                 get_ref=lambda: None, mount=("x", "y", "z"), rate_hz=50, spoof_action="switch",
                 compass_sigma=6.0, max_speed=60.0, get_vehicle=lambda: False):
        """imu: deadreck.IMU (or None); get_compass() -> true heading deg or None; get_fix() -> GPS dict;
        settings: (get, set) callables; get_sea() -> True on a boat; get_steps() -> step count or None;
        get_ref() -> (lat, lon, err_m) of the dead-reckoning estimate or None."""
        self.clock = time.time  # tests replace it with a simulated clock
        self.imu, self.get_compass, self.get_fix = imu, get_compass, get_fix
        self.get_sea, self.get_steps, self.get_ref = get_sea, get_steps, get_ref
        # get_vehicle() -> True in a car, plane or on a bike: the device may sit at any angle to the direction
        # of travel, so GPS course says nothing about where the device points, and planes are fast
        self.get_vehicle, self.max_speed = get_vehicle, max_speed
        self.rate_hz, self.spoof_action, self.compass_sigma = rate_hz, spoof_action, compass_sigma
        self.mount = self._mount(mount)
        self.model = getattr(imu, "model", None) if imu is not None and imu.available else None
        self.qpsi, self.qb = NOISE.get(self.model, NOISE["default"])
        self.pull = 0.05 if self.model == "ICM-42688-P" else 0.4     # max deg per reference update
        self.blim = 0.05 if self.model == "ICM-42688-P" else 0.6   # residual bias after alignment, deg/s
        self.lock = threading.RLock()
        self.monitor = SpoofMonitor(max_speed=max_speed, dv_tol=2.0 if self.model == "ICM-42688-P" else 3.5)
        self._vet_key = None
        self._vet_result = False
        self.state = "none" if self.model is None else "align"
        self._reset(self.clock())

    @staticmethod
    def _mount(m):
        idx = {"x": 0, "y": 1, "z": 2}
        out = []
        for s in m:
            s = str(s).lower()
            out.append((idx[s.lstrip("-")], -1.0 if s.startswith("-") else 1.0))
        return out

    def _remap(self, v):
        return tuple(v[i] * sg for i, sg in self.mount)

    def _reset(self, t):
        self.psi = None
        self.b = 0.0
        self.p00, self.p01, self.p11 = 180.0 ** 2, 0.0, 0.5 ** 2
        self.u = (0.0, 0.0, 1.0)            # gravity ("up") direction in device axes
        self.bias = [0.0, 0.0, 0.0]         # gyro zero offset, deg/s
        self.dv = [0.0, 0.0]                # accumulated horizontal velocity change, m/s
        self.amax = 0.0
        self._amax_run = 0.0
        self._comp, self._comp_t = [], None
        self.degraded = False
        self.rate = 0.0
        self.tilt = 0.0
        self.n = 0
        self.last_t = None
        sea = bool(self.get_sea())
        self.align = _Align(60 if sea else 30, 8.0 if sea else 0.8, 0.35 if sea else 0.08, sea, t) \
            if self.model else None
        self.state = "align" if self.model else "none"
        self._last_gps_use = 0.0

    # ----------------------------------------------------------------- public controls
    def realign(self):
        with self.lock:
            self._reset(self.clock())

    def set_heading(self, deg):
        """Steering-compass heading typed in by hand: becomes the reference."""
        with self.lock:
            if self.state in ("nav", "nav-degraded"):
                self.psi = deg % 360.0
                self.p00 = 3.0 ** 2

    def trust_gps(self, minutes=30):
        with self.lock:
            self.monitor.trust(self.clock(), minutes)
            self._vet_key = None

    def heading(self):
        """Gyro-stabilised true heading, or None when not aligned or still unsure."""
        with self.lock:
            if self.state in ("nav", "nav-degraded") and self.psi is not None and self.p00 < 30.0 ** 2:
                return round(self.psi, 1)
        return None

    # ----------------------------------------------------------------- the filter
    def feed(self, t, accel, gyro):
        """One IMU sample in device axes (g, deg/s)."""
        with self.lock:
            a, g = self._remap(accel), self._remap(gyro)
            if self.state == "align":
                self._feed_align(t, a, g)
                return
            if self.state == "none" or self.last_t is None:
                self.last_t = t
                return
            dt = t - self.last_t
            self.last_t = t
            if dt <= 0 or dt > 0.5:
                return
            self.n += 1
            w = [(g[i] - self.bias[i]) * RAD for i in range(3)]
            am = math.sqrt(_dot(a, a))
            ah = _norm(a) if am > 0.3 else self.u
            wt = max(0.0, 1.0 - abs(am - 1.0) / 0.4)          # trust gravity only when ~1 g
            e = _cross(self.u, ah)
            kp, ki = 0.02 * wt, 0.0002 * wt   # gentle: a steady push or turn must not be mistaken for tilt
            wc = tuple(w[i] - kp * e[i] for i in range(3))
            d = _cross(wc, self.u)
            self.u = _norm((self.u[0] - d[0] * dt, self.u[1] - d[1] * dt, self.u[2] - d[2] * dt))
            if wt > 0:  # slow gyro-bias learning on the axes gravity can see (the vertical one is the Kalman's)
                for i in range(3):
                    self.bias[i] += ki * e[i] * dt / RAD
            self.tilt = math.degrees(math.acos(max(-1.0, min(1.0, self.u[2]))))
            # heading rate: rotation about the true vertical (counter-clockwise positive) -> heading falls
            rate = -math.degrees(_dot(w, self.u))
            self.rate = rate
            self._predict(rate, dt)
            # horizontal acceleration -> velocity change (only ever used as a short-window difference)
            if self.psi is not None:
                lin = (a[0] - self.u[0], a[1] - self.u[1], a[2] - self.u[2])
                vert = _dot(lin, self.u)
                lin = (lin[0] - vert * self.u[0], lin[1] - vert * self.u[1], lin[2] - vert * self.u[2])
                fwd = _norm((1 - self.u[0] * self.u[0], -self.u[0] * self.u[1], -self.u[0] * self.u[2]))
                left = _cross(self.u, fwd)
                af, al = _dot(lin, fwd) * G, _dot(lin, left) * G
                s, c = math.sin(self.psi * RAD), math.cos(self.psi * RAD)
                ae, an = af * s - al * c, af * c + al * s
                self.dv[0] += ae * dt
                self.dv[1] += an * dt
                self._amax_run = max(self._amax_run, math.hypot(ae, an))

    def _predict(self, rate, dt):
        if self.psi is None:
            return
        self.psi = (self.psi + (rate - self.b) * dt) % 360.0
        p00, p01, p11 = self.p00, self.p01, self.p11
        self.p00 = p00 - 2 * dt * p01 + dt * dt * p11 + self.qpsi ** 2 * dt
        self.p01 = p01 - dt * p11
        self.p11 = p11 + self.qb ** 2 * dt

    def _update(self, z, sigma, gate=None):
        if self.psi is None:
            self.psi, self.p00 = z % 360.0, sigma ** 2
            return True
        y = wrap180(z - self.psi)
        if gate is not None and abs(y) > gate and self.p00 < 30.0 ** 2:
            return False
        s = self.p00 + sigma ** 2
        k0, k1 = self.p00 / s, self.p01 / s
        move = k0 * y
        if self.p00 < 30.0 ** 2:  # sure of the heading: references (compass, GPS course) may only nudge it
            move = max(-self.pull, min(self.pull, move))
        self.psi = (self.psi + move) % 360.0
        self.b = max(-self.blim, min(self.blim, self.b + k1 * y))   # a biased compass must not pose as gyro drift
        self.p11 -= k1 * self.p01
        self.p01 *= (1 - k0)
        self.p00 *= (1 - k0)
        return True

    def feed_compass(self, t, heading):
        """Compass sample (true heading). Ignored when the device is tilted or turning fast."""
        with self.lock:
            if heading is None:
                return
            if self.state == "align":
                if self.align is not None:
                    self.align.block_comp.append(heading)
                return
            if self.state in ("nav", "nav-degraded") and self.tilt < 25.0 and abs(self.rate) < 60.0:
                # one averaged update per second: compass errors (iron, magnets) are not white noise,
                # so the filter must not count every 5 Hz sample as fresh evidence
                self._comp.append(heading)
                if self._comp_t is None:
                    self._comp_t = t
                if t - self._comp_t >= 1.0:
                    z = circ_mean(self._comp)
                    self._comp, self._comp_t = [], t
                    self._update(z, self.compass_sigma, gate=30.0)

    def _feed_align(self, t, a, g):
        al = self.align
        if self.last_t is None:
            self.last_t = t
            al.t_block = t
        al.add(a, g, None)
        if t - al.t_block >= 1.0:
            al.t_block = t
            al.close_block()
            if al.done():
                self._finish_align(t)
            elif t - al.t0 > (240 if al.sea else 150):
                self._finish_align(t, degraded=True)

    def _finish_align(self, t, degraded=False):
        al = self.align
        g, a, comp = al.result()
        if al.n >= 1:
            self.bias = list(g)
            self.u = _norm(tuple(a))
        self.degraded = degraded or al.n < al.need
        self.last_t = t
        self.psi = None
        self.p00 = 180.0 ** 2
        self.b, self.p01, self.p11 = 0.0, 0.0, (self.blim * (2.0 if self.degraded else 0.2)) ** 2  # measured at rest -> small
        if comp is not None:
            self.psi, self.p00 = comp, self.compass_sigma ** 2
        self.state = "nav-degraded" if self.degraded else "nav"
        self.align = None

    # ----------------------------------------------------------------- GPS vetting
    def _snapshot(self):
        return {"psi": self.psi, "dv": (self.dv[0], self.dv[1]), "amax": self.amax,
                "aligned": self.state in ("nav", "nav-degraded") and self.psi is not None,
                "psi_sigma": math.sqrt(max(self.p00, 0.0))}

    def vet(self, f=None):
        """True if this GPS fix may be used for position. Evaluated once per new fix."""
        f = f or self.get_fix()
        if f.get("mode", 0) < 2 or f.get("lat") is None or f.get("stale"):
            return True
        key = f.get("time_local")
        with self.lock:
            if key == self._vet_key:
                return self._vet_result
            self._vet_key = key
            t = self.clock()
            self.amax, self._amax_run = self._amax_run, 0.0
            vehicle = bool(self.get_vehicle())
            self.monitor.max_speed = max(self.max_speed, 320.0) if vehicle else self.max_speed  # airliner ~250 m/s
            self.monitor.course_vs_heading = not vehicle
            self.monitor.evaluate(t, f, self._snapshot(), self.get_steps(), self.get_ref())
            self._vet_result = not (self.spoof_action == "switch" and self.monitor.suspect(t))
            if self._vet_result and not vehicle and self.state in ("nav", "nav-degraded") and not self.monitor.suspect(t):
                sp, tr = f.get("speed"), f.get("track")
                if sp is not None and tr is not None and sp > 1.5 and (f.get("hdop") or 1.0) < 3.0:
                    self._update(tr, 12.0 + 20.0 / sp, gate=60.0)
            return self._vet_result

    def gps_trusted(self, f=None):
        return self.vet(f)

    # ----------------------------------------------------------------- thread and status
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        period = 1.0 / self.rate_hz
        n = 0
        while True:
            t = self.clock()
            try:
                if self.model is not None:
                    a, g = self.imu.read6()
                    self.feed(t, a, g)
                    if n % 10 == 0:
                        self.feed_compass(t, self.get_compass())
                if n % self.rate_hz == 0:
                    self.vet()
            except OSError:
                pass
            except Exception:  # never let a filter bug kill the thread
                pass
            n += 1
            time.sleep(max(0.0, period - (self.clock() - t)))

    def status(self):
        with self.lock:
            t = self.clock()
            m = self.monitor
            gps = "suspect" if m.suspect(t) else ("trusted-by-hand" if t < m.trust_until else "ok")
            return {"available": self.model is not None, "model": self.model, "state": self.state,
                    "align_pct": self.align.pct if self.align else (100 if self.model else 0),
                    "degraded": self.degraded, "heading": self.heading(),
                    "heading_sigma": round(math.sqrt(max(self.p00, 0.0)), 1) if self.psi is not None else None,
                    "gyro_bias_dps": [round(x, 3) for x in self.bias], "tilt": round(self.tilt, 1),
                    "turn_dps": round(self.rate, 2), "gps": gps, "reasons": list(m.reasons) if gps == "suspect" else [],
                    "notes": list(m.notes), "flags_total": m.flags_total, "action": self.spoof_action,
                    "sea": bool(self.align.sea) if self.align else bool(self.get_sea())}
