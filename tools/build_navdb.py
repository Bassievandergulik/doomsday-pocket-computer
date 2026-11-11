#!/usr/bin/env python3
"""Build the offline navigation database from an OpenStreetMap extract.

Run this on a normal computer (it needs RAM and time), then copy the
resulting nav.db to the pocket computer.

    pip install osmium
    # download e.g. https://download.geofabrik.de/europe/netherlands/gelderland-latest.osm.pbf
    python3 tools/build_navdb.py gelderland-latest.osm.pbf data/nav.db

The database holds:
  lines     roads, paths, rail, rivers, coastline (with R-tree index)
  areas     water, forest, built-up land, optional buildings
  pois      survival-relevant points: water, shelter, medical, food, fuel...
  places    towns and villages, for search and labels
  search    full-text index over places and named POIs
"""
import argparse
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import geo  # noqa: E402

try:
    import osmium
except ImportError:
    sys.exit("pyosmium is required: pip install osmium")

# class -> minimum zoom it is shown at
LINE_CLASSES = {
    ("highway", "motorway"): ("motorway", 6), ("highway", "motorway_link"): ("motorway", 10),
    ("highway", "trunk"): ("trunk", 7), ("highway", "trunk_link"): ("trunk", 11),
    ("highway", "primary"): ("primary", 8), ("highway", "primary_link"): ("primary", 12),
    ("highway", "secondary"): ("secondary", 10), ("highway", "secondary_link"): ("secondary", 13),
    ("highway", "tertiary"): ("tertiary", 11), ("highway", "tertiary_link"): ("tertiary", 13),
    ("highway", "unclassified"): ("minor", 12), ("highway", "residential"): ("minor", 13),
    ("highway", "living_street"): ("minor", 14), ("highway", "service"): ("service", 15),
    ("highway", "track"): ("track", 13),
    ("highway", "path"): ("path", 14), ("highway", "footway"): ("path", 15),
    ("highway", "bridleway"): ("path", 14), ("highway", "cycleway"): ("path", 14),
    ("highway", "steps"): ("path", 16),
    ("railway", "rail"): ("rail", 10),
    ("waterway", "river"): ("river", 8), ("waterway", "canal"): ("canal", 10),
    ("waterway", "stream"): ("stream", 13), ("waterway", "ditch"): ("stream", 15),
    ("waterway", "drain"): ("stream", 15),
    ("natural", "coastline"): ("coast", 5),
    ("power", "line"): ("power", 14),
}

AREA_CLASSES = {
    ("natural", "water"): "water", ("landuse", "reservoir"): "water",
    ("landuse", "basin"): "water", ("waterway", "riverbank"): "water",
    ("natural", "wetland"): "wetland",
    ("natural", "wood"): "forest", ("landuse", "forest"): "forest",
    ("landuse", "residential"): "urban", ("landuse", "industrial"): "urban",
    ("landuse", "commercial"): "urban", ("landuse", "retail"): "urban",
    ("landuse", "farmland"): "farm", ("landuse", "meadow"): "grass",
    ("natural", "grassland"): "grass", ("natural", "heath"): "grass",
    ("leisure", "park"): "grass", ("natural", "beach"): "sand", ("natural", "sand"): "sand",
    ("natural", "bare_rock"): "rock", ("natural", "scree"): "rock",
    ("natural", "glacier"): "ice",
}

# POI category -> list of (key, value) matches. Order matters: first match wins.
POI_CATEGORIES = [
    ("water", [("amenity", "drinking_water"), ("man_made", "water_tap"), ("man_made", "water_well"),
               ("natural", "spring"), ("amenity", "water_point"), ("drinking_water", "yes")]),
    ("shelter", [("amenity", "shelter"), ("tourism", "alpine_hut"), ("tourism", "wilderness_hut"),
                 ("building", "hut"), ("military", "bunker")]),
    ("hospital", [("amenity", "hospital"), ("healthcare", "hospital")]),
    ("doctor", [("amenity", "clinic"), ("amenity", "doctors"), ("healthcare", "clinic"),
                ("healthcare", "doctor")]),
    ("pharmacy", [("amenity", "pharmacy"), ("healthcare", "pharmacy")]),
    ("aed", [("emergency", "defibrillator")]),
    ("police", [("amenity", "police")]),
    ("fire", [("amenity", "fire_station")]),
    ("fuel", [("amenity", "fuel")]),
    ("food", [("shop", "supermarket"), ("shop", "convenience"), ("shop", "greengrocer"),
              ("shop", "bakery"), ("shop", "butcher"), ("amenity", "marketplace")]),
    ("hardware", [("shop", "hardware"), ("shop", "doityourself"), ("shop", "outdoor")]),
    ("camp", [("tourism", "camp_site"), ("tourism", "caravan_site")]),
    ("toilet", [("amenity", "toilets")]),
    ("phone", [("amenity", "telephone"), ("emergency", "phone")]),
    ("peak", [("natural", "peak"), ("natural", "volcano")]),
    ("cave", [("natural", "cave_entrance")]),
    ("bridge", []),  # placeholder, not matched from tags
]
POI_CATEGORIES = [c for c in POI_CATEGORIES if c[1]]

PLACE_RANK = {"city": 6, "town": 9, "village": 11, "suburb": 12, "hamlet": 13,
              "isolated_dwelling": 15, "locality": 14, "neighbourhood": 14}

# simplification tolerance (metres) for the full-detail and low-zoom geometries
TOL_HI = 3.0
TOL_LO = 60.0
LO_ZOOM = 12  # below this zoom the low-detail geometry is served


def poi_category(tags):
    for cat, matches in POI_CATEGORIES:
        for k, v in matches:
            if tags.get(k) == v:
                return cat
    return None


def keep_tags(tags):
    keys = ("name", "opening_hours", "phone", "drinking_water", "access", "fee", "ele",
            "emergency", "healthcare", "operator", "addr:street", "addr:housenumber",
            "addr:city", "description", "seasonal", "capacity")
    return {k: tags[k] for k in keys if k in tags}


SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE lines(id INTEGER PRIMARY KEY, cls TEXT, name TEXT, minz INT, geom BLOB, geom_lo BLOB);
CREATE VIRTUAL TABLE lines_idx USING rtree(id, minx, maxx, miny, maxy);
CREATE TABLE areas(id INTEGER PRIMARY KEY, cls TEXT, name TEXT, minz INT, geom BLOB, geom_lo BLOB);
CREATE VIRTUAL TABLE areas_idx USING rtree(id, minx, maxx, miny, maxy);
CREATE TABLE pois(id INTEGER PRIMARY KEY, cat TEXT, name TEXT, lon REAL, lat REAL, tags TEXT);
CREATE VIRTUAL TABLE pois_idx USING rtree(id, minx, maxx, miny, maxy);
CREATE TABLE places(id INTEGER PRIMARY KEY, kind TEXT, name TEXT, minz INT, lon REAL, lat REAL, population INT);
CREATE VIRTUAL TABLE places_idx USING rtree(id, minx, maxx, miny, maxy);
CREATE VIRTUAL TABLE search USING fts5(name, kind, ref UNINDEXED, lon UNINDEXED, lat UNINDEXED,
                                       tokenize='unicode61 remove_diacritics 2');
"""


class Builder(osmium.SimpleHandler):
    def __init__(self, db, buildings=False):
        super().__init__()
        self.db = db
        self.buildings = buildings
        self.n = {"lines": 0, "areas": 0, "pois": 0, "places": 0}
        self.bbox = [180.0, 90.0, -180.0, -90.0]
        self.t0 = time.time()

    def _grow(self, minx, miny, maxx, maxy):
        b = self.bbox
        b[0], b[1], b[2], b[3] = min(b[0], minx), min(b[1], miny), max(b[2], maxx), max(b[3], maxy)

    def _progress(self):
        total = sum(self.n.values())
        if total % 20000 == 0:
            print("  %s  (%.0fs)" % (self.n, time.time() - self.t0), flush=True)

    def _add_poi(self, cat, tags, lon, lat):
        cur = self.db.execute("INSERT INTO pois(cat,name,lon,lat,tags) VALUES(?,?,?,?,?)",
                              (cat, tags.get("name"), lon, lat, json.dumps(keep_tags(tags))))
        pid = cur.lastrowid
        self.db.execute("INSERT INTO pois_idx VALUES(?,?,?,?,?)", (pid, lon, lon, lat, lat))
        if tags.get("name"):
            self.db.execute("INSERT INTO search VALUES(?,?,?,?,?)",
                            (tags["name"], cat, "poi:%d" % pid, lon, lat))
        self.n["pois"] += 1
        self._progress()

    def node(self, n):
        if not n.tags or not n.location.valid():
            return
        tags = {t.k: t.v for t in n.tags}
        lon, lat = n.location.lon, n.location.lat
        place = tags.get("place")
        if place in PLACE_RANK and tags.get("name"):
            try:
                pop = int(tags.get("population", "0").replace(",", "").replace(".", ""))
            except ValueError:
                pop = 0
            cur = self.db.execute(
                "INSERT INTO places(kind,name,minz,lon,lat,population) VALUES(?,?,?,?,?,?)",
                (place, tags["name"], PLACE_RANK[place], lon, lat, pop))
            self.db.execute("INSERT INTO places_idx VALUES(?,?,?,?,?)", (cur.lastrowid, lon, lon, lat, lat))
            self.db.execute("INSERT INTO search VALUES(?,?,?,?,?)",
                            (tags["name"], place, "place:%d" % cur.lastrowid, lon, lat))
            self.n["places"] += 1
            self._grow(lon, lat, lon, lat)
        cat = poi_category(tags)
        if cat:
            self._add_poi(cat, tags, lon, lat)

    def way(self, w):
        tags = w.tags
        cls = None
        for (k, v), c in LINE_CLASSES.items():
            if tags.get(k) == v:
                cls = c
                break
        if cls is None:
            return
        # canals and rivers mapped as areas are handled in area(); skip closed riverbanks
        try:
            pts = [(nd.lon, nd.lat) for nd in w.nodes if nd.location.valid()]
        except osmium.InvalidLocationError:
            return
        if len(pts) < 2:
            return
        name = tags.get("name") or tags.get("ref")
        cname, minz = cls
        hi = geo.simplify(pts, TOL_HI)
        lo = geo.simplify(pts, TOL_LO) if minz < LO_ZOOM else None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        cur = self.db.execute("INSERT INTO lines(cls,name,minz,geom,geom_lo) VALUES(?,?,?,?,?)",
                              (cname, name, minz, geo.encode([hi]), geo.encode([lo]) if lo else None))
        self.db.execute("INSERT INTO lines_idx VALUES(?,?,?,?,?)",
                        (cur.lastrowid, min(xs), max(xs), min(ys), max(ys)))
        self._grow(min(xs), min(ys), max(xs), max(ys))
        self.n["lines"] += 1
        self._progress()

    def area(self, a):
        tags = {t.k: t.v for t in a.tags}
        cls = None
        for (k, v), c in AREA_CLASSES.items():
            if tags.get(k) == v:
                cls = c
                break
        if cls is None and self.buildings and "building" in tags:
            cls = "building"
        cat = poi_category(tags)
        if cls is None and cat is None:
            return
        try:
            rings = []
            for outer in a.outer_rings():
                rings.append([(nd.lon, nd.lat) for nd in outer])
                for inner in a.inner_rings(outer):
                    rings.append([(nd.lon, nd.lat) for nd in inner])
        except (osmium.InvalidLocationError, RuntimeError):
            return
        rings = [r for r in rings if len(r) >= 4]
        if not rings:
            return
        allx = [p[0] for r in rings for p in r]
        ally = [p[1] for r in rings for p in r]
        if cat:
            self._add_poi(cat, tags, sum(allx) / len(allx), sum(ally) / len(ally))
        if cls is None:
            return
        size = geo.ring_area_m2(rings[0])
        # bigger areas show from further out
        if cls == "building":
            minz = 15
        elif size > 50e6:
            minz = 6
        elif size > 5e6:
            minz = 8
        elif size > 500e3:
            minz = 10
        elif size > 50e3:
            minz = 12
        elif size > 2e3:
            minz = 13
        else:
            minz = 14
        hi = [geo.simplify(r, TOL_HI) for r in rings]
        hi = [r for r in hi if len(r) >= 3]
        lo = None
        if minz < LO_ZOOM:
            lo = [geo.simplify(r, TOL_LO) for r in rings]
            lo = [r for r in lo if len(r) >= 4]
        cur = self.db.execute("INSERT INTO areas(cls,name,minz,geom,geom_lo) VALUES(?,?,?,?,?)",
                              (cls, tags.get("name"), minz, geo.encode(hi), geo.encode(lo) if lo else None))
        self.db.execute("INSERT INTO areas_idx VALUES(?,?,?,?,?)",
                        (cur.lastrowid, min(allx), max(allx), min(ally), max(ally)))
        self._grow(min(allx), min(ally), max(allx), max(ally))
        self.n["areas"] += 1
        self._progress()


LO_IDX_ZOOM = 9


def add_lo_index(db):
    """Small R-trees with only the features shown up to zoom 9, so zoomed-out map tiles don't
    have to read (and throw away) every road in the country. Safe to run on an existing nav.db."""
    for t in ("lines", "areas"):
        db.execute("DROP TABLE IF EXISTS %s_lo_idx" % t)
        db.execute("CREATE VIRTUAL TABLE %s_lo_idx USING rtree(id, minx, maxx, miny, maxy)" % t)
        db.execute("INSERT INTO %s_lo_idx SELECT i.id, i.minx, i.maxx, i.miny, i.maxy FROM %s_idx i "
                   "JOIN %s t ON t.id=i.id WHERE t.minz<=?" % (t, t, t), (LO_IDX_ZOOM,))
    db.commit()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="+", help=".osm.pbf (or .osm) extract(s), e.g. from download.geofabrik.de; "
                    "several (netherlands.osm.pbf curacao.osm) go into one map")
    ap.add_argument("output", help="output database, e.g. data/nav.db")
    ap.add_argument("--buildings", action="store_true", help="include building outlines (much bigger)")
    args = ap.parse_args()

    if os.path.exists(args.output):
        os.remove(args.output)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    db = sqlite3.connect(args.output)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.executescript(SCHEMA)

    b = Builder(db, buildings=args.buildings)
    for f in args.input:
        print("Reading %s ..." % f, flush=True)
        # 'flex_mem' keeps node locations in RAM; fine for regional/country extracts
        b.apply_file(f, locations=True, idx="flex_mem")
        db.commit()

    meta = {
        "source": " + ".join(os.path.basename(f) for f in args.input),
        "built": time.strftime("%Y-%m-%d %H:%M"),
        "bbox": json.dumps(b.bbox),
        "counts": json.dumps(b.n),
        "attribution": "© OpenStreetMap contributors, ODbL",
    }
    db.executemany("INSERT INTO meta VALUES(?,?)", meta.items())
    db.commit()
    print("Optimising ...", flush=True)
    add_lo_index(db)
    db.execute("INSERT INTO search(search) VALUES('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    mb = os.path.getsize(args.output) / 1e6
    print("Done: %s  %s  %.1f MB  (%.0fs)" % (args.output, b.n, mb, time.time() - b.t0))


if __name__ == "__main__":
    main()
