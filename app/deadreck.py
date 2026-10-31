"""Dead reckoning: keep estimating where you are when GPS has no fix.

On foot: an accelerometer (MPU-6050 / GY-521, or the MPU-6500/9250 clones sold
under that name) counts steps; each step moves the estimate one step length in
the compass direction. The step length learns itself from GPS while there is a fix.

At sea (or in a vehicle): steps mean nothing on a rocking boat, so the estimate
carries on with the last GPS speed and course (or a speed and course you enter,
e.g. from the boat's log and steering compass).

The estimate starts from the last GPS fix, or from a position you set by hand
("I am here"), and its uncertainty grows with distance and time.
"""
import math
import threading
import time

G = 9.80665
WHO_AM_I_OK = {0x68: "MPU-6050", 0x70: "MPU-6500", 0x71: "MPU-9250", 0x73: "MPU-9255", 0x72: "MPU-6500"}


class IMU:
    """MPU-6050 family accelerometer on I2C: 0x69 with AD0 tied high (this build, because the
    DS3231 clock uses 0x68), or 0x68."""

    def __init__(self, bus, addresses=(0x69, 0x68)):  # 0x69 first: a DS3231 clock sits on 0x68
        self.bus = bus
        self.available = False
        self.model = None
        if bus is None:
            return
        for a in addresses:
            try:
                who = bus.read_byte_data(a, 0x75)
            except OSError:
                continue
            if who in WHO_AM_I_OK:
                self.addr, self.model = a, WHO_AM_I_OK[who]
                try:
                    bus.write_byte_data(a, 0x6B, 0x01)  # wake up, gyro X clock
                    bus.write_byte_data(a, 0x1C, 0x00)  # accel +-2 g
                    bus.write_byte_data(a, 0x1A, 0x03)  # digital low-pass ~44 Hz
                    self.available = True
                except OSError:
                    pass
                break

    def accel(self):
        """(ax, ay, az) in g."""
        d = self.bus.read_i2c_block_data(self.addr, 0x3B, 6)
        v = [(d[i] << 8 | d[i + 1]) for i in (0, 2, 4)]
        return tuple((x - 65536 if x > 32767 else x) / 16384.0 for x in v)


class StepDetector:
    """Peaks in the acceleration magnitude: a step is a rise above ~1.12 g followed by a
    fall below ~0.95 g, at least 0.28 s after the previous step (max ~3.5 steps/s)."""

    def __init__(self, high=1.12, low=0.95, min_gap=0.28):
        self.high, self.low, self.min_gap = high, low, min_gap
        self.armed = False
        self.last_step = 0.0
        self.smooth = 1.0
        self.count = 0

    def feed(self, t, ax, ay, az):
        m = math.sqrt(ax * ax + ay * ay + az * az)
        self.smooth += 0.35 * (m - self.smooth)  # light low-pass against vibration
        if not self.armed and self.smooth > self.high:
            self.armed = True
        elif self.armed and self.smooth < self.low:
            self.armed = False
            if t - self.last_step >= self.min_gap:
                self.last_step = t
                self.count += 1
                return True
        return False


def move(lat, lon, dist_m, bearing_deg):
    """Point `dist_m` metres from (lat, lon) in direction `bearing_deg` (flat-earth, fine below ~50 km steps)."""
    b = math.radians(bearing_deg)
    dlat = dist_m * math.cos(b) / 111320.0
    dlon = dist_m * math.sin(b) / (111320.0 * max(0.01, math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


class DeadReckoner:
    def __init__(self, imu, get_fix, get_heading, get_manual, settings, rate_hz=50):
        """get_fix() -> GPS fix dict; get_heading() -> degrees or None;
        get_manual() -> {"lat","lon","set"} or None; settings: (get, set) callables."""
        self.imu = imu
        self.get_fix, self.get_heading, self.get_manual = get_fix, get_heading, get_manual
        self._get, self._set = settings
        self.rate_hz = rate_hz
        self.steps = StepDetector()
        self.lock = threading.Lock()
        self.step_len = self._get("dr_step_len") or 0.72
        self.anchor = None      # {"lat","lon","t","source"}: where the estimate started
        self.pos = None         # current estimate (lat, lon)
        self.dist = 0.0         # metres moved since the anchor
        self.last_good = None   # last good GPS fix: (t, lat, lon, speed m/s, course)
        self._cal = None        # step-length learning: (steps at start, lat, lon)
        self.last_t = time.time()
        self.track = []

    # --- settings ---------------------------------------------------------
    @property
    def mode(self):
        return self._get("dr_mode") or "foot"   # "foot", "boat" or "off"

    def set_mode(self, mode, speed_kn=None, course=None):
        if mode not in ("foot", "boat", "off"):
            raise ValueError("mode must be foot, boat or off")
        self._set("dr_mode", mode)
        if mode == "boat":
            self._set("dr_boat", {"speed_kn": speed_kn, "course": course} if speed_kn is not None else None)

    # --- main loop ------------------------------------------------------
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        period = 1.0 / self.rate_hz
        n = 0
        while True:
            t = time.time()
            stepped = False
            if self.imu is not None and self.imu.available:
                try:
                    stepped = self.steps.feed(t, *self.imu.accel())
                except OSError:
                    pass
            if stepped:
                self.on_step(t)
            n += 1
            if n % self.rate_hz == 0:  # once a second
                self.tick(t)
            time.sleep(max(0.0, period - (time.time() - t)))

    def _fix_ok(self, f):
        return f.get("mode", 0) >= 2 and f.get("lat") is not None and not f.get("stale") and \
            (f.get("hdop") is None or f["hdop"] < 5)

    def tick(self, t=None):
        """Once a second: follow GPS while it has a fix, otherwise extrapolate at sea."""
        t = t or time.time()
        dt = t - self.last_t
        self.last_t = t
        f = self.get_fix()
        with self.lock:
            if self._fix_ok(f):
                self.last_good = (t, f["lat"], f["lon"], f.get("speed") or 0.0, f.get("track"))
                self.anchor = {"lat": f["lat"], "lon": f["lon"], "t": t, "source": "gps"}
                self.pos, self.dist = (f["lat"], f["lon"]), 0.0
                self._learn_step(f)
                return
            self._cal = None
            m = self.get_manual()
            if m and (self.anchor is None or m.get("set", 0) > self.anchor["t"]):
                # a position set by hand is a fresh starting point
                self.anchor = {"lat": m["lat"], "lon": m["lon"], "t": m.get("set", t), "source": "manual"}
                self.pos, self.dist = (m["lat"], m["lon"]), 0.0
            if self.pos is None or self.mode != "boat" or dt <= 0 or dt > 30:
                return
            boat = self._get("dr_boat") or {}
            if boat.get("speed_kn") is not None:
                speed, course = boat["speed_kn"] * 0.514444, boat.get("course")
            elif self.last_good:
                speed, course = self.last_good[3], self.last_good[4]
            else:
                return
            if course is None:
                course = self.get_heading()
            if course is None or speed < 0.05:
                return
            self.pos = move(self.pos[0], self.pos[1], speed * dt, course)
            self.dist += speed * dt
            self._log(t)

    def on_step(self, t=None):
        t = t or time.time()
        with self.lock:
            if self.mode != "foot" or self.pos is None or self.anchor is None or self.anchor["source"] == "gps" \
                    and self._fix_ok(self.get_fix()):
                return
            h = self.get_heading()
            if h is None:
                return
            self.pos = move(self.pos[0], self.pos[1], self.step_len, h)
            self.dist += self.step_len
            self._log(t)

    def _learn_step(self, f):
        """While walking with GPS, compare GPS distance with counted steps (100+ steps, 60+ m)."""
        if self.mode != "foot" or (f.get("hdop") or 1) > 2.5:
            return
        if self._cal is None:
            self._cal = (self.steps.count, f["lat"], f["lon"])
            return
        n = self.steps.count - self._cal[0]
        if n < 100:
            return
        lat0, lon0 = self._cal[1], self._cal[2]
        d = math.hypot((f["lat"] - lat0) * 111320.0, (f["lon"] - lon0) * 111320.0 * math.cos(math.radians(lat0)))
        if d > 60:
            sl = d / n  # straight-line, so it can only underestimate on winding paths: be gentle
            if 0.4 < sl < 1.1:
                self.step_len = round(0.8 * self.step_len + 0.2 * sl, 3)
                self._set("dr_step_len", self.step_len)
        self._cal = (self.steps.count, f["lat"], f["lon"])

    def _log(self, t):
        if not self.track or t - self.track[-1][0] > 15:
            self.track.append((t, self.pos[0], self.pos[1]))
            del self.track[:-2000]

    # --- what the rest of the app sees ------------------------------------
    def estimate(self):
        """Current estimate when GPS has no fix: dict, or None if there is nothing to go on."""
        with self.lock:
            if self.pos is None or self.anchor is None or self.mode == "off":
                return None
            if self.anchor["source"] == "gps" and self.dist == 0 and self._fix_ok(self.get_fix()):
                return None
            age = time.time() - self.anchor["t"]
            if self.mode == "boat":
                err = 50 + 0.10 * self.dist + 0.25 * age  # current and leeway: ~0.5 kn unknown drift
            else:
                err = 10 + 0.05 * self.dist
            if self.anchor["source"] == "manual":
                err += 100  # a tap on the map is not exact
            return {"lat": self.pos[0], "lon": self.pos[1], "err_m": round(err), "mode": self.mode,
                    "dist_m": round(self.dist), "since": self.anchor["t"], "from": self.anchor["source"],
                    "step_len": self.step_len, "steps": self.steps.count}

    def status(self):
        return {"imu": self.imu.model if self.imu is not None and self.imu.available else None,
                "mode": self.mode, "step_len": self.step_len, "steps": self.steps.count,
                "boat": self._get("dr_boat"), "estimate": self.estimate()}
