#!/usr/bin/env python3
"""Download satellite / aerial imagery into data/map.mbtiles for offline use.

Run on a computer with internet, then copy map.mbtiles to the device's data/
folder. Run it several times to layer sources into one file: a low-detail
world first, then sharper imagery for your home area. Existing tiles are
skipped, so an interrupted download can simply be restarted.

    # 1. whole world, NASA Blue Marble (public domain), zoom 0-8: ~90k tiles, ~1-2 GB
    python3 tools/build_imagery.py data/map.mbtiles --source bluemarble --maxzoom 8

    #    smaller: zoom 0-7 is ~22k tiles, a few hundred MB
    python3 tools/build_imagery.py data/map.mbtiles --source bluemarble --maxzoom 7

    # 2. home area, sharper (Sentinel-2 10 m, non-commercial licence), 60 km around a point
    python3 tools/build_imagery.py data/map.mbtiles --source s2cloudless --around 52.09,5.12,60 \\
        --minzoom 9 --maxzoom 13

    # 3. Netherlands only: PDOK aerial photos (open data), street level for 15 km around home
    python3 tools/build_imagery.py data/map.mbtiles --source pdok --around 52.09,5.12,15 \\
        --minzoom 14 --maxzoom 17

Standard library only. Be kind to the free services: the default is 4 parallel
downloads; don't raise it much.
"""
import argparse
import concurrent.futures as cf
import math
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

SOURCES = {
    "bluemarble": {
        "url": "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/"
               "GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
        "maxzoom": 8,
        "attribution": "NASA Blue Marble: Next Generation (NASA Earth Observatory), public domain",
        "note": "Whole world, 500 m per pixel. Shows land cover, forests, deserts, snow; no roads or buildings.",
    },
    "bluemarble-relief": {
        "url": "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/"
               "GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
        "maxzoom": 8,
        "attribution": "NASA Blue Marble shaded relief and bathymetry, public domain",
        "note": "Same as bluemarble with mountains shaded and sea depth shown.",
    },
    "s2cloudless": {
        "url": "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg",
        "maxzoom": 13,
        "attribution": "Sentinel-2 cloudless 2020 by EOX IT Services GmbH (contains modified Copernicus "
                       "Sentinel data 2020), CC BY-NC-SA 4.0",
        "note": "Whole world, 10 m per pixel, cloud-free. Non-commercial use only. Fields, forests, towns, "
                "big roads are visible. Use for your region, not the whole world (too many tiles).",
    },
    "pdok": {
        "url": "https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_orthoHR/EPSG:3857/{z}/{x}/{y}.jpeg",
        "maxzoom": 19,
        "bbox": (3.2, 50.7, 7.3, 53.6),
        "attribution": "Luchtfoto Beeldmateriaal Nederland via PDOK, open data (CC BY 4.0)",
        "note": "Netherlands only, aerial photos up to ~8 cm. Use zoom 14-17 for your area (17 = ~1 m per pixel).",
    },
}

UA = "doomsday-pocket-computer-offline-cache/1.0 (personal offline map; python urllib)"


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    lat = max(-85.0511, min(85.0511, lat))
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return min(n - 1, max(0, x)), min(n - 1, max(0, y))


def tiles_for(bbox, z):
    w, s, e, n = bbox
    x0, y0 = lonlat_to_tile(w, n, z)
    x1, y1 = lonlat_to_tile(e, s, z)
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            yield z, x, y


def bbox_around(lat, lon, km):
    dlat = km / 111.0
    dlon = km / (111.0 * max(0.05, math.cos(math.radians(lat))))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def intersect(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def open_mbtiles(path, name, attribution):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS metadata(name TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS tiles(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);
    CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles(zoom_level, tile_column, tile_row);
    """)
    old = dict(db.execute("SELECT name, value FROM metadata").fetchall())
    attrs = [a for a in (old.get("attribution") or "").split(" | ") if a]
    if attribution not in attrs:
        attrs.append(attribution)
    meta = {"name": old.get("name") or name, "type": "baselayer", "version": "1",
            "description": "Offline imagery for the pocket survival computer", "format": "jpg",
            "attribution": " | ".join(attrs)}
    db.executemany("INSERT OR REPLACE INTO metadata VALUES(?,?)", meta.items())
    db.commit()
    return db


def fetch(url, tries=4):
    delay = 2
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                ctype = r.headers.get("Content-Type", "")
            if not data or ("image" not in ctype and not data[:3] in (b"\xff\xd8\xff", b"\x89PN")):
                return None  # error page / no data for this tile
            return data
        except urllib.error.HTTPError as e:
            if e.code in (400, 404, 204):
                return None  # tile outside coverage
            if attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                raise
        time.sleep(delay)
        delay *= 2
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output", help="MBTiles file, e.g. data/map.mbtiles (created or added to)")
    ap.add_argument("--source", default="bluemarble", help="one of: %s, or a URL template with {z} {x} {y}"
                    % ", ".join(SOURCES))
    ap.add_argument("--minzoom", type=int, default=0)
    ap.add_argument("--maxzoom", type=int)
    ap.add_argument("--bbox", help="west,south,east,north in degrees (default: whole world / source area)")
    ap.add_argument("--around", help="lat,lon,km: square area around a point")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--attribution", default="", help="attribution text when using a custom URL")
    ap.add_argument("--dry-run", action="store_true", help="only count tiles")
    ap.add_argument("--list", action="store_true", help="describe the built-in sources")
    args = ap.parse_args()

    if args.list:
        for k, s in SOURCES.items():
            print("%-18s max zoom %2d  %s\n%18s licence: %s" % (k, s["maxzoom"], s["note"], "", s["attribution"]))
        return

    src = SOURCES.get(args.source) or {"url": args.source, "maxzoom": 19, "attribution": args.attribution,
                                        "note": "custom source"}
    if "{z}" not in src["url"]:
        sys.exit("Unknown source '%s'. Use --list to see the built-in ones." % args.source)
    maxzoom = min(args.maxzoom if args.maxzoom is not None else src["maxzoom"], src["maxzoom"])

    bbox = (-180.0, -85.05, 180.0, 85.05)
    if args.bbox:
        bbox = tuple(float(v) for v in args.bbox.split(","))
    if args.around:
        lat, lon, km = (float(v) for v in args.around.split(","))
        bbox = bbox_around(lat, lon, km)
    if "bbox" in src:
        bbox = intersect(bbox, src["bbox"])
        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            sys.exit("That area is outside the coverage of '%s'." % args.source)

    jobs = []
    for z in range(args.minzoom, maxzoom + 1):
        jobs.extend(tiles_for(bbox, z))
    print("%s: zoom %d-%d, %d tiles (rough size %.0f-%.0f MB)" % (
        args.source, args.minzoom, maxzoom, len(jobs), len(jobs) * 8 / 1024, len(jobs) * 25 / 1024))
    if args.dry_run:
        return
    if len(jobs) > 400000:
        sys.exit("That is more than 400,000 tiles. Lower --maxzoom or use --around/--bbox for a smaller area.")

    db = open_mbtiles(args.output, args.source, src["attribution"])
    have = set(db.execute("SELECT zoom_level, tile_column, tile_row FROM tiles").fetchall())
    todo = [(z, x, y) for z, x, y in jobs if (z, x, (2 ** z - 1) - y) not in have]
    print("%d already present, downloading %d" % (len(jobs) - len(todo), len(todo)), flush=True)

    # check the source works before starting thousands of requests
    if todo:
        z, x, y = todo[0]
        try:
            fetch(src["url"].format(z=z, x=x, y=y), tries=2)
        except Exception as e:  # noqa: BLE001
            sys.exit("Source not reachable (%s). Check your internet connection or the URL." % e)

    lock = threading.Lock()
    done = [0, 0, 0]  # ok, empty, failed
    t0 = time.time()

    def work(job):
        z, x, y = job
        try:
            data = fetch(src["url"].format(z=z, x=x, y=y))
        except Exception:  # noqa: BLE001
            with lock:
                done[2] += 1
            return
        with lock:
            if data:
                db.execute("INSERT OR REPLACE INTO tiles VALUES(?,?,?,?)", (z, x, (2 ** z - 1) - y, data))
                done[0] += 1
            else:
                done[1] += 1
            n = sum(done)
            if n % 500 == 0:
                db.commit()
                rate = n / max(1, time.time() - t0)
                print("  %d/%d  (%.0f tiles/s, ~%.0f min left)" % (n, len(todo), rate,
                                                                    (len(todo) - n) / max(rate, 0.1) / 60),
                      flush=True)

    try:
        with cf.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as ex:
            list(ex.map(work, todo))
    except KeyboardInterrupt:
        print("Interrupted: progress is saved, run the same command again to continue.")
    db.commit()
    zooms = db.execute("SELECT min(zoom_level), max(zoom_level) FROM tiles").fetchone()
    db.executemany("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                   [("minzoom", str(zooms[0])), ("maxzoom", str(zooms[1]))])
    db.commit()
    db.close()
    print("Done: %d saved, %d empty, %d failed. %s is %.0f MB." % (
        done[0], done[1], done[2], args.output, os.path.getsize(args.output) / 1e6))
    if done[2]:
        print("Some tiles failed: run the same command again to retry them.")


if __name__ == "__main__":
    main()
