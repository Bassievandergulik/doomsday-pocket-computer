"""GPS position source.

Tries, in order:
  1. gpsd on localhost:2947 (recommended: `sudo apt install gpsd`)
  2. raw NMEA from a serial port (e.g. /dev/serial0 for a GPS on the UART pins)
  3. a fixed simulated position (for testing, or when there is no GPS at all)

The latest fix is kept in `GPS.fix` as a dict and updated by a background thread.
"""
import json
import socket
import threading
import time


def _nmea_coord(value, hemi):
    if not value:
        return None
    dot = value.index(".")
    deg = float(value[:dot - 2])
    minutes = float(value[dot - 2:])
    v = deg + minutes / 60
    return -v if hemi in ("S", "W") else v


def _checksum_ok(line):
    if "*" not in line:
        return False
    body, cs = line[1:].split("*", 1)
    c = 0
    for ch in body:
        c ^= ord(ch)
    try:
        return c == int(cs[:2], 16)
    except ValueError:
        return False


class GPS:
    def __init__(self, serial_port=None, baud=9600, simulate=None):
        self.serial_port = serial_port
        self.baud = baud
        self.simulate = simulate
        self.fix = {"mode": 0, "source": "none"}
        self.track = []  # recent (time, lat, lon) breadcrumbs
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def get(self):
        with self._lock:
            f = dict(self.fix)
        if f.get("time_local") and time.time() - f["time_local"] > 10:
            f["stale"] = True
        return f

    def _update(self, **kw):
        with self._lock:
            self.fix.update(kw)
            self.fix["time_local"] = time.time()
            lat, lon = self.fix.get("lat"), self.fix.get("lon")
            if self.fix.get("mode", 0) >= 2 and lat is not None:
                if not self.track or time.time() - self.track[-1][0] > 15:
                    self.track.append((time.time(), lat, lon))
                    del self.track[:-2000]

    def _run(self):
        if self.simulate:
            lat, lon = self.simulate
            while True:
                self._update(mode=3, lat=lat, lon=lon, alt=10.0, speed=0.0, track=None,
                             sats=0, hdop=1.0, source="simulated")
                time.sleep(1)
        while True:
            try:
                self._gpsd()
            except OSError:
                pass
            if self.serial_port:
                try:
                    self._serial()
                except OSError:
                    pass
            self.fix["source"] = "none"
            time.sleep(5)

    def _gpsd(self):
        s = socket.create_connection(("127.0.0.1", 2947), timeout=3)
        s.sendall(b'?WATCH={"enable":true,"json":true};\n')
        s.settimeout(15)
        buf = b""
        while True:
            data = s.recv(4096)
            if not data:
                raise OSError("gpsd closed")
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("class") == "TPV":
                    self._update(mode=msg.get("mode", 0), lat=msg.get("lat"), lon=msg.get("lon"),
                                 alt=msg.get("altMSL", msg.get("alt")), speed=msg.get("speed"),
                                 track=msg.get("track"), utc=msg.get("time"), source="gpsd")
                elif msg.get("class") == "SKY":
                    # gpsd 3.2x sends uSat (satellites used); older versions only the satellite list,
                    # and some SKY messages carry neither: then keep the last count
                    used = msg.get("uSat")
                    if used is None and "satellites" in msg:
                        used = len([x for x in msg["satellites"] if x.get("used")])
                    upd = {"hdop": msg["hdop"]} if msg.get("hdop") is not None else {}
                    if used is not None:
                        upd["sats"] = used
                    if upd:
                        self._update(**upd)

    def _serial(self):
        try:
            import serial  # pyserial
            port = serial.Serial(self.serial_port, self.baud, timeout=5)
            readline = port.readline
        except ImportError:
            port = open(self.serial_port, "rb", buffering=0)  # needs `stty -F <port> 9600 raw`
            readline = port.readline
        with port:
            while True:
                raw = readline()
                if not raw:
                    raise OSError("no data from serial GPS")
                self.parse_nmea(raw.decode("ascii", "replace").strip())

    def parse_nmea(self, line):
        if not line.startswith("$") or not _checksum_ok(line):
            return
        f = line.split("*")[0].split(",")
        kind = f[0][3:]
        if kind == "GGA" and len(f) > 9:
            q = int(f[6] or 0)
            if q == 0:
                self._update(mode=1, sats=int(f[7] or 0), source="nmea")
                return
            self._update(lat=_nmea_coord(f[2], f[3]), lon=_nmea_coord(f[4], f[5]),
                         sats=int(f[7] or 0), hdop=float(f[8] or 0), alt=float(f[9] or 0),
                         mode=max(self.fix.get("mode", 0), 2), source="nmea")
        elif kind == "RMC" and len(f) > 9:
            if f[2] != "A":
                return
            spd = float(f[7]) * 0.514444 if f[7] else None
            trk = float(f[8]) if f[8] else None
            utc = None
            if f[1] and f[9]:
                utc = "20%s-%s-%sT%s:%s:%sZ" % (f[9][4:6], f[9][2:4], f[9][0:2], f[1][0:2], f[1][2:4], f[1][4:6])
            self._update(lat=_nmea_coord(f[3], f[4]), lon=_nmea_coord(f[5], f[6]), speed=spd,
                         track=trk, utc=utc, mode=max(self.fix.get("mode", 0), 2), source="nmea")
        elif kind == "GSA" and len(f) > 2 and f[2] in ("2", "3"):
            self._update(mode=int(f[2]))


def track_length_m(track):
    from geo import haversine
    return sum(haversine(a[1], a[2], b[1], b[2]) for a, b in zip(track, track[1:]))


if __name__ == "__main__":
    g = GPS()
    g.parse_nmea("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
    print(g.get())
