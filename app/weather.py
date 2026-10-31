"""Local weather station: logs the BME280 and forecasts from the pressure trend.

The forecast uses the Zambretti algorithm (a 1915 barometer-based method that
is right roughly 75-90% of the time for the next ~12 hours in NW Europe) plus
simple warning rules for fast pressure drops, frost and heat.
"""
import math
import sqlite3
import threading
import time

ZAMBRETTI = [
    "Settled fine", "Fine weather", "Becoming fine", "Fine, becoming less settled",
    "Fine, possible showers", "Fairly fine, improving", "Fairly fine, possible showers early",
    "Fairly fine, showery later", "Showery early, improving", "Changeable, mending",
    "Fairly fine, showers likely", "Rather unsettled, clearing later",
    "Unsettled, probably improving", "Showery, bright intervals", "Showery, becoming less settled",
    "Changeable, some rain", "Unsettled, short fine intervals", "Unsettled, rain later",
    "Unsettled, some rain", "Mostly very unsettled", "Occasional rain, worsening",
    "Rain at times, very unsettled", "Rain at frequent intervals", "Rain, very unsettled",
    "Stormy, may improve", "Stormy, much rain",
]
# lookup tables mapping the Zambretti number to the text index above
_RISING = [25, 25, 25, 24, 24, 19, 16, 12, 11, 9, 8, 6, 5, 2, 1, 1, 0, 0, 0, 0, 0, 0]
_STEADY = [25, 25, 25, 25, 25, 25, 23, 23, 22, 18, 15, 13, 10, 4, 1, 1, 0, 0, 0, 0, 0, 0]
_FALLING = [25, 25, 25, 25, 25, 25, 25, 25, 23, 23, 21, 20, 17, 14, 7, 3, 1, 1, 1, 0, 0, 0]


def sea_level_pressure(p_hpa, alt_m, temp_c):
    """Reduce station pressure to mean sea level (hypsometric formula)."""
    if p_hpa is None:
        return None
    return p_hpa * (1 - 0.0065 * alt_m / (temp_c + 0.0065 * alt_m + 273.15)) ** -5.257


def dew_point(temp_c, rh):
    if rh is None or rh <= 0:
        return None
    a, b = 17.62, 243.12
    g = math.log(rh / 100) + a * temp_c / (b + temp_c)
    return b * g / (a - g)


def zambretti(p_msl, trend_hpa_3h, month, northern=True):
    """Classic Zambretti forecaster. trend: hPa change over the last 3 hours."""
    if trend_hpa_3h <= -1.6:
        tendency, table = "falling", _FALLING
    elif trend_hpa_3h >= 1.6:
        tendency, table = "rising", _RISING
    else:
        tendency, table = "steady", _STEADY
    summer = (4 <= month <= 9) if northern else not (4 <= month <= 9)
    p = p_msl
    # seasonal correction from the original instrument (7% of the 100 hPa scale)
    if tendency == "rising" and not summer:
        p += 7.0
    elif tendency == "falling" and summer:
        p -= 7.0
    # scale 950..1050 hPa onto the 22-step table (low pressure = stormy end)
    idx = int(math.floor((p - 950) / (100 / 22)))
    idx = max(0, min(21, idx))
    return tendency, ZAMBRETTI[table[idx]]


def warnings(trend_3h, temp_c, rh, dp):
    out = []
    if trend_3h is not None:
        if trend_3h <= -6:
            out.append("Pressure falling very fast: gale or storm likely within hours. Secure shelter.")
        elif trend_3h <= -3:
            out.append("Pressure falling fast (3 hPa or more in 3 hours): strong wind and rain likely soon. At sea: reef early, secure the boat.")
    if temp_c is not None:
        if temp_c <= 3 or (dp is not None and dp <= 0 and temp_c <= 6):
            out.append("Frost or ice possible tonight. Protect water and keep dry clothing.")
        if temp_c >= 32 or (temp_c >= 27 and rh and rh >= 70):
            out.append("Heat stress risk. Rest in shade 11:00-16:00, drink regularly.")
    return out


class WeatherStation:
    def __init__(self, sensor, db_path, altitude_m=0.0, interval_s=600, get_alt=None):
        self.sensor = sensor
        self.db_path = db_path
        self.altitude_m = altitude_m
        self.interval_s = interval_s
        self.get_alt = get_alt  # callable returning GPS altitude, or None
        self.last = None
        db = self._db()
        db.execute("CREATE TABLE IF NOT EXISTS weather(t REAL PRIMARY KEY, temp REAL, p REAL, rh REAL)")
        db.commit()
        db.close()

    def _db(self):
        return sqlite3.connect(self.db_path, timeout=10)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                self.sample()
            except OSError:
                pass
            time.sleep(self.interval_s)

    def sample(self):
        if not self.sensor or not self.sensor.available:
            return None
        r = self.sensor.read()
        if not r or r["pressure_hpa"] is None:
            return None
        self.last = dict(r, t=time.time())
        db = self._db()
        db.execute("INSERT OR REPLACE INTO weather VALUES(?,?,?,?)",
                   (self.last["t"], r["temp_c"], r["pressure_hpa"], r["humidity"]))
        db.execute("DELETE FROM weather WHERE t < ?", (time.time() - 14 * 86400,))
        db.commit()
        db.close()
        return self.last

    def history(self, hours=48):
        db = self._db()
        rows = db.execute("SELECT t,temp,p,rh FROM weather WHERE t > ? ORDER BY t",
                          (time.time() - hours * 3600,)).fetchall()
        db.close()
        return rows

    def altitude(self):
        if self.get_alt:
            a = self.get_alt()
            if a is not None:
                return a
        return self.altitude_m

    def report(self, now=None, latitude=None):
        now = now or time.time()
        rows = self.history(6)
        if not rows:
            return {"available": bool(self.sensor and self.sensor.available),
                    "message": "No readings yet. A forecast needs about 3 hours of data."}
        t, temp, p, rh = rows[-1]
        alt = self.altitude()
        msl = sea_level_pressure(p, alt, temp)
        past = [r for r in rows if r[0] <= t - 2.5 * 3600]
        trend = None
        if past:
            pt, ptemp, pp, _ = past[-1]
            hours = (t - pt) / 3600
            trend = (msl - sea_level_pressure(pp, alt, ptemp)) / hours * 3
        dp = dew_point(temp, rh)
        month = time.localtime(now).tm_mon
        out = {
            "available": True, "time": t, "temp_c": round(temp, 1),
            "humidity": rh, "dew_point_c": round(dp, 1) if dp is not None else None,
            "pressure_station_hpa": round(p, 1), "pressure_msl_hpa": round(msl, 1),
            "altitude_m": alt, "trend_hpa_3h": round(trend, 1) if trend is not None else None,
            "warnings": warnings(trend, temp, rh, dp),
        }
        if trend is None:
            out["forecast"] = "Collecting data: forecast available after 3 hours of readings."
        else:
            tendency, text = zambretti(msl, trend, month, northern=(latitude is None or latitude >= 0))
            out["tendency"] = tendency
            out["forecast"] = text
        return out
