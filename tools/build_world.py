#!/usr/bin/env python3
"""Build the rough world map (data/world.db): country outlines, lakes, sea and
ocean names, and the important airports with their runways and radio frequencies.

The detailed map (nav.db) covers only the regions you built it for. This layer is
drawn underneath it, so the whole world has at least coastlines, borders and
airfields. Run it on a computer with internet (no extra Python packages needed):

    python3 tools/build_world.py data/world.db

Sources (downloaded into a cache folder, about 25 MB):
  Natural Earth 1:50m (public domain)       countries, lakes, marine areas
  OurAirports (public domain)               airports, runways, frequencies
"""
import argparse
import csv
import io
import json
import os
import sqlite3
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import geo  # noqa: E402

NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
OA = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/"
SOURCES = {
    "countries.geojson": NE + "ne_50m_admin_0_countries.geojson",
    "lakes.geojson": NE + "ne_50m_lakes.geojson",
    "marine.geojson": NE + "ne_50m_geography_marine_polys.geojson",
    "airports.csv": OA + "airports.csv",
    "runways.csv": OA + "runways.csv",
    "frequencies.csv": OA + "airport-frequencies.csv",
}
# geometry detail levels: (column, simplify tolerance in metres)
LEVELS = (("geom", 800), ("geom_mid", 4000), ("geom_lo", 25000))
SURFACE = {"ASP": "asphalt", "ASPH": "asphalt", "ASPHALT": "asphalt", "BIT": "asphalt", "PEM": "asphalt",
           "CON": "concrete", "CONC": "concrete", "CONCRETE": "concrete", "GRS": "grass", "GRASS": "grass",
           "TURF": "grass", "GRE": "gravel", "GRVL": "gravel", "GRAVEL": "gravel", "DIRT": "dirt",
           "SAND": "sand", "WATER": "water", "COP": "composite", "ASP-CON": "asphalt/concrete"}
FREQ_ORDER = ["ATIS", "TWR", "AFIS", "INFO", "APP", "GND", "CTAF", "UNICOM", "A/G", "RDO", "DEP", "CLD", "DEL"]


def fetch(cache, name):
    path = os.path.join(cache, name)
    if not os.path.exists(path):
        print("downloading", SOURCES[name])
        req = urllib.request.Request(SOURCES[name], headers={"User-Agent": "offline-map-builder"})
        with urllib.request.urlopen(req, timeout=120) as r, open(path + ".part", "wb") as f:
            f.write(r.read())
        os.replace(path + ".part", path)
    return path


def polygons(geometry):
    """GeoJSON (Multi)Polygon -> list of polygons, each a list of rings of (lon, lat)."""
    if not geometry:
        return []
    if geometry["type"] == "Polygon":
        polys = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polys = geometry["coordinates"]
    else:
        return []
    return [[[(p[0], p[1]) for p in ring] for ring in poly] for poly in polys]


def add_polygons(db, table, name, polys):
    for poly in polys:
        cols = {}
        for col, tol in LEVELS:
            rings = []
            for i, ring in enumerate(poly):
                s = geo.simplify(ring, tol)
                if len(s) >= 4:
                    rings.append(s)
                elif i == 0:
                    break  # outer ring too small at this detail: leave the polygon out
            cols[col] = geo.encode(rings) if rings and len(rings[0]) >= 4 else None
        if cols["geom"] is None:
            continue
        outer = poly[0]
        xs, ys = [p[0] for p in outer], [p[1] for p in outer]
        cur = db.execute("INSERT INTO %s(name, geom, geom_mid, geom_lo) VALUES(?,?,?,?)" % table,
                         (name, cols["geom"], cols["geom_mid"], cols["geom_lo"]))
        db.execute("INSERT INTO %s_idx VALUES(?,?,?,?,?)" % table, (cur.lastrowid, min(xs), max(xs), min(ys), max(ys)))


def add_label(db, kind, name, lon, lat, minz):
    cur = db.execute("INSERT INTO labels(kind, name, lon, lat, minz) VALUES(?,?,?,?,?)", (kind, name, lon, lat, minz))
    db.execute("INSERT INTO labels_idx VALUES(?,?,?,?,?)", (cur.lastrowid, lon, lon, lat, lat))
    db.execute("INSERT INTO search(name, kind, ref, lon, lat) VALUES(?,?,?,?,?)", (name, kind, "", lon, lat))


def label_point(polys):
    """Middle of the bounding box of the biggest polygon (good enough for sea names)."""
    best = max((p[0] for p in polys), key=len)
    xs, ys = [p[0] for p in best], [p[1] for p in best]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def runway_text(rws):
    out = []
    for r in sorted(rws, key=lambda r: -(num(r["length_ft"], 0))):
        if r.get("closed") == "1":
            continue
        ends = "/".join(x for x in (r["le_ident"], r["he_ident"]) if x)
        if not ends or ends.upper().startswith("H"):  # helipads
            continue
        length = num(r["length_ft"])
        surf = (r["surface"] or "").upper().strip()
        surf = SURFACE.get(surf, SURFACE.get(surf.split("-")[0].split(" ")[0], surf.lower()))
        bits = ["RWY " + ends]
        if length:
            bits.append("%d m" % round(length * 0.3048))
        if surf:
            bits.append(surf)
        out.append(" ".join(bits))
    return out[:4]


def freq_text(fqs):
    by_type = {}
    for f in fqs:
        t = (f["type"] or f["description"] or "").upper().strip()
        mhz = num(f["frequency_mhz"])
        if not t or not mhz or not 108 <= mhz <= 137 or t in ("MISC", "OPS", "POST"):
            continue  # only VHF airband, the band the radio can receive
        by_type.setdefault(t, [])
        v = ("%.3f" % mhz).rstrip("0").rstrip(".")
        if v not in by_type[t]:
            by_type[t].append(v)
    keys = sorted(by_type, key=lambda t: FREQ_ORDER.index(t) if t in FREQ_ORDER else 99)
    return ["%s %s" % (t, " ".join(by_type[t][:2])) for t in keys[:6]]


def build(out, cache):
    os.makedirs(cache, exist_ok=True)
    paths = {n: fetch(cache, n) for n in SOURCES}
    tmp = out + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.executescript("""
    CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE land(id INTEGER PRIMARY KEY, name TEXT, geom BLOB, geom_mid BLOB, geom_lo BLOB);
    CREATE VIRTUAL TABLE land_idx USING rtree(id, minx, maxx, miny, maxy);
    CREATE TABLE lakes(id INTEGER PRIMARY KEY, name TEXT, geom BLOB, geom_mid BLOB, geom_lo BLOB);
    CREATE VIRTUAL TABLE lakes_idx USING rtree(id, minx, maxx, miny, maxy);
    CREATE TABLE labels(id INTEGER PRIMARY KEY, kind TEXT, name TEXT, lon REAL, lat REAL, minz REAL);
    CREATE VIRTUAL TABLE labels_idx USING rtree(id, minx, maxx, miny, maxy);
    CREATE TABLE airports(id INTEGER PRIMARY KEY, ident TEXT, icao TEXT, iata TEXT, name TEXT, size TEXT,
                          lon REAL, lat REAL, elev_ft INTEGER, country TEXT, city TEXT, info TEXT);
    CREATE VIRTUAL TABLE airports_idx USING rtree(id, minx, maxx, miny, maxy);
    CREATE VIRTUAL TABLE search USING fts5(name, kind UNINDEXED, ref UNINDEXED, lon UNINDEXED, lat UNINDEXED,
                                           tokenize='unicode61 remove_diacritics 2');
    """)

    countries = {}
    for f in json.load(open(paths["countries.geojson"], encoding="utf-8"))["features"]:
        p = f["properties"]
        name = p.get("NAME_EN") or p.get("NAME") or p.get("ADMIN")
        countries[p.get("ISO_A2_EH") or p.get("ISO_A2")] = name
        polys = polygons(f["geometry"])
        add_polygons(db, "land", name, polys)
        if p.get("LABEL_X") is not None:
            add_label(db, "country", name, p["LABEL_X"], p["LABEL_Y"], num(p.get("MIN_LABEL"), 5))
    print("countries:", len(countries))

    n = 0
    for f in json.load(open(paths["lakes.geojson"], encoding="utf-8"))["features"]:
        p = f["properties"]
        if p.get("featurecla") not in ("Lake", "Reservoir", "Alkaline Lake"):
            continue
        polys = polygons(f["geometry"])
        add_polygons(db, "lakes", p.get("name"), polys)
        n += 1
        if p.get("name") and polys and num(p.get("min_label"), 9) <= 5:
            lon, lat = label_point(polys)
            add_label(db, "lake", p["name"], lon, lat, max(3, num(p.get("min_label"), 5)))
    print("lakes:", n)

    n = 0
    for f in json.load(open(paths["marine.geojson"], encoding="utf-8"))["features"]:
        p = f["properties"]
        name = p.get("name_en") or p.get("name")
        polys = polygons(f["geometry"])
        if not name or not polys or p.get("featurecla") in ("river", "reef"):
            continue
        lon, lat = label_point(polys)
        add_label(db, "ocean" if p.get("featurecla") == "ocean" else "sea", name, lon, lat,
                  num(p.get("min_label"), 4))
        n += 1
    print("sea names:", n)

    rws, fqs = {}, {}
    for r in read_csv(paths["runways.csv"]):
        rws.setdefault(r["airport_ident"], []).append(r)
    for r in read_csv(paths["frequencies.csv"]):
        fqs.setdefault(r["airport_ident"], []).append(r)
    n = 0
    for a in read_csv(paths["airports.csv"]):
        if a["type"] not in ("large_airport", "medium_airport"):
            continue
        lon, lat = num(a["longitude_deg"]), num(a["latitude_deg"])
        if lon is None or lat is None:
            continue
        icao = a.get("icao_code") or (a["gps_code"] if len(a.get("gps_code") or "") == 4 else "") or a["ident"]
        iata = a.get("iata_code") or ""
        elev = num(a["elevation_ft"])
        info = [" / ".join(x for x in (icao, iata) if x)]
        if elev is not None:
            info.append("elev %d ft (%d m)" % (elev, round(elev * 0.3048)))
        info += runway_text(rws.get(a["ident"], []))
        info += freq_text(fqs.get(a["ident"], []))
        size = "large" if a["type"] == "large_airport" else "medium"
        country = countries.get(a["iso_country"], a["iso_country"])
        cur = db.execute("INSERT INTO airports(ident, icao, iata, name, size, lon, lat, elev_ft, country, city, info) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (a["ident"], icao, iata, a["name"], size, lon, lat, None if elev is None else int(elev),
                          country, a["municipality"], " · ".join(info)))
        db.execute("INSERT INTO airports_idx VALUES(?,?,?,?,?)", (cur.lastrowid, lon, lon, lat, lat))
        db.execute("INSERT INTO search(name, kind, ref, lon, lat) VALUES(?,?,?,?,?)",
                   (" ".join(x for x in (a["name"], icao, iata, a["municipality"]) if x), "airport",
                    "ap:%d" % cur.lastrowid, lon, lat))
        n += 1
    print("airports:", n)

    db.executemany("INSERT INTO meta VALUES(?,?)", [
        ("built", time.strftime("%Y-%m-%d")),
        ("sources", "Natural Earth 1:50m; OurAirports"),
    ])
    db.commit()
    db.execute("VACUUM")
    db.close()
    os.replace(tmp, out)
    print("wrote %s (%.1f MB)" % (out, os.path.getsize(out) / 1e6))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output", nargs="?", default="data/world.db")
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/doomsday-world"),
                    help="where the downloaded source files are kept")
    a = ap.parse_args()
    build(a.output, a.cache)


if __name__ == "__main__":
    main()
