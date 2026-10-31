"""Geometry helpers shared by the database builder and the server.

Geometries are stored as compact blobs: a list of parts (lines or polygon
rings), each a sequence of int32 microdegree lon/lat pairs.
"""
import math
import struct

EARTH_R = 6371008.8  # metres


def encode(parts):
    """parts: list of [(lon, lat), ...] -> bytes."""
    out = [struct.pack("<H", len(parts))]
    for p in parts:
        out.append(struct.pack("<I", len(p)))
        flat = []
        for lon, lat in p:
            flat.append(int(round(lon * 1e6)))
            flat.append(int(round(lat * 1e6)))
        out.append(struct.pack("<%di" % len(flat), *flat))
    return b"".join(out)


def decode(blob):
    """bytes -> list of flat [lon, lat, lon, lat, ...] float lists (rounded to 1e-6)."""
    (nparts,) = struct.unpack_from("<H", blob, 0)
    off = 2
    parts = []
    for _ in range(nparts):
        (n,) = struct.unpack_from("<I", blob, off)
        off += 4
        vals = struct.unpack_from("<%di" % (2 * n), blob, off)
        off += 8 * n
        parts.append([v / 1e6 for v in vals])
    return parts


def simplify(points, tol_m):
    """Douglas-Peucker on (lon, lat) points with a tolerance in metres."""
    if len(points) < 3 or tol_m <= 0:
        return list(points)
    lat0 = math.radians(sum(p[1] for p in points) / len(points))
    kx = math.cos(lat0) * 111320.0
    ky = 110540.0
    xy = [(p[0] * kx, p[1] * ky) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    tol2 = tol_m * tol_m
    while stack:
        a, b = stack.pop()
        ax, ay = xy[a]
        bx, by = xy[b]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        best, besti = -1.0, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            if seg2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > best:
                best, besti = d2, i
        if best > tol2:
            keep[besti] = True
            stack.append((a, besti))
            stack.append((besti, b))
    return [p for p, k in zip(points, keep) if k]


def haversine(lat1, lon1, lat2, lon2):
    """Distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1, lon1, lat2, lon2):
    """Initial true bearing in degrees, 0 = north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def tile_bbox(z, x, y):
    """Web Mercator tile -> (west, south, east, north) in degrees."""
    n = 2 ** z

    def lat(yy):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))

    return (x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y))


def ring_area_m2(ring):
    """Approximate absolute area of a (lon, lat) ring in square metres."""
    if len(ring) < 3:
        return 0.0
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    kx = math.cos(lat0) * 111320.0
    ky = 110540.0
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        s += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(s) / 2


def to_mgrs_like(lat, lon):
    """UTM coordinate string, handy for paper maps and radio reports."""
    zone = int((lon + 180) / 6) + 1
    # Norway / Svalbard exceptions
    if 56 <= lat < 64 and 3 <= lon < 12:
        zone = 32
    if 72 <= lat < 84:
        for zlo, zhi, zz in ((0, 9, 31), (9, 21, 33), (21, 33, 35), (33, 42, 37)):
            if zlo <= lon < zhi:
                zone = zz
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    phi, lam = math.radians(lat), math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    T = math.tan(phi) ** 2
    C = ep2 * math.cos(phi) ** 2
    A = math.cos(phi) * (lam - lon0)
    M = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    east = k0 * N * (A + (1 - T + C) * A ** 3 / 6
                     + (5 - 18 * T + T ** 2 + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000
    north = k0 * (M + N * math.tan(phi) * (A ** 2 / 2 + (5 - T + 9 * C + 4 * C ** 2) * A ** 4 / 24
                                          + (61 - 58 * T + T ** 2 + 600 * C - 330 * ep2) * A ** 6 / 720))
    if lat < 0:
        north += 10000000
    bands = "CDEFGHJKLMNPQRSTUVWXX"
    band = bands[max(0, min(20, int((lat + 80) / 8)))]
    return "%d%s %06d E %07d N" % (zone, band, round(east), round(north))


def sun_times(lat, lon, date):
    """Sunrise, sunset (UTC datetimes or None) and day length for a date (NOAA method)."""
    import datetime as dt
    n = date.timetuple().tm_yday
    results = {}
    for name, zenith in (("dawn", 96.0), ("sunrise", 90.833), ("sunset", 90.833), ("dusk", 96.0)):
        rising = name in ("dawn", "sunrise")
        lng_hour = lon / 15
        t = n + ((6 if rising else 18) - lng_hour) / 24
        M = 0.9856 * t - 3.289
        L = (M + 1.916 * math.sin(math.radians(M)) + 0.020 * math.sin(math.radians(2 * M)) + 282.634) % 360
        RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
        RA = (RA + (math.floor(L / 90) * 90 - math.floor(RA / 90) * 90)) / 15
        sin_dec = 0.39782 * math.sin(math.radians(L))
        cos_dec = math.cos(math.asin(sin_dec))
        cos_h = (math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(lat))) / (
            cos_dec * math.cos(math.radians(lat)))
        if cos_h > 1 or cos_h < -1:
            results[name] = None  # sun never rises / never sets
            continue
        H = (360 - math.degrees(math.acos(cos_h))) if rising else math.degrees(math.acos(cos_h))
        T = H / 15 + RA - 0.06571 * t - 6.622
        ut = (T - lng_hour) % 24
        base = dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc)
        results[name] = base + dt.timedelta(hours=ut)
    return results


def utm_to_latlon(zone, northern, east, north):
    """Inverse of the UTM projection used above (WGS84)."""
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    x = east - 500000.0
    y = north if northern else north - 10000000.0
    M = y / k0
    mu = M / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    N1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    T1 = math.tan(phi1) ** 2
    C1 = ep2 * math.cos(phi1) ** 2
    R1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    D = x / (N1 * k0)
    lat = phi1 - (N1 * math.tan(phi1) / R1) * (D ** 2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 ** 2 - 9 * ep2) * D ** 4 / 24
                                               + (61 + 90 * T1 + 298 * C1 + 45 * T1 ** 2 - 252 * ep2 - 3 * C1 ** 2)
                                               * D ** 6 / 720)
    lon = (D - (1 + 2 * T1 + C1) * D ** 3 / 6
           + (5 - 2 * C1 + 28 * T1 - 3 * C1 ** 2 + 8 * ep2 + 24 * T1 ** 2) * D ** 5 / 120) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon) + (zone - 1) * 6 - 180 + 3


def parse_coords(text):
    """Typed coordinates -> (lat, lon). Accepts
         52.3702, 4.8952        52.3702N 4.8952E        -33.92 18.42
         52 22.21 N 4 53.71 E   52°22.21'N 004°53.71'E  (degrees + decimal minutes, as on charts)
         52°22'12.6"N 4°53'42.7"E                       (degrees, minutes, seconds)
         31U 628000 5803000     31U 628000 E 5803000 N  (UTM, as shown on the Go tab)
    Raises ValueError with a short hint when it can't make sense of it."""
    import re
    s = text.strip().upper().replace(",", " ").replace(";", " ")
    s = s.replace("º", "°").replace("’", "'").replace("′", "'").replace("″", '"').replace("''", '"')
    m = re.match(r"^(\d{1,2})\s*([C-HJ-NP-X])\s+(\d{5,7}(?:\.\d+)?)\s*E?\s+(\d{6,8}(?:\.\d+)?)\s*N?$", s)
    if m:
        zone, band = int(m.group(1)), m.group(2)
        if not 1 <= zone <= 60:
            raise ValueError("UTM zone must be 1-60")
        return utm_to_latlon(zone, band >= "N", float(m.group(3)), float(m.group(4)))
    # split into two halves at the N/S letter, or in the middle of the numbers
    parts = re.findall(r"[NSEW]|-?\d+(?:\.\d+)?", s)
    if not parts:
        raise ValueError("type e.g. 52.37 4.89, or 52 22.2 N 4 53.7 E")
    halves, cur = [], []
    if parts[0] in ("N", "S", "E", "W"):  # hemisphere letters written in front: N 52 22.2 E 4 53.7
        for p in parts:
            if p in "NSEW":
                halves.append(([], p))
            elif halves:
                halves[-1][0].append(float(p))
        parts = []
    for p in parts:
        if p in "NSEW":
            if cur:
                halves.append((cur, p))
                cur = []
            elif halves and halves[-1][1] is None:
                halves[-1] = (halves[-1][0], p)
            else:
                halves.append(([], p))
        else:
            cur.append(float(p))
    if cur:
        halves.append((cur, None))
    if len(halves) == 1 and halves[0][1] is None and len(halves[0][0]) in (2, 4, 6):
        nums = halves[0][0]
        k = len(nums) // 2
        halves = [(nums[:k], None), (nums[k:], None)]
    if len(halves) != 2:
        raise ValueError("need a latitude and a longitude")

    def value(nums, hemi):
        if not 1 <= len(nums) <= 3:
            raise ValueError("too many numbers")
        neg = nums[0] < 0
        d = abs(nums[0]) + (nums[1] / 60 if len(nums) > 1 else 0) + (nums[2] / 3600 if len(nums) > 2 else 0)
        if len(nums) > 1 and not 0 <= nums[1] < 60 or len(nums) > 2 and not 0 <= nums[2] < 60:
            raise ValueError("minutes and seconds must be below 60")
        return -d if neg or hemi in ("S", "W") else d

    (n1, h1), (n2, h2) = halves
    if h1 in ("E", "W") or h2 in ("N", "S"):  # longitude typed first
        (n1, h1), (n2, h2) = (n2, h2), (n1, h1)
    lat, lon = value(n1, h1), value(n2, h2)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("latitude must be -90..90 and longitude -180..180")
    return lat, lon
