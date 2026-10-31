#!/usr/bin/env python3
"""Doomsday pocket computer: offline map, navigation, radio, weather and survival library.

Runs a small web server on the device (default http://127.0.0.1:8080) that the
touchscreen browser shows full-screen. Standard library only; smbus2, pyserial
and lgpio are optional and only needed for the hardware they drive.

    python3 app/server.py --data data/
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import geo  # noqa: E402
from gps import GPS, track_length_m  # noqa: E402
from library import Library  # noqa: E402
import radio as radio_mod  # noqa: E402
import sensors  # noqa: E402
from weather import WeatherStation  # noqa: E402
from forecast import Forecaster  # noqa: E402
import hotspot as hotspot_mod  # noqa: E402
import exports  # noqa: E402
import shortwave as shortwave_mod  # noqa: E402
import deadreck  # noqa: E402
import ins as ins_mod  # noqa: E402
import airband as airband_mod  # noqa: E402
import light as light_mod  # noqa: E402
import mesh as mesh_mod  # noqa: E402
from kiwix import Kiwix  # noqa: E402
from search import Finder, LANGS, LANG_NAMES  # noqa: E402

STATIC = os.path.join(HERE, "static")
MAX_DATA_ZOOM = 14  # vector tiles above this zoom reuse z14 data

DEFAULT_CONFIG = {
    "port": 8080,
    "gps_serial": "/dev/serial0",       # GPS module on the UART (gpsd is tried first)
    "gps_baud": 9600,
    "simulate_position": None,          # e.g. [52.09, 5.12] when testing without GPS
    "home_altitude_m": 0,               # used by the barometer when there is no GPS fix
    "magnetic_declination": 2.5,        # degrees east; ~+2..+5 across NL/DE/BE in 2026
    "radio_chip": "si4732",             # "si4732" (FM+AM+SW+SSB), "rda5807m" (FM only) or "none"
    "radio_address": 17,                # 0x11 = Si4732 with SEN to GND; SEN high: 99 (0x63)
    "radio_reset_gpio": 23,             # Si4732 RST pin
    "ssb_patch": "ssb_patch.bin",       # in the data folder; made by tools/get_ssb_patch.py
    "audio_device": "auto",             # USB sound stick for weather fax / RTTY ("auto" or e.g. "plughw:1,0")
    "sw_capture_volume": 45,            # radio volume (0-63) while recording a fax / RTTY
    "sw_keep_audio": False,
    "airband_gain": 40,
    "meshtastic_port": "auto",          # USB serial port of a Meshtastic node, or "auto"
    "board": "pi",                      # "pi" (Pi Zero 2 W / 3 A+); see docs/boards.md for alternatives
    "light_white_gpio": 12,             # MOSFET gate of the 1 W white LED (PWM pin)
    "light_red_gpio": 13,               # MOSFET gate of the red LED (PWM pin)                 # RTL-SDR tuner gain in dB for the airband receiver             # keep the WAV recordings (about 1 MB per minute)
    "i2c_bus": 1,
    "ins_enabled": True,                # IRS-style inertial heading + GPS spoof checks (needs the gyro chip)
    "ins_mount": ["x", "y", "z"],       # which chip axes point forward / left / up (e.g. ["y", "-x", "z"])
    "ins_spoof_action": "switch",       # "switch": ignore a suspect GPS and carry on by dead reckoning; "warn": only warn
    "ins_compass_sigma": 6.0,           # degrees; raise it on a steel boat with a poor compass
    "ins_max_speed_ms": 60.0,           # a GPS position change faster than this is a jump (fake or glitch)
    "weather_interval_s": 600,
    "forecast_auto_download": True,     # opportunistic: refresh the forecast whenever internet happens to be there
    "forecast_grid_half": 2,            # 5x5 grid of points around you
    "forecast_grid_step": 0.5,          # degrees between grid points (~55 km)
    "start_view": [52.1, 5.3, 8],       # lat, lon, zoom shown before a position is known
    "battery_shutdown_v": 3.35,          # UPS HAT: shut down cleanly below this cell voltage
    "hotspot_auto_off_min": 60,         # switch the direct-WiFi hotspot off after this long unused (0 = never)
    "extra_data_dirs": ["/boot/firmware/doomsday", "/media/doomsday"],  # also look here for nav.db / map.mbtiles / zim / videos
    "kiwix_url": "http://127.0.0.1:8081/kiwix",  # kiwix-serve with Wikipedia etc. (deploy/kiwix.sh)
}


class App:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        cfg_path = os.path.join(data_dir, "config.json")
        self.config = dict(DEFAULT_CONFIG)
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                self.config.update(json.load(f))
        else:
            with open(cfg_path, "w") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)

        self.nav_path = self._find_data_file("nav.db")
        self.mbtiles_path = self._find_data_file("map.mbtiles")
        self.user_path = os.path.join(data_dir, "user.db")
        self._local = threading.local()
        self._init_user_db()

        self.library = Library(os.path.join(HERE, "..", "library"))
        self.kiwix = Kiwix(self.config["kiwix_url"])
        self.finder = Finder(self, os.path.join(HERE, "lexicon.txt"), self.kiwix,
                             [os.path.join(d, "videos") for d in [data_dir] + list(self.config["extra_data_dirs"])])
        self.hotspot = hotspot_mod.Hotspot(self.get_setting, self.set_setting, self.config["hotspot_auto_off_min"])

        self.gps = GPS(serial_port=self.config["gps_serial"], baud=self.config["gps_baud"],
                       simulate=self.config["simulate_position"])
        self.gps.start()

        bus = sensors.open_bus(self.config["i2c_bus"])
        cal = self.get_setting("compass_cal")
        self.compass = sensors.Compass(bus, calibration=cal, declination=self.config["magnetic_declination"])
        self.bme = sensors.BME280(bus)
        self.battery = sensors.Battery(bus)
        self.imu = deadreck.IMU(bus)
        self.battery_state = {"available": self.battery.available}
        if self.battery.available:
            threading.Thread(target=self._battery_watch, daemon=True).start()

        def gps_alt():
            f = self.gps.get()
            return f.get("alt") if f.get("mode", 0) >= 3 and not f.get("stale") else None

        self.weather = WeatherStation(self.bme, self.user_path, self.config["home_altitude_m"],
                                      self.config["weather_interval_s"], get_alt=gps_alt)
        self.weather.start()

        self.forecast = Forecaster(self.user_path, lambda: self.position() or tuple(self.config["start_view"][:2]),
                                   grid_half=self.config["forecast_grid_half"],
                                   grid_step=self.config["forecast_grid_step"])
        if self.config["forecast_auto_download"]:
            self.forecast.start()

        patch = self.config["ssb_patch"]
        patch = patch if os.path.isabs(patch) else self._find_data_file(patch)
        self.radio = radio_mod.open_radio(bus, self.config["radio_chip"], self.config["radio_address"],
                                          self.config["radio_reset_gpio"], ssb_patch=patch)
        if self.radio.available:
            r = self.radio
            vol = self.get_setting("radio_volume")
            r.set_volume(vol if vol is not None else r.volume_max * 2 // 3)
            last = self.get_setting("radio_last")
            if last:
                try:
                    r.set_band(last["band"])
                    r.tune(last["freq"])
                except (OSError, KeyError, ValueError):
                    pass

        self.shortwave = shortwave_mod.Shortwave(self, os.path.join(data_dir, "shortwave"),
                                                 self.config["audio_device"], self.config["sw_capture_volume"],
                                                 self.config["sw_keep_audio"])
        self.shortwave.start_scheduler()

        # dead reckoning: keeps an estimated position when GPS has no fix
        def compass_true():
            try:
                return self.compass.heading() if self.compass.available else None
            except OSError:
                return None

        def dr_ref():
            if getattr(self, "dr", None) is None:
                return None
            e = self.dr.estimate()
            if e:
                return e["lat"], e["lon"], e["err_m"]
            a = self.dr.anchor
            return (a["lat"], a["lon"], 100.0) if a else None

        self.ins = ins_mod.INS(self.imu if self.config["ins_enabled"] else None, compass_true, self.gps.get,
                               (self.get_setting, self.set_setting), get_sea=lambda: getattr(self, "dr", None) is not None and self.dr.mode == "boat",
                               get_steps=lambda: self.dr.steps.count if getattr(self, "dr", None) is not None and self.dr.mode == "foot" else None,
                               get_ref=dr_ref, mount=self.config["ins_mount"],
                               spoof_action=self.config["ins_spoof_action"],
                               compass_sigma=self.config["ins_compass_sigma"], max_speed=self.config["ins_max_speed_ms"])
        self.dr = deadreck.DeadReckoner(self.imu, self.gps.get, lambda: self.heading()["heading"],
                                        lambda: self.get_setting("manual_pos"), (self.get_setting, self.set_setting),
                                        ins=self.ins)
        self.dr.start()
        self.ins.start()
        threading.Thread(target=self._clock_from_gps, daemon=True).start()
        self.mesh = mesh_mod.Mesh(self.config["meshtastic_port"], get_position=self.position)
        self.mesh.start()
        self.light = light_mod.Light(self.config["light_white_gpio"], self.config["light_red_gpio"])
        self.airband = airband_mod.Airband(self.get_setting, self.set_setting, self.config["audio_device"],
                                           self.config["airband_gain"])
        self._seed_presets()

    def _clock_from_gps(self):
        """Set the clock from GPS time when it is off (no internet needed)."""
        while True:
            time.sleep(60)
            f = self.gps.get()
            utc = f.get("utc")
            if not utc or f.get("mode", 0) < 2 or f.get("stale"):
                continue
            try:
                t = dt.datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp()
                if abs(t - time.time()) > 30:
                    self.set_clock(t)
            except (ValueError, OSError):
                pass

    # aviation weather broadcasts on shortwave (voice, USB), useful anywhere over the North Atlantic
    VOLMET = [("Shannon VOLMET (night)", 3413), ("Shannon VOLMET", 5505), ("Shannon VOLMET", 8957),
              ("Shannon VOLMET (day)", 13264), ("RAF VOLMET", 5450), ("RAF VOLMET (day)", 11253),
              ("Gander VOLMET (night)", 3485), ("Gander VOLMET", 6604), ("Gander VOLMET", 10051),
              ("Gander VOLMET (day)", 13270)]

    def _seed_presets(self):
        if "USB" not in getattr(self.radio, "bands", {}) or self.get_setting("seeded_volmet"):
            return
        db = self.user()
        for name, khz in self.VOLMET:
            db.execute("INSERT INTO radio_presets(name,band,freq) VALUES(?,?,?)", (name, "USB", khz))
        db.commit()
        self.set_setting("seeded_volmet", True)

    def _find_data_file(self, name):
        """data/ first, then folders you can fill from any PC (the SD card's FAT boot partition, a USB stick)."""
        for d in [self.data_dir] + list(self.config["extra_data_dirs"]):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
        return os.path.join(self.data_dir, name)

    def _battery_watch(self):
        low_since = None
        while True:
            try:
                v = self.battery.voltage()
                pct = sensors.Battery.percent(v)
                self.battery_state = {"available": True, "voltage": round(v, 2), "percent": pct}
                if v < self.config["battery_shutdown_v"]:
                    low_since = low_since or time.time()
                    self.battery_state["shutting_down"] = time.time() - low_since > 30
                    if time.time() - low_since > 60:
                        # clean shutdown protects the SD card; charging starts it again
                        os.system("sudo -n systemctl poweroff")
                else:
                    low_since = None
            except OSError:
                pass
            time.sleep(10)

    # --- databases -------------------------------------------------------
    def nav(self):
        if not os.path.exists(self.nav_path):
            return None
        db = getattr(self._local, "nav", None)
        if db is None:
            db = sqlite3.connect("file:%s?mode=ro" % self.nav_path, uri=True, check_same_thread=False)
            self._local.nav = db
        return db

    def mbtiles(self):
        if not os.path.exists(self.mbtiles_path):
            return None
        db = getattr(self._local, "mbt", None)
        if db is None:
            db = sqlite3.connect("file:%s?mode=ro" % self.mbtiles_path, uri=True, check_same_thread=False)
            self._local.mbt = db
        return db

    def user(self):
        db = getattr(self._local, "user", None)
        if db is None:
            db = sqlite3.connect(self.user_path, timeout=10, check_same_thread=False)
            self._local.user = db
        return db

    def _init_user_db(self):
        db = sqlite3.connect(self.user_path)
        # WAL keeps the database consistent if the power is cut mid-write
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS waypoints(id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL,
                                             icon TEXT, note TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS radio_presets(id INTEGER PRIMARY KEY, name TEXT, band TEXT, freq INT);
        """)
        db.commit()
        db.close()

    def get_setting(self, key):
        r = self.user().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def set_setting(self, key, value):
        db = self.user()
        db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))
        db.commit()

    # --- map data --------------------------------------------------------
    def vector_tile(self, z, x, y):
        db = self.nav()
        if db is None:
            return {"lines": [], "areas": [], "places": [], "pois": []}
        dz = min(z, MAX_DATA_ZOOM)
        w, s, e, n = geo.tile_bbox(z, x, y)
        # small margin so lines crossing the tile edge are drawn
        mx, my = (e - w) * 0.05, (n - s) * 0.05
        args = (dz, w - mx, e + mx, s - my, n + my)
        col = "COALESCE(geom_lo, geom)" if dz < 12 else "geom"
        out = {"lines": [], "areas": [], "places": [], "pois": []}
        for cls, name, g in db.execute(
                "SELECT t.cls, t.name, %s FROM areas t JOIN areas_idx i ON t.id=i.id "
                "WHERE t.minz<=? AND i.maxx>=? AND i.minx<=? AND i.maxy>=? AND i.miny<=? LIMIT 4000" % col,
                (args[0], args[1], args[2], args[3], args[4])):
            out["areas"].append([cls, geo.decode(g)])
        for cls, name, g in db.execute(
                "SELECT t.cls, t.name, %s FROM lines t JOIN lines_idx i ON t.id=i.id "
                "WHERE t.minz<=? AND i.maxx>=? AND i.minx<=? AND i.maxy>=? AND i.miny<=? LIMIT 8000" % col,
                (args[0], args[1], args[2], args[3], args[4])):
            out["lines"].append([cls, name if z >= 15 else None, geo.decode(g)])
        for kind, name, lon, lat in db.execute(
                "SELECT t.kind, t.name, t.lon, t.lat FROM places t JOIN places_idx i ON t.id=i.id "
                "WHERE t.minz<=? AND i.maxx>=? AND i.minx<=? AND i.maxy>=? AND i.miny<=? "
                "ORDER BY t.minz, t.population DESC LIMIT 60", (dz + 1, w, e, s, n)):
            out["places"].append([kind, name, lon, lat])
        if z >= 12:
            for pid, cat, name, lon, lat in db.execute(
                    "SELECT t.id, t.cat, t.name, t.lon, t.lat FROM pois t JOIN pois_idx i ON t.id=i.id "
                    "WHERE i.maxx>=? AND i.minx<=? AND i.maxy>=? AND i.miny<=? LIMIT 500", (w, e, s, n)):
                out["pois"].append([pid, cat, name, lon, lat])
        return out

    def nearest(self, lat, lon, cat=None, limit=10, max_km=50):
        db = self.nav()
        if db is None:
            return []
        found = []
        r_km = 1.0
        while r_km <= max_km:
            dlat = r_km / 111.0
            dlon = r_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
            q = ("SELECT t.id, t.cat, t.name, t.lon, t.lat, t.tags FROM pois t JOIN pois_idx i ON t.id=i.id "
                 "WHERE i.maxx>=? AND i.minx<=? AND i.maxy>=? AND i.miny<=?")
            a = [lon - dlon, lon + dlon, lat - dlat, lat + dlat]
            if cat:
                q += " AND t.cat=?"
                a.append(cat)
            rows = db.execute(q + " LIMIT 2000", a).fetchall()
            found = [r for r in rows if geo.haversine(lat, lon, r[4], r[3]) <= r_km * 1000]
            if len(found) >= limit or r_km >= max_km:
                break
            r_km *= 2.5
        res = []
        for pid, c, name, plon, plat, tags in found:
            res.append({"id": pid, "cat": c, "name": name, "lat": plat, "lon": plon,
                        "tags": json.loads(tags or "{}"),
                        "dist_m": round(geo.haversine(lat, lon, plat, plon)),
                        "bearing": round(geo.bearing(lat, lon, plat, plon))})
        res.sort(key=lambda r: r["dist_m"])
        return res[:limit]

    def search(self, q, lat=None, lon=None):
        db = self.nav()
        out = []
        if db is not None and q.strip():
            terms = " ".join('"%s"*' % t.replace('"', "") for t in q.split())
            try:
                rows = db.execute("SELECT name, kind, ref, lon, lat FROM search WHERE search MATCH ? "
                                  "ORDER BY rank LIMIT 40", (terms,)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for name, kind, ref, plon, plat in rows:
                item = {"name": name, "kind": kind, "ref": ref, "lat": plat, "lon": plon}
                if lat is not None:
                    item["dist_m"] = round(geo.haversine(lat, lon, plat, plon))
                    item["bearing"] = round(geo.bearing(lat, lon, plat, plon))
                out.append(item)
        for wid, name, wlat, wlon in self.user().execute(
                "SELECT id, name, lat, lon FROM waypoints WHERE name LIKE ?", ("%" + q + "%",)):
            out.insert(0, {"name": name, "kind": "waypoint", "ref": "wp:%d" % wid, "lat": wlat, "lon": wlon})
        if lat is not None:
            out.sort(key=lambda r: (r["kind"] != "waypoint", r.get("dist_m", 0)))
        return out

    def position(self):
        """GPS fix if there is one, else the position you set by hand on the map."""
        f = self.gps.get()
        ins = getattr(self, "ins", None)
        if f.get("mode", 0) >= 2 and f.get("lat") is not None and (ins is None or ins.gps_trusted(f)):
            return f["lat"], f["lon"]
        dr = getattr(self, "dr", None)
        e = dr.estimate() if dr else None
        if e:
            return e["lat"], e["lon"]
        m = self.get_setting("manual_pos")
        if m:
            return m["lat"], m["lon"]
        return None

    def set_clock(self, epoch):
        """Set the system clock (the Pi has no clock battery; without internet or a GPS fix
        nothing else sets it). Returns the change in seconds."""
        import subprocess
        if not 1767225600 <= epoch <= 4102444800:  # 2026..2100: refuse obviously wrong times
            raise ValueError("implausible date")
        diff = epoch - time.time()
        if abs(diff) < 30:
            return 0
        r = subprocess.run(["sudo", "-n", "date", "-u", "-s", "@%d" % int(epoch)], capture_output=True, text=True)
        if r.returncode != 0:
            raise OSError((r.stderr or "date failed").strip())
        subprocess.run(["sudo", "-n", "fake-hwclock", "save"], capture_output=True)
        if os.path.exists("/dev/rtc0"):  # DS3231 clock chip: keep it in step too
            subprocess.run(["sudo", "-n", "hwclock", "-w"], capture_output=True)
        return round(diff)

    def heading(self):
        h = None
        src = None
        ins = getattr(self, "ins", None)
        if ins is not None and ins.heading() is not None:
            return {"heading": ins.heading(), "source": "ins", "compass": self.compass.available}
        if self.compass.available:
            try:
                h, src = self.compass.heading(), "compass"
            except OSError:
                h = None
        if h is None:
            f = self.gps.get()
            if f.get("track") is not None and (f.get("speed") or 0) > 0.8:
                h, src = f["track"], "gps-course"
        return {"heading": h, "source": src, "compass": self.compass.available}

    def status(self):
        f = self.gps.get()
        sun = None
        pos = self.position() or tuple(self.config["start_view"][:2])
        if pos:
            st = geo.sun_times(pos[0], pos[1], dt.date.today())
            sun = {k: (v.isoformat() if v else None) for k, v in st.items()}
        meta = {}
        db = self.nav()
        if db is not None:
            meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
        return {
            "gps": f, "utm": geo.to_mgrs_like(*pos) if pos else None,
            "sun": sun, "nav_db": meta, "raster": self.mbtiles() is not None,
            "raster_attribution": self._raster_attribution(),
            "radio": self.radio.available, "weather_sensor": self.bme.available,
            "compass": self.compass.available, "start_view": self.config["start_view"],
            "track_km": round(track_length_m(self.gps.track) / 1000, 2),
            "battery": self.battery_state, "manual_pos": self.get_setting("manual_pos"),
            "time": time.time(),
        }

    def _raster_attribution(self):
        db = self.mbtiles()
        if db is None:
            return None
        try:
            r = db.execute("SELECT value FROM metadata WHERE name='attribution'").fetchone()
        except sqlite3.OperationalError:
            return None
        return r[0] if r else None

    # --- radio -----------------------------------------------------------
    def radio_action(self, a):
        r = self.radio
        if not r.available:
            return r.status()
        if self.shortwave.job:
            return dict(r.status(), busy="Receiving %s: stop it first" % self.shortwave.job["name"])
        act = a.get("action")
        if act == "band":
            r.set_band(a["band"])
        elif act == "tune":
            r.tune(a["freq"])
        elif act == "step":
            r.step(int(a.get("dir", 1)))
        elif act == "seek":
            r.seek(int(a.get("dir", 1)) > 0)
        elif act == "volume":
            r.set_volume(a["volume"])
            self.set_setting("radio_volume", r.volume)
        elif act == "bfo":
            r.set_bfo(a["bfo"])
        elif act == "mute":
            r.mute(bool(a.get("on")))
        elif act == "scan":
            return {"stations": self.radio_scan()}
        st = r.status()
        if act in ("band", "tune", "step", "seek"):
            self.set_setting("radio_last", {"band": st["band"], "freq": st["freq"]})
        return st

    def radio_scan(self):
        """Seek through the current band once and save every station found as a preset."""
        r = self.radio
        start = r.status()["freq"]
        seen = []
        for _ in range(60):
            st = r.seek(True)
            if st["freq"] in [s["freq"] for s in seen] or (seen and st["freq"] <= seen[-1]["freq"]):
                break
            if st["valid"]:
                seen.append(st)
        db = self.user()
        for st in seen:
            if not db.execute("SELECT 1 FROM radio_presets WHERE band=? AND freq=?",
                              (st["band"], st["freq"])).fetchone():
                db.execute("INSERT INTO radio_presets(name,band,freq) VALUES(?,?,?)",
                           (st.get("rds") or st["label"], st["band"], st["freq"]))
        db.commit()
        r.tune(start)
        return seen


class Handler(BaseHTTPRequestHandler):
    app = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _allowed(self):
        """The device's own screen always; other computers only over the device's own hotspot.
        (When the device has joined some other WiFi network, nobody there can reach it.)"""
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            return True
        if ip.startswith(hotspot_mod.HOTSPOT_PREFIX) and self.app.hotspot.started:
            self.app.hotspot.touch()
            return True
        self._send(403, "Connect through the device's own WiFi hotspot (Share on the device).", "text/plain")
        return False

    def _local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _download(self, data, filename, ctype):
        if isinstance(data, str):
            data = data.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % filename)
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self):
        """Streaming upload from the Files page: PUT /api/upload?name=nav.db"""
        if not self._allowed():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path != "/api/upload":
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length") or 0)
            result = exports.receive_upload(self.app, q.get("name", ""), self.rfile, n)
            return self._send(200, result)
        except ValueError as e:
            # drain what the client is still sending so it sees the error
            return self._send(400, {"error": str(e)})
        except OSError as e:
            return self._send(500, {"error": str(e)})

    def _send(self, code, body, ctype="application/json", cache=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, separators=(",", ":")).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        app = self.app
        if not self._allowed():
            return
        try:
            if p == "/files":
                return self._static("files.html")
            if p.startswith("/kiwix/"):
                return app.kiwix.proxy(self, self.path)
            if p.startswith("/media/"):
                return self._media(p[len("/media/"):])
            if p == "/api/hotspot":
                return self._send(200, app.hotspot.status())
            if p == "/api/files":
                return self._send(200, exports.file_list(app))
            if p.startswith("/api/export/"):
                name = p[len("/api/export/"):]
                data, ctype = exports.export(app, name)
                if data is None:
                    return self._send(404, {"error": "nothing to export"})
                return self._download(data, name, ctype)
            if p == "/" or p.startswith("/static/"):
                return self._static("index.html" if p == "/" else p[len("/static/"):])
            if p.startswith("/vt/"):
                z, x, y = (int(v) for v in p[4:].split("/"))
                data = app.vector_tile(z, x, y)
                # revalidate every time (cheap on the device), and never keep an empty tile:
                # a tile fetched before nav.db existed would otherwise stay blank in the browser
                empty = not any(data.get(k) for k in ("lines", "areas", "places", "pois"))
                return self._send(200, data, cache="no-store" if empty else "no-cache")
            if p.startswith("/tiles/"):
                return self._raster(p)
            if p == "/api/status":
                return self._send(200, app.status())
            if p == "/api/gps":
                f = app.gps.get()
                return self._send(200, dict(f, manual_pos=app.get_setting("manual_pos"), dr=app.dr.estimate(),
                                           gps_suspect=not app.ins.gps_trusted(f), ins=app.ins.status(), **app.heading()))
            if p == "/api/ins":
                return self._send(200, app.ins.status())
            if p == "/api/dr":
                return self._send(200, app.dr.status())
            if p == "/api/track":
                pts = sorted(list(app.gps.track) + list(app.dr.track))  # GPS fixes + estimated points
                return self._send(200, [[t[1], t[2]] for t in pts])
            if p == "/api/nearest":
                pos = (float(q["lat"]), float(q["lon"])) if "lat" in q else app.position()
                if not pos:
                    return self._send(200, {"error": "No position: set one on the map or wait for GPS"})
                return self._send(200, app.nearest(pos[0], pos[1], q.get("cat") or None,
                                                   int(q.get("limit", 10))))
            if p == "/api/search":
                pos = app.position()
                return self._send(200, app.search(q.get("q", ""), *(pos or (None, None))))
            if p == "/api/waypoints":
                rows = app.user().execute(
                    "SELECT id,name,lat,lon,icon,note,created FROM waypoints ORDER BY created DESC").fetchall()
                keys = ("id", "name", "lat", "lon", "icon", "note", "created")
                pos = app.position()
                out = []
                for r in rows:
                    d = dict(zip(keys, r))
                    if pos:
                        d["dist_m"] = round(geo.haversine(pos[0], pos[1], d["lat"], d["lon"]))
                        d["bearing"] = round(geo.bearing(pos[0], pos[1], d["lat"], d["lon"]))
                    out.append(d)
                return self._send(200, out)
            if p == "/api/library":
                return self._send(200, app.library.index())
            if p == "/api/library/page":
                pg = app.library.page(q.get("id", ""))
                return self._send(200 if pg else 404, pg or {"error": "not found"})
            if p == "/api/library/search":
                return self._send(200, app.finder.guide_search(q.get("q", "")))
            if p == "/api/find":
                pos = app.position()
                return self._send(200, app.finder.find(q.get("q", ""), *(pos or (None, None))))
            if p == "/api/find/wiki":
                return self._send(200, app.kiwix.find(q["book"], q["q"], int(q.get("count", 8))))
            if p == "/api/books":
                return self._send(200, {"books": app.kiwix.books(max_age=0),
                                        "videos": len(app.finder.video_files),
                                        "languages": [[l, LANG_NAMES[l]] for l in LANGS]})
            if p == "/api/weather":
                pos = app.position()
                rep = app.weather.report(latitude=pos[0] if pos else None)
                rep["history"] = [[r[0], r[1], r[2]] for r in app.weather.history(48)[::3]]
                return self._send(200, rep)
            if p == "/api/forecast":
                return self._send(200, dict(app.forecast.report(), enabled=app.config["forecast_auto_download"]))
            if p == "/api/radio":
                st = app.radio.status()
                st["presets"] = [dict(zip(("id", "name", "band", "freq"), r)) for r in app.user().execute(
                    "SELECT id,name,band,freq FROM radio_presets ORDER BY band, freq")]
                st["bands"] = list(app.radio.bands)
                if app.shortwave.job:
                    st["busy"] = "Receiving " + app.shortwave.job["name"]
                return self._send(200, st)
            if p == "/api/air":
                return self._send(200, app.airband.status())
            if p == "/api/light":
                return self._send(200, app.light.status())
            if p == "/api/mesh":
                return self._send(200, app.mesh.status())
            if p == "/api/sw":
                return self._send(200, app.shortwave.status())
            if p.startswith("/sw/"):
                return self._sw_file(p[4:])
            if p == "/api/convert":
                lat, lon = float(q["lat"]), float(q["lon"])
                return self._send(200, {"utm": geo.to_mgrs_like(lat, lon), "dms": _dms(lat, lon)})
            return self._send(404, {"error": "not found"})
        except (KeyError, ValueError) as e:
            return self._send(400, {"error": "bad request: %s" % e})
        except OSError as e:
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        app = self.app
        p = urlparse(self.path).path
        if not self._allowed():
            return
        try:
            b = self._body()
            if p == "/api/hotspot":
                act = b.get("action")
                if act == "on":
                    return self._send(200, app.hotspot.on())
                if act == "off":
                    return self._send(200, app.hotspot.off())
                if act == "newpass" and self._local():
                    return self._send(200, app.hotspot.new_password())
                return self._send(400, {"error": "unknown action"})
            if p == "/api/waypoints":
                db = app.user()
                if b.get("id"):
                    db.execute("UPDATE waypoints SET name=?, note=?, icon=? WHERE id=?",
                               (b.get("name"), b.get("note"), b.get("icon"), b["id"]))
                    wid = b["id"]
                else:
                    if "lat" not in b:
                        pos = app.position()
                        if not pos:
                            return self._send(400, {"error": "no GPS fix"})
                        b["lat"], b["lon"] = pos
                    cur = db.execute("INSERT INTO waypoints(name,lat,lon,icon,note,created) VALUES(?,?,?,?,?,?)",
                                     (b.get("name") or time.strftime("WP %d-%m %H:%M"), float(b["lat"]),
                                      float(b["lon"]), b.get("icon", "pin"), b.get("note", ""), time.time()))
                    wid = cur.lastrowid
                db.commit()
                return self._send(200, {"id": wid})
            if p == "/api/waypoints/delete":
                app.user().execute("DELETE FROM waypoints WHERE id=?", (int(b["id"]),))
                app.user().commit()
                return self._send(200, {"ok": True})
            if p == "/api/radio":
                return self._send(200, app.radio_action(b))
            if p == "/api/radio/preset":
                db = app.user()
                if b.get("delete"):
                    db.execute("DELETE FROM radio_presets WHERE id=?", (int(b["delete"]),))
                else:
                    st = app.radio.status()
                    db.execute("INSERT INTO radio_presets(name,band,freq) VALUES(?,?,?)",
                               (b.get("name") or st.get("rds") or st.get("label"), st["band"], st["freq"]))
                db.commit()
                return self._send(200, {"ok": True})
            if p == "/api/sw/receive":
                try:
                    return self._send(200, {"job": app.shortwave.receive(b["station"], int(b.get("minutes", 12)))})
                except RuntimeError as e:
                    return self._send(200, {"error": str(e)})
            if p == "/api/air":
                act = b.get("action")
                try:
                    if act == "listen":
                        return self._send(200, app.airband.listen(b["mhz"], b.get("squelch", "low")))
                    if act == "stop":
                        app.airband.stop()
                    elif act == "add":
                        app.airband.add_freq(b.get("name"), b["mhz"])
                    elif act == "remove":
                        app.airband.remove_freq(b["mhz"])
                except RuntimeError as e:
                    return self._send(200, dict(app.airband.status(), error=str(e)))
                return self._send(200, app.airband.status())
            if p == "/api/mesh":
                act = b.get("action")
                try:
                    if act == "send":
                        app.mesh.send_text(b.get("text"))
                    elif act == "position":
                        app.mesh.share_position()
                except (ValueError, RuntimeError) as e:
                    return self._send(200, dict(app.mesh.status(), error=str(e)))
                return self._send(200, app.mesh.status())
            if p == "/api/light":
                if "sos" in b:
                    return self._send(200, app.light.set_sos(b["sos"]))
                return self._send(200, app.light.set(b["which"], b.get("on"), b.get("brightness")))
            if p == "/api/sw/stop":
                app.shortwave.stop()
                return self._send(200, {"ok": True})
            if p == "/api/sw/schedule":
                if b.get("delete"):
                    return self._send(200, app.shortwave.remove_schedule(b["delete"]))
                return self._send(200, app.shortwave.add_schedule(b["time"], b["station"], b.get("minutes", 12)))
            if p == "/api/sw/delete":
                return self._send(200, {"ok": app.shortwave.delete(b["id"])})
            if p == "/api/dr":
                app.dr.set_mode(b["mode"], b.get("speed_kn"), b.get("course"))
                return self._send(200, app.dr.status())
            if p == "/api/ins":
                act = b.get("action")
                if act == "realign":
                    app.ins.realign()
                elif act == "trust_gps":
                    app.ins.trust_gps()
                elif act == "heading":
                    app.ins.set_heading(float(b["deg"]))
                else:
                    return self._send(400, {"error": "bad request: unknown action"})
                return self._send(200, app.ins.status())
            if p == "/api/position":
                if b.get("clear"):
                    app.set_setting("manual_pos", None)
                else:
                    if "text" in b:
                        b["lat"], b["lon"] = geo.parse_coords(b["text"])
                    lat, lon = float(b["lat"]), float(b["lon"])
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError("position out of range")
                    app.set_setting("manual_pos", {"lat": lat, "lon": lon, "set": time.time()})
                return self._send(200, {"manual_pos": app.get_setting("manual_pos")})
            if p == "/api/clock":
                return self._send(200, {"changed_s": app.set_clock(float(b["epoch"]))})
            if p == "/api/compass/calibrate":
                if b.get("start"):
                    app.compass.start_calibration()
                    return self._send(200, {"calibrating": True})
                cal = app.compass.finish_calibration()
                app.set_setting("compass_cal", cal)
                return self._send(200, {"calibration": cal})
            if p == "/api/forecast/update":
                err = app.forecast.update()
                return self._send(200, app.forecast.report() if not err else {"error": err})
            if p == "/api/weather/sample":
                return self._send(200, app.weather.sample() or {"error": "no sensor"})
            if p == "/api/find/reload":
                app.library.reload()
                app.finder.reload()
                return self._send(200, {"guide": len(app.finder.guide.docs), "videos": len(app.finder.video_files),
                                        "books": len(app.kiwix.books(max_age=0))})
            return self._send(404, {"error": "not found"})
        except (KeyError, ValueError, TypeError) as e:
            return self._send(400, {"error": "bad request: %s" % e})
        except OSError as e:
            return self._send(500, {"error": str(e)})

    def _static(self, name):
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self._send(404, "not found", "text/plain")
        ext = os.path.splitext(path)[1]
        ctype = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
                 ".svg": "image/svg+xml", ".png": "image/png"}.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype, cache="no-cache")

    def _media(self, vid):
        """Video files with Range support, so the player can seek."""
        path = self.app.finder.video_files.get(vid)
        if not path or not os.path.isfile(path):
            return self._send(404, "not found", "text/plain")
        size = os.path.getsize(path)
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        else:
            self.send_response(200)
        ext = os.path.splitext(path)[1].lower()
        self.send_header("Content-Type", {".webm": "video/webm", ".ogv": "video/ogg", ".mkv": "video/x-matroska"}
                         .get(ext, "video/mp4"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(256 * 1024, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except ConnectionError:  # the player jumped elsewhere and closed this request
                    self.close_connection = True
                    return
                left -= len(chunk)

    def _sw_file(self, name):
        name = os.path.basename(name)
        path = os.path.join(self.app.shortwave.out_dir, name)
        if not os.path.isfile(path) or not name.endswith((".png", ".txt")):
            return self._send(404, "not found", "text/plain")
        with open(path, "rb") as f:
            data = f.read()
        ctype = "image/png" if name.endswith(".png") else "text/plain; charset=utf-8"
        self._send(200, data, ctype, cache="max-age=86400")

    def _raster(self, p):
        db = self.app.mbtiles()
        if db is None:
            return self._send(404, "", "text/plain")
        z, x, y = (int(v.split(".")[0]) for v in p[len("/tiles/"):].split("/"))
        row = db.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                         (z, x, (2 ** z - 1) - y)).fetchone()  # MBTiles uses TMS rows
        if not row:
            return self._send(404, "", "text/plain")
        data = row[0]
        ctype = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg" if data[:2] == b"\xff\xd8" else "image/webp"
        return self._send(200, data, ctype, cache="no-cache")


def _dms(lat, lon):
    def f(v, pos, neg):
        h = pos if v >= 0 else neg
        v = abs(v)
        d = int(v)
        m = int((v - d) * 60)
        s = (v - d - m / 60) * 3600
        return "%d°%02d'%04.1f\"%s" % (d, m, s, h)
    return "%s %s" % (f(lat, "N", "S"), f(lon, "E", "W"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "..", "data"))
    ap.add_argument("--port", type=int)
    ap.add_argument("--host", default="0.0.0.0", help="other computers are still only let in over the hotspot")
    args = ap.parse_args()
    app = App(os.path.abspath(args.data))
    Handler.app = app
    port = args.port or app.config["port"]
    srv = ThreadingHTTPServer((args.host, port), Handler)
    print("Doomsday computer running on http://%s:%d  (nav db: %s, radio: %s, weather: %s, compass: %s)" % (
        args.host, port, os.path.exists(app.nav_path), app.radio.available, app.bme.available,
        app.compass.available), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
