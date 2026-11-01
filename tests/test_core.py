"""Run with:  python3 -m unittest discover tests   (no hardware needed)"""
import ctypes
import datetime as dt
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import geo  # noqa: E402
import forecast  # noqa: E402
import radio  # noqa: E402
import radio_rda5807  # noqa: E402
import radio_si4732 as si  # noqa: E402
import weather  # noqa: E402
from gps import GPS  # noqa: E402
from library import Library  # noqa: E402


class GeoTest(unittest.TestCase):
    def test_encode_roundtrip(self):
        parts = [[(5.123456, 52.654321), (5.2, 52.7)], [(0.0, 0.0), (-1.5, -2.5), (3, 4)]]
        out = geo.decode(geo.encode(parts))
        self.assertEqual(out[0], [5.123456, 52.654321, 5.2, 52.7])
        self.assertEqual(len(out[1]), 6)

    def test_distance_bearing(self):
        # Amsterdam Centraal -> Utrecht Centraal is about 35 km SSE
        d = geo.haversine(52.3791, 4.9003, 52.0894, 5.1100)
        self.assertAlmostEqual(d / 1000, 35.2, delta=0.5)
        self.assertAlmostEqual(geo.bearing(52.3791, 4.9003, 52.0894, 5.1100), 155, delta=3)

    def test_simplify_keeps_ends(self):
        pts = [(5 + i * 1e-5, 52 + (1e-7 if i % 2 else 0)) for i in range(100)]
        s = geo.simplify(pts, 1.0)
        self.assertEqual(s[0], pts[0])
        self.assertEqual(s[-1], pts[-1])
        self.assertLess(len(s), 5)

    def test_utm(self):
        # Dom tower Utrecht, known UTM 31U ~ 645 km E, 5773 km N
        u = geo.to_mgrs_like(52.0907, 5.1214)
        zone, e, n = re.match(r"(\d+\w) (\d+) E (\d+) N", u).groups()
        self.assertEqual(zone, "31U")
        self.assertAlmostEqual(int(e), 645300, delta=1500)
        self.assertAlmostEqual(int(n), 5773300, delta=1500)

    def test_sun(self):
        st = geo.sun_times(52.1, 5.3, dt.date(2026, 6, 21))
        self.assertEqual(st["sunrise"].hour, 3)   # ~05:20 CEST = 03:20 UTC
        self.assertEqual(st["sunset"].hour, 20)   # ~22:00 CEST = 20:00 UTC


class GPSTest(unittest.TestCase):
    def test_nmea(self):
        g = GPS()
        g.parse_nmea("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
        f = g.get()
        self.assertAlmostEqual(f["lat"], 48.1173, places=4)
        self.assertAlmostEqual(f["lon"], 11.516667, places=4)
        self.assertEqual(f["sats"], 8)
        g.parse_nmea("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*48")  # bad checksum
        self.assertEqual(g.get()["sats"], 8)


class WeatherTest(unittest.TestCase):
    def test_zambretti(self):
        self.assertIn("fine", weather.zambretti(1035, 0, 7)[1].lower())
        self.assertIn("storm", weather.zambretti(965, -5, 1)[1].lower())

    def test_report_from_fake_sensor(self):
        class Fake:
            available = True
            p = 1015.0

            def read(self):
                self.p -= 1.0
                return {"temp_c": 12.0, "pressure_hpa": self.p, "humidity": 80.0}

        with tempfile.TemporaryDirectory() as d:
            ws = weather.WeatherStation(Fake(), os.path.join(d, "w.db"), altitude_m=0)
            now = time.time()
            db = sqlite3.connect(ws.db_path)
            for i in range(7):  # one reading per 30 min, falling 1 hPa each
                db.execute("INSERT INTO weather VALUES(?,?,?,?)", (now - (6 - i) * 1800, 12.0, 1010 - i, 80))
            db.commit()
            r = ws.report()
            self.assertEqual(r["tendency"], "falling")
            self.assertAlmostEqual(r["trend_hpa_3h"], -6.0, delta=0.2)
            self.assertTrue(any("storm" in w.lower() or "fast" in w.lower() for w in r["warnings"]))


class FakeSiBus:
    """Pretends to be an Si4732: always clear-to-send, tune complete, freq echoed back."""

    def __init__(self):
        self.freq = 0
        self.writes = []
        self.last = None

    def i2c_rdwr(self, msg):
        if msg.flags == 0:  # write
            data = list(msg)
            self.writes.append(data)
            self.last = data[0]
            if data[0] in (si.FM_TUNE_FREQ, si.AM_TUNE_FREQ):
                self.freq = (data[2] << 8) | data[3]
        else:
            n = msg.len
            resp = [0x81] + [0] * (n - 1)
            if self.last in (si.FM_TUNE_STATUS, si.AM_TUNE_STATUS):
                resp[1] = 1
                resp[2], resp[3] = self.freq >> 8, self.freq & 0xFF
                resp[4], resp[5] = 30, 12
            ctypes.memmove(msg.buf, bytes(resp), n)


@unittest.skipIf(si.i2c_msg is None, "smbus2 not installed")
class RadioTest(unittest.TestCase):
    def test_tune_fm_and_am(self):
        bus = FakeSiBus()
        r = si.Si4732(bus, reset_gpio=None)
        self.assertTrue(r.available, r.error)
        st = r.tune(10170)
        self.assertEqual(st["label"], "101.7 MHz")
        self.assertIn([si.POWER_UP, 0x10, 0x05], bus.writes)
        r.set_band("MW")
        st = r.tune(747)
        self.assertEqual(st["label"], "747 kHz")
        self.assertIn([si.POWER_UP, 0x11, 0x05], bus.writes)
        st = r.tune(99999)  # clamped to band
        self.assertEqual(st["freq"], 1710)


@unittest.skipIf(si.i2c_msg is None, "smbus2 not installed")
class SsbTest(unittest.TestCase):
    def test_patch_and_usb_tune(self):
        with tempfile.TemporaryDirectory() as d:
            patch = os.path.join(d, "ssb_patch.bin")
            rows = [[0x15, 0, 0x0F, 0xE0, 0xF2, 0x73, 0x76, 0x2F]] + [[0x16] + [i % 256] * 7 for i in range(20)] + \
                [[0x15, 0, 0, 0, 0, 0, 0x9D, 0x29]]
            with open(patch, "wb") as f:
                f.write(bytes(sum(rows, [])))
            bus = FakeSiBus()
            r = si.Si4732(bus, reset_gpio=None, ssb_patch=patch)
            self.assertIn("USB", r.bands)
            r.set_band("USB")
            st = r.tune(7878)
            self.assertEqual(st["label"], "7878 kHz USB")
            self.assertIn([si.POWER_UP, 0x31, 0x05], bus.writes)  # patch-enabled power up
            for row in rows:
                self.assertIn(row, bus.writes)
            self.assertIn([si.SET_PROPERTY, 0, 0x01, 0x01, 0x80, 0x12], bus.writes)  # SSB_MODE
            self.assertIn([si.AM_TUNE_FREQ, 0x81, 7878 >> 8, 7878 & 0xFF, 0, 0], bus.writes)  # USB
            n_power = sum(1 for w in bus.writes if w[0] == si.POWER_UP)
            r.set_band("LSB")  # same patched firmware: no new power-up
            self.assertEqual(n_power, sum(1 for w in bus.writes if w[0] == si.POWER_UP))
            r.set_bfo(-250)
            self.assertIn([si.SET_PROPERTY, 0, 0x01, 0x00, 0xFF, 0x06], bus.writes)
            r.set_band("FM")
            self.assertEqual(r.status()["mode"], "fm")

    def test_no_patch_no_ssb(self):
        r = si.Si4732(FakeSiBus(), reset_gpio=None, ssb_patch="/nonexistent")
        self.assertNotIn("USB", r.bands)

    def test_patch_converter(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import get_ssb_patch
        text = "/* x */ const PROGMEM uint8_t ssb_patch_content[] = { 0x15, 0x00, 0x0F, 0xE0, 0xF2, 0x73, 0x76, 0x2F,\n" \
               "0x16, 0x6F, 0x26, 0x1E, 0x00, 0x4B, 0x2C, 0x58,\n 0x15, 0, 0x00, 0x00, 0x00, 0x00, 0x9D, 0x29};"
        with self.assertRaises(ValueError):  # a bare 0 is not a valid byte entry
            get_ssb_patch.convert(text)
        data = get_ssb_patch.convert(text.replace(" 0x15, 0, ", " 0x15, 0x00, "))
        self.assertEqual(len(data), 24)
        self.assertEqual(data[-2:], bytes([0x9D, 0x29]))


class ShortwaveJobTest(unittest.TestCase):
    """A whole reception with a fake radio and a fake sound stick that 'hears' a fax."""

    def test_receive_fax(self):
        import numpy as np
        import wave
        import audio
        import shortwave
        import wefax

        self.assertEqual(shortwave.dial_for(3855.0), (3853, 2000.0))
        self.assertEqual(shortwave.dial_for(13882.5), (13881, 1500.0))

        class Radio:
            available = True
            bands = {"FM": 0, "USB": 0}
            volume = 30

            def __init__(self):
                self.band, self.freq, self.log = "FM", 9800, []

            def status(self):
                return {"band": self.band, "freq": self.freq, "rssi": 25, "snr": 10}

            def set_band(self, b):
                self.band = b
                self.log.append(("band", b))

            def tune(self, f):
                self.freq = f
                self.log.append(("tune", f))

            def set_bfo(self, v):
                pass

            def set_volume(self, v):
                self.volume = v

        img = np.full((150, wefax.WIDTH), 235, np.uint8)
        img[40:110, 400:1000] = 10
        fs = audio.RATE
        sig = wefax.synthesize(img, fs, centre=2000 + 90)  # radio a bit off frequency
        sig = sig + np.random.default_rng(3).normal(0, .15, len(sig))
        sig = sig / np.abs(sig).max()

        class FakeRec:
            def __init__(self, device, path, seconds, rate=fs):
                self.path, self.error, self.done = path, None, __import__("threading").Event()

            def start(self):
                with wave.open(self.path, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(fs)
                    w.writeframes((sig * 20000).astype("<i2").tobytes())
                self.done.set()
                return self

            def stop(self):
                pass

            def level(self):
                return 0.5

        class FakeApp:
            radio = Radio()
            settings = {}

            def get_setting(self, k):
                return self.settings.get(k)

            def set_setting(self, k, v):
                self.settings[k] = v

        orig = audio.find_device, audio.Recorder
        audio.find_device, audio.Recorder = (lambda setting="auto": "plughw:9,0"), FakeRec
        try:
            with tempfile.TemporaryDirectory() as d:
                app = FakeApp()
                sw = shortwave.Shortwave(app, d)
                self.assertTrue(sw.ready()[0])
                sw.receive("dwd-fax-7880", minutes=3)
                with self.assertRaises(RuntimeError):
                    sw.receive("dwd-fax-3855")  # busy
                for _ in range(300):
                    if sw.job is None:
                        break
                    time.sleep(0.2)
                self.assertIsNone(sw.job)
                self.assertTrue(sw.last["ok"], sw.last)
                res = sw.results()
                self.assertEqual(len(res), 1)
                self.assertTrue(os.path.exists(os.path.join(d, res[0]["small"])))
                self.assertFalse([n for n in os.listdir(d) if n.endswith(".wav")])  # recording removed
                self.assertIn(("tune", 7878), app.radio.log)
                self.assertEqual((app.radio.band, app.radio.freq, app.radio.volume), ("FM", 9800, 30))  # put back
                sw.add_schedule("06:30", "dwd-rtty-7646", 10)
                self.assertEqual(sw.schedule()[0]["time"], "06:30")
                with self.assertRaises(ValueError):
                    sw.add_schedule("25:00", "dwd-rtty-7646", 10)
                self.assertTrue(sw.delete(res[0]["id"]))
                self.assertEqual(sw.results(), [])
        finally:
            audio.find_device, audio.Recorder = orig


class DeadReckoningTest(unittest.TestCase):
    def test_parse_coords(self):
        for t in ("52.3702 4.8952", "52 22.212 N 4 53.712 E", "N 52 22.212 E 004 53.712", "52°22'12.7\"N 4°53'42.7\"E",
                  geo.to_mgrs_like(52.3702, 4.8952)):
            lat, lon = geo.parse_coords(t)
            self.assertAlmostEqual(lat, 52.3702, delta=2e-4, msg=t)
            self.assertAlmostEqual(lon, 4.8952, delta=2e-4, msg=t)
        self.assertEqual(geo.parse_coords("33 55.2 S 18 25.2 E"), (-33.92, 18.42))
        for bad in ("hello", "52", "95 4", "52 61 N 4 0 E"):
            with self.assertRaises(ValueError):
                geo.parse_coords(bad)

    def test_imu_clone_on_0x69(self):
        import deadreck

        class Bus:
            def read_byte_data(self, a, r):
                if a == 0x69 and r == 0x75:
                    return 0x70  # an "MPU-6050" board that is really an MPU-6500
                if a == 0x68:
                    return 0x00  # the DS3231 clock answers on 0x68
                raise OSError

            def write_byte_data(self, a, r, v):
                pass

            def read_i2c_block_data(self, a, r, n):
                return [0, 0, 0, 0, 0x40, 0]  # z = +1 g

        imu = deadreck.IMU(Bus())
        self.assertTrue(imu.available)
        self.assertEqual((imu.addr, imu.model), (0x69, "MPU-6500"))
        self.assertEqual(imu.accel(), (0.0, 0.0, 1.0))

    def test_steps_from_walking_signal(self):
        import math as m
        import deadreck
        sd = deadreck.StepDetector()
        n = 0
        for i in range(50 * 20):  # 20 s at 50 Hz, 1.8 steps/s, plus a little jitter
            t = i / 50
            a = 1 + 0.3 * m.sin(2 * m.pi * 1.8 * t) + 0.03 * m.sin(2 * m.pi * 13 * t)
            n += sd.feed(t, 0, 0, a)
        self.assertAlmostEqual(n, 36, delta=2)
        still = deadreck.StepDetector()
        self.assertEqual(sum(still.feed(i / 50, 0, 0, 1 + 0.02 * m.sin(i)) for i in range(500)), 0)

    def _dr(self, fix, heading=90.0):
        import deadreck
        st = {}
        dr = deadreck.DeadReckoner(None, lambda: fix[0], lambda: heading, lambda: st.get("manual_pos"),
                                   (st.get, st.__setitem__))
        return dr, st

    def test_on_foot(self):
        fix = [{"mode": 3, "lat": 52.0, "lon": 5.0, "speed": 1.2, "track": 90, "hdop": 1.0}]
        dr, st = self._dr(fix)
        dr.tick()
        self.assertIsNone(dr.estimate())  # GPS is fine: no estimate needed
        fix[0] = {"mode": 1}  # GPS lost
        dr.tick()
        for _ in range(100):
            dr.on_step()
        e = dr.estimate()
        self.assertAlmostEqual(geo.haversine(52.0, 5.0, e["lat"], e["lon"]), 72, delta=1)
        self.assertAlmostEqual(geo.bearing(52.0, 5.0, e["lat"], e["lon"]), 90, delta=1)
        self.assertEqual(e["err_m"], round(10 + 0.05 * 72))
        # typed coordinates restart the estimate there
        st["manual_pos"] = {"lat": 52.1, "lon": 5.1, "set": time.time() + 1}
        dr.tick()
        e = dr.estimate()
        self.assertEqual((e["lat"], e["lon"], e["from"]), (52.1, 5.1, "manual"))

    def test_boat(self):
        fix = [{"mode": 3, "lat": 50.0, "lon": -10.0, "speed": 3.0, "track": 0.0}]
        dr, st = self._dr(fix)
        dr.set_mode("boat")
        dr.tick(1000.0)
        fix[0] = {"mode": 1}
        for k in range(1, 11):
            dr.tick(1000.0 + k)  # 10 s at the last GPS speed and course: 30 m north
        e = dr.estimate()
        self.assertAlmostEqual((e["lat"] - 50.0) * 111320, 30, delta=0.5)
        dr.set_mode("boat", speed_kn=10, course=270)  # entered by hand
        dr.tick(1011.0)
        self.assertAlmostEqual(e["lon"] - dr.estimate()["lon"], 5.144 / (111320 * m_cos(50)), delta=1e-6)

    def test_airband_freq_list(self):
        import airband
        st = {}
        a = airband.Airband(st.get, st.__setitem__)
        a.add_freq("Tower", "118.275")
        self.assertIn({"name": "Tower", "mhz": 118.275}, a.freqs())
        with self.assertRaises(ValueError):
            a.add_freq("FM", 99.0)
        a.remove_freq(118.275)
        self.assertNotIn(118.275, [f["mhz"] for f in a.freqs()])
        self.assertIn("ready", a.status())


class LightTest(unittest.TestCase):
    def test_torch_with_fake_gpio(self):
        import types
        import light
        calls = []
        fake = types.SimpleNamespace(
            gpiochip_open=lambda n: 7, gpio_claim_output=lambda h, p, v: calls.append(("claim", p)),
            tx_pwm=lambda h, p, f, d: calls.append(("pwm", p, d)), gpio_write=lambda h, p, v: calls.append(("w", p, v)))
        orig, light.lgpio = light.lgpio, fake
        try:
            L = light.Light(12, 13)
            self.assertTrue(L.available)
            L.set("white", True)
            self.assertIn(("w", 12, 1), calls)
            L.set("red", True, 30)
            self.assertIn(("pwm", 13, 30), calls)
            L.set_sos(True)
            time.sleep(0.5)
            L.set_sos(False)
            time.sleep(0.5)
            self.assertTrue(L.status()["white"]["on"])
            self.assertEqual(calls[-1][:2], ("w", 12))  # back to steady light after SOS
            with self.assertRaises(ValueError):
                L.set("blue", True)
        finally:
            light.lgpio = orig


def m_cos(deg):
    import math
    return math.cos(math.radians(deg))


class MeshTest(unittest.TestCase):
    def test_messages_and_limits(self):
        import mesh
        m = mesh.Mesh("auto", get_position=lambda: (52.37, 4.89))
        m.available = True  # pretend the meshtastic package is installed
        class Node:
            localNode = type("L", (), {"sendPosition": lambda self, la, lo: None})()
            nodes = {"!a1": {"user": {"longName": "Hut 2"}, "snr": 5, "lastHeard": 1}}
            sent = []
            def sendText(self, t): self.sent.append(t)
        m.iface = Node()
        m._on_text({"fromId": "!b2", "decoded": {"text": "water at the creek"}, "rxSnr": 3.5})
        m.send_text("on my way")
        self.assertEqual([x["text"] for x in m.status()["messages"]], ["water at the creek", "on my way"])
        self.assertEqual(m.status()["nodes"][0]["name"], "Hut 2")
        m.share_position()
        self.assertIn("My position: 52.37000, 4.89000", m.iface.sent)
        with self.assertRaises(ValueError):
            m.send_text("x" * 300)
        with self.assertRaises(ValueError):
            m.send_text("   ")
        m2 = mesh.Mesh("auto")
        self.assertFalse(m2.status()["available"])
        with self.assertRaises(RuntimeError):
            m2.send_text("hi")  # no node connected


class AirAndUvTest(unittest.TestCase):
    def test_uv_index_from_fake_ltr390(self):
        import sensors

        class Bus:
            regs = {0x06: 0xB2}
            def read_byte_data(self, a, r): return self.regs[r]
            def write_byte_data(self, a, r, v): pass
            def read_i2c_block_data(self, a, r, n): return [0x40, 0x0D, 0x03]  # raw 0x030D40
        uv = sensors.UVSensor(Bus())
        self.assertTrue(uv.available)
        self.assertAlmostEqual(uv.index(), round(0x030D40 / 2300.0, 1))
        self.assertFalse(sensors.UVSensor(None).available)

    def test_bme680_absent_is_harmless(self):
        import sensors
        s = sensors.BME680(None)
        self.assertFalse(s.available)
        self.assertIsNone(s.read())


class FakeRdaBus:
    """Pretends to be an RDA5807M: 16-bit registers, tune/seek complete at once."""

    def __init__(self):
        self.regs = {0x00: 0x5804, 0x0A: 0, 0x0B: (40 << 9) | 0x0100}

    def write_i2c_block_data(self, addr, reg, data):
        value = (data[0] << 8) | data[1]
        self.regs[reg] = value
        if reg == 0x03 and value & radio_rda5807.TUNE:
            self.regs[0x0A] = radio_rda5807.STC | (value >> 6)
        if reg == 0x02 and value & radio_rda5807.SEEK:
            chan = (self.regs[0x0A] & 0x3FF) + (7 if value & radio_rda5807.SEEKUP else -7)
            self.regs[0x0A] = radio_rda5807.STC | chan

    def read_i2c_block_data(self, addr, reg, n):
        v = self.regs.get(reg, 0)
        return [v >> 8, v & 0xFF]


class RdaRadioTest(unittest.TestCase):
    def test_fm(self):
        bus = FakeRdaBus()
        r = radio.open_radio(bus, "rda5807m")
        self.assertTrue(r.available, getattr(r, "error", None))
        st = r.tune(10170)
        self.assertEqual(st["label"], "101.7 MHz")
        self.assertEqual(bus.regs[0x03] >> 6, 147)  # (101.7 - 87.0) / 0.1
        self.assertEqual(st["rssi"], 40)
        self.assertEqual(r.seek(True)["freq"], 10240)
        self.assertEqual(r.tune(5000)["freq"], 8700)  # clamped to band
        r.set_volume(99)
        self.assertEqual(bus.regs[0x05] & 0x0F, 15)
        with self.assertRaises(ValueError):
            r.set_band("MW")

    def test_wrong_chip(self):
        bus = FakeRdaBus()
        bus.regs[0x00] = 0x1234
        r = radio.open_radio(bus, "rda5807m")
        self.assertFalse(r.available)
        self.assertIn("not an RDA5807M", r.error)


class ForecastTest(unittest.TestCase):
    def test_download_and_report(self):
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import fake_openmeteo
        srv = fake_openmeteo.start()
        old = forecast.API
        forecast.API = "http://127.0.0.1:%d/v1/forecast" % srv.server_port
        try:
            with tempfile.TemporaryDirectory() as d:
                f = forecast.Forecaster(os.path.join(d, "u.db"), lambda: (52.1, 5.3))
                self.assertIn("message", f.report())
                self.assertIsNone(f.update())
                r = f.report()
                self.assertEqual(len(r["days"]), 16)
                self.assertEqual(len(r["grid"]), 25)
                self.assertEqual(r["grid_dates"][0], r["days"][0]["date"])
                self.assertEqual(r["days"][1]["text"], "Light rain")
                self.assertTrue(0 < len(r["hours"]) <= 48)
                self.assertLess(r["age_h"], 0.1)
        finally:
            forecast.API = old
            srv.shutdown()


class BatteryTest(unittest.TestCase):
    def test_percent_curve(self):
        import sensors
        self.assertEqual(sensors.Battery.percent(3.0), 0)
        self.assertEqual(sensors.Battery.percent(4.2), 100)
        self.assertTrue(40 < sensors.Battery.percent(3.78) < 52)


class ExportTest(unittest.TestCase):
    def test_gpx_roundtrip(self):
        import exports
        gpx = exports.gpx_waypoints([("Bron & co", 52.1, 5.3, "spring", 0)])
        pts = exports.parse_gpx_waypoints(gpx.encode())
        self.assertEqual(pts, [("Bron & co", 52.1, 5.3, "spring")])


class AccessTest(unittest.TestCase):
    """Other computers may only reach the app over the device's own hotspot."""

    def _handler(self, ip, hotspot_on):
        import server

        class FakeHotspot:
            started = time.time() if hotspot_on else None

            def touch(self):
                pass

        class FakeApp:
            hotspot = FakeHotspot()

        h = server.Handler.__new__(server.Handler)
        h.client_address = (ip, 1234)
        h.app = FakeApp()
        h.sent = None
        h._send = lambda code, *a, **k: setattr(h, "sent", code)
        return h

    def test_rules(self):
        self.assertTrue(self._handler("127.0.0.1", False)._allowed())
        self.assertTrue(self._handler("10.42.0.23", True)._allowed())
        h = self._handler("10.42.0.23", False)
        self.assertFalse(h._allowed())
        self.assertEqual(h.sent, 403)
        self.assertFalse(self._handler("192.168.1.50", True)._allowed())


class ShortwaveDecoderTest(unittest.TestCase):
    def test_wefax_with_clock_error(self):
        import numpy as np
        import wefax
        fs = 11025
        img = np.full((80, wefax.WIDTH), 200, np.uint8)
        img[30:60, 300:900] = 20
        a = wefax.synthesize(img, fs, centre=2000)
        rng = np.random.default_rng(0)
        a = np.concatenate([rng.normal(0, .3, fs * 4), a]) + rng.normal(0, .1, len(a) + fs * 4)
        a = np.interp(np.arange(0, len(a), 1 + 80e-6), np.arange(len(a)), a)  # sound card 80 ppm off
        res = wefax.decode(a, fs, centre=2000)
        self.assertEqual(len(res), 1)
        im = res[0]["image"]
        self.assertTrue(res[0]["complete"])
        self.assertAlmostEqual(len(im), 80, delta=2)
        # rectangle edges stay put from top to bottom (no slant)
        for r in (33, 56):
            dark = np.flatnonzero(im[r, 100:1200] < 100) + 100
            self.assertAlmostEqual(np.median(dark[:20]), 310, delta=12)  # median of the first 20 dark pixels ~ edge + 10

    def test_rtty(self):
        import numpy as np
        import rtty
        fs = 11025
        text = "WETTERLAGE 30.10. 1200 UTC: TIEF 985 HPA, SW 7, BOEN 9."
        a = rtty.encode(text, fs, mark=1600, space=1150)
        a = a + np.random.default_rng(2).normal(0, .25, len(a))
        out, info = rtty.decode(a, fs)
        self.assertIn(text, out)


class LibraryTest(unittest.TestCase):
    def test_links_and_search(self):
        lib = Library(os.path.join(ROOT, "library"))
        self.assertGreater(len(lib.pages), 15)
        for p in lib.pages.values():
            for target in re.findall(r"\(page:([\w\-/]+)\)", p["text"]):
                self.assertIn(target, lib.pages, "broken link in %s" % p["id"])
        self.assertEqual(lib.search("tourniquet")[0]["id"], "firstaid/bleeding")
        self.assertIn("<table>", lib.page("water/purifying")["html"])


class BuilderTest(unittest.TestCase):
    def test_build_sample(self):
        try:
            import osmium  # noqa: F401
        except ImportError:
            self.skipTest("pyosmium not installed")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "nav.db")
            subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "build_navdb.py"),
                                   os.path.join(ROOT, "tests", "data", "sample.osm"), out],
                                  stdout=subprocess.DEVNULL)
            db = sqlite3.connect(out)
            self.assertEqual(db.execute("SELECT count(*) FROM pois").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT name FROM search WHERE search MATCH 'tests*'").fetchone()[0],
                             "Teststad")


if __name__ == "__main__":
    unittest.main()
