"""Downloaded weather forecast grid, kept for offline use.

Whenever the device has internet (home WiFi, a phone hotspot) it fetches a
16-day forecast from Open-Meteo (free for non-commercial use, no API key) for
your position plus a grid of points around it, and stores it in user.db.
Without internet the last download keeps working; the UI shows its age.
"""
import json
import socket
import threading
import time
import urllib.parse
import urllib.request

API = "https://api.open-meteo.com/v1/forecast"
DAILY = ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
         "wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant")
HOURLY = ("temperature_2m,precipitation,precipitation_probability,weather_code,wind_speed_10m,"
          "wind_gusts_10m,wind_direction_10m,pressure_msl,cloud_cover")

# WMO weather interpretation codes
WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers", 81: "Showers",
    82: "Violent showers", 85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm, hail", 99: "Thunderstorm, heavy hail",
}


def online(host="api.open-meteo.com", timeout=3):
    try:
        socket.create_connection((host, 443), timeout=timeout).close()
        return True
    except OSError:
        return False


def _get(params, timeout=60):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "doomsday-pocket-computer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def grid_points(lat, lon, half=2, step=0.5):
    """(2*half+1)^2 points centred on lat/lon, `step` degrees apart (0.5 deg ~ 55 km N-S)."""
    pts = []
    for i in range(-half, half + 1):
        for j in range(-half, half + 1):
            pts.append((round(lat + i * step, 3), round(lon + j * step * 1.5, 3)))  # wider E-W at 50+ deg
    return pts


class Forecaster:
    def __init__(self, user_db_path, get_position, grid_half=2, grid_step=0.5, max_age_h=3):
        self.db_path = user_db_path
        self.get_position = get_position  # callable -> (lat, lon)
        self.grid_half = grid_half
        self.grid_step = grid_step
        self.max_age_h = max_age_h
        self.last_error = None
        self.busy = False
        self._lock = threading.Lock()
        import sqlite3
        self._sqlite = sqlite3
        db = self._db()
        db.execute("CREATE TABLE IF NOT EXISTS forecast(kind TEXT PRIMARY KEY, fetched REAL, lat REAL, lon REAL, "
                   "data TEXT)")
        db.commit()
        db.close()

    def _db(self):
        return self._sqlite.connect(self.db_path, timeout=10)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        time.sleep(20)
        while True:
            try:
                if self.age_hours() is None or self.age_hours() > self.max_age_h:
                    if online():
                        self.update()
            except Exception as e:  # noqa: BLE001  keep the thread alive whatever happens
                self.last_error = str(e)
            time.sleep(1800)

    def age_hours(self):
        db = self._db()
        r = db.execute("SELECT fetched FROM forecast WHERE kind='home'").fetchone()
        db.close()
        return (time.time() - r[0]) / 3600 if r else None

    def update(self):
        """Download now. Returns None on success or an error message."""
        if not self._lock.acquire(blocking=False):
            return "Download already running"
        self.busy = True
        try:
            lat, lon = self.get_position()
            home = _get({"latitude": lat, "longitude": lon, "daily": DAILY, "hourly": HOURLY,
                         "forecast_days": 16, "timezone": "auto", "wind_speed_unit": "kmh"})
            pts = grid_points(lat, lon, self.grid_half, self.grid_step)
            grid = _get({"latitude": ",".join(str(p[0]) for p in pts),
                         "longitude": ",".join(str(p[1]) for p in pts),
                         "daily": DAILY, "forecast_days": 16, "timezone": "auto", "wind_speed_unit": "kmh"})
            if isinstance(grid, dict):
                grid = [grid]
            now = time.time()
            db = self._db()
            db.execute("INSERT OR REPLACE INTO forecast VALUES('home',?,?,?,?)", (now, lat, lon, json.dumps(home)))
            db.execute("INSERT OR REPLACE INTO forecast VALUES('grid',?,?,?,?)", (now, lat, lon, json.dumps(grid)))
            db.commit()
            db.close()
            self.last_error = None
            return None
        except (OSError, ValueError) as e:
            self.last_error = "Download failed: %s" % e
            return self.last_error
        finally:
            self.busy = False
            self._lock.release()

    def report(self):
        db = self._db()
        rows = {k: (f, la, lo, d) for k, f, la, lo, d in db.execute("SELECT kind, fetched, lat, lon, data FROM forecast")}
        db.close()
        out = {"busy": self.busy, "error": self.last_error}
        if "home" not in rows:
            out["message"] = "No forecast downloaded yet. Connect to WiFi or a phone hotspot and press Update."
            return out
        fetched, lat, lon, data = rows["home"]
        home = json.loads(data)
        out.update({"fetched": fetched, "age_h": round((time.time() - fetched) / 3600, 1), "lat": lat, "lon": lon,
                    "timezone": home.get("timezone")})
        d = home.get("daily", {})
        days = []
        for i, day in enumerate(d.get("time", [])):
            def g(k):
                v = d.get(k)
                return v[i] if v and i < len(v) else None
            days.append({"date": day, "code": g("weather_code"), "text": WMO.get(g("weather_code"), ""),
                         "tmax": g("temperature_2m_max"), "tmin": g("temperature_2m_min"),
                         "rain": g("precipitation_sum"), "rain_prob": g("precipitation_probability_max"),
                         "wind": g("wind_speed_10m_max"), "gust": g("wind_gusts_10m_max"),
                         "wind_dir": g("wind_direction_10m_dominant")})
        out["days"] = days
        h = home.get("hourly", {})
        times = h.get("time", [])
        # next 48 hours from the current local hour
        now_local = time.strftime("%Y-%m-%dT%H:00", time.gmtime(time.time() + home.get("utc_offset_seconds", 0)))
        start = next((i for i, t in enumerate(times) if t >= now_local), len(times))
        keys = ("temperature_2m", "precipitation", "precipitation_probability", "weather_code",
                "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m", "pressure_msl")
        out["hours"] = [[times[i]] + [h.get(k, [None] * len(times))[i] for k in keys]
                        for i in range(start, min(len(times), start + 48))]
        out["hour_keys"] = ["time"] + list(keys)
        if "grid" in rows:
            grid = json.loads(rows["grid"][3])
            out["grid_dates"] = grid[0].get("daily", {}).get("time", []) if grid else []
            out["grid"] = [{"lat": g.get("latitude"), "lon": g.get("longitude"),
                            "rain": g.get("daily", {}).get("precipitation_sum"),
                            "gust": g.get("daily", {}).get("wind_gusts_10m_max"),
                            "wind_dir": g.get("daily", {}).get("wind_direction_10m_dominant"),
                            "tmax": g.get("daily", {}).get("temperature_2m_max"),
                            "tmin": g.get("daily", {}).get("temperature_2m_min")} for g in grid]
        return out
