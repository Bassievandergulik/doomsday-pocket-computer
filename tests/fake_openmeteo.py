"""Tiny stand-in for the Open-Meteo API, used by the tests (no internet needed)."""
import datetime as dt
import http.server
import json
import math
import threading
from urllib.parse import parse_qs, urlparse


def fake_point(lat, lon, hourly):
    today = dt.date.today()
    days = [(today + dt.timedelta(days=i)).isoformat() for i in range(16)]
    d = {"time": days,
         "weather_code": [61 if i % 3 else 3 for i in range(16)],
         "temperature_2m_max": [12 + math.sin(i + lat) * 3 for i in range(16)],
         "temperature_2m_min": [4 + math.sin(i) for i in range(16)],
         "precipitation_sum": [abs(math.sin(i + lon)) * 12 for i in range(16)],
         "precipitation_probability_max": [(i * 13) % 100 for i in range(16)],
         "wind_speed_10m_max": [20 + i for i in range(16)],
         "wind_gusts_10m_max": [40 + i * 3 for i in range(16)],
         "wind_direction_10m_dominant": [(200 + i * 20 + lat * 10) % 360 for i in range(16)]}
    out = {"latitude": lat, "longitude": lon, "timezone": "Europe/Amsterdam", "utc_offset_seconds": 3600, "daily": d}
    if hourly:
        start = dt.datetime.combine(today, dt.time())
        times = [(start + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(16 * 24)]
        n = len(times)
        out["hourly"] = {"time": times, "temperature_2m": [8 + 4 * math.sin(h / 4) for h in range(n)],
                         "precipitation": [max(0, math.sin(h / 5)) for h in range(n)],
                         "precipitation_probability": [h % 100 for h in range(n)],
                         "weather_code": [61] * n, "wind_speed_10m": [15] * n, "wind_gusts_10m": [35] * n,
                         "wind_direction_10m": [240] * n, "pressure_msl": [1010] * n, "cloud_cover": [80] * n}
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        lats = [float(v) for v in q["latitude"].split(",")]
        lons = [float(v) for v in q["longitude"].split(",")]
        pts = [fake_point(a, b, "hourly" in q) for a, b in zip(lats, lons)]
        body = json.dumps(pts[0] if len(pts) == 1 else pts).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(port=0):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
