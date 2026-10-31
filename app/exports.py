"""Files exchanged with a computer over the direct WiFi link: uploads and downloads."""
import io
import os
import re
import shutil
import sqlite3
import tempfile
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

CHUNK = 1 << 20


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def gpx_waypoints(rows):
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="pocket-survival-computer" xmlns="http://www.topografix.com/GPX/1/1">']
    for name, lat, lon, note, created in rows:
        out.append('  <wpt lat="%.6f" lon="%.6f"><time>%s</time><name>%s</name>%s</wpt>' % (
            lat, lon, _iso(created or time.time()), escape(name or ""),
            "<desc>%s</desc>" % escape(note) if note else ""))
    out.append("</gpx>")
    return "\n".join(out)


def gpx_track(points):
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="pocket-survival-computer" xmlns="http://www.topografix.com/GPX/1/1">',
           "  <trk><name>Walked track</name><trkseg>"]
    for t, lat, lon in points:
        out.append('    <trkpt lat="%.6f" lon="%.6f"><time>%s</time></trkpt>' % (lat, lon, _iso(t)))
    out.append("  </trkseg></trk>\n</gpx>")
    return "\n".join(out)


def parse_gpx_waypoints(data):
    """GPX bytes -> list of (name, lat, lon, desc) from <wpt> and route points."""
    root = ET.fromstring(data)
    pts = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("wpt", "rtept") and "lat" in el.attrib:
            name = desc = ""
            for c in el:
                ct = c.tag.split("}")[-1]
                if ct == "name":
                    name = (c.text or "").strip()
                elif ct in ("desc", "cmt") and not desc:
                    desc = (c.text or "").strip()
            pts.append((name or "GPX point", float(el.attrib["lat"]), float(el.attrib["lon"]), desc))
    return pts


def export(app, name):
    """-> (bytes or str, content type) or (None, None)."""
    db = app.user()
    if name == "waypoints.gpx":
        rows = db.execute("SELECT name, lat, lon, note, created FROM waypoints ORDER BY created").fetchall()
        return gpx_waypoints(rows), "application/gpx+xml"
    if name == "track.gpx":
        return gpx_track(list(app.gps.track)), "application/gpx+xml"
    if name == "weather.csv":
        buf = io.StringIO()
        buf.write("time_utc,temperature_c,pressure_hpa,humidity_pct\n")
        for t, temp, p, rh in db.execute("SELECT t, temp, p, rh FROM weather ORDER BY t"):
            buf.write("%s,%s,%s,%s\n" % (_iso(t), temp, p, "" if rh is None else rh))
        return buf.getvalue(), "text/csv"
    if name == "weather-charts.zip":
        # received weather fax charts (full size) and RTTY texts
        import zipfile
        d = getattr(getattr(app, "shortwave", None), "out_dir", None)
        names = sorted(n for n in os.listdir(d) if n.endswith((".png", ".txt")) and ".small." not in n) \
            if d and os.path.isdir(d) else []
        if not names:
            return None, None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:  # PNGs are already compressed
            for n in names:
                z.write(os.path.join(d, n), n)
        return buf.getvalue(), "application/zip"
    if name == "backup.db":
        # consistent copy of waypoints, presets, settings and weather log
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            dst = sqlite3.connect(tmp.name)
            db.backup(dst)
            dst.close()
            with open(tmp.name, "rb") as f:
                return f.read(), "application/octet-stream"
        finally:
            os.unlink(tmp.name)
    return None, None


def _guide_dir(app):
    return os.path.join(app.library.root, "my-pages")


def file_list(app):
    files = []
    for label, path in (("Map database (nav.db)", app.nav_path), ("Satellite/raster map (map.mbtiles)", app.mbtiles_path)):
        files.append({"label": label, "path": path, "exists": os.path.exists(path),
                      "size": os.path.getsize(path) if os.path.exists(path) else 0,
                      "modified": os.path.getmtime(path) if os.path.exists(path) else None})
    gd = _guide_dir(app)
    pages = sorted(f for f in os.listdir(gd) if f.endswith(".md")) if os.path.isdir(gd) else []
    du = shutil.disk_usage(app.data_dir)
    n_wp = app.user().execute("SELECT count(*) FROM waypoints").fetchone()[0]
    return {"files": files, "my_pages": pages, "free_bytes": du.free, "total_bytes": du.total,
            "waypoints": n_wp, "track_points": len(app.gps.track)}


def _stream_to(path, rfile, n):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as f:
            left = n
            while left > 0:
                chunk = rfile.read(min(CHUNK, left))
                if not chunk:
                    raise OSError("upload interrupted")
                f.write(chunk)
                left -= len(chunk)
            f.flush()
            os.fsync(f.fileno())
        return tmp
    except BaseException:
        os.unlink(tmp)
        raise


def _check_sqlite(path, required_table):
    db = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()
    if required_table not in tables:
        raise ValueError("this is not the right kind of file (missing table '%s')" % required_table)


def receive_upload(app, name, rfile, n):
    if n <= 0:
        raise ValueError("empty upload")
    free = shutil.disk_usage(app.data_dir).free
    if n > free - 200 * 1024 * 1024:  # keep 200 MB spare so the system keeps running
        raise ValueError("not enough space on the SD card (%.0f MB free)" % (free / 1e6))
    low = name.lower()
    if low in ("nav.db", "map.mbtiles"):
        dest = os.path.join(app.data_dir, low)
        tmp = _stream_to(dest, rfile, n)
        try:
            _check_sqlite(tmp, "lines" if low == "nav.db" else "tiles")
        except (ValueError, sqlite3.DatabaseError) as e:
            os.unlink(tmp)
            raise ValueError(str(e))
        os.replace(tmp, dest)  # atomic: the map keeps working until the new file is complete
        if low == "nav.db":
            app.nav_path = dest
        else:
            app.mbtiles_path = dest
        return {"ok": True, "saved": dest, "size": n}
    if low.endswith(".gpx"):
        data = rfile.read(n)
        pts = parse_gpx_waypoints(data)
        db = app.user()
        for nm, lat, lon, desc in pts:
            db.execute("INSERT INTO waypoints(name,lat,lon,icon,note,created) VALUES(?,?,?,?,?,?)",
                       (nm, lat, lon, "pin", desc, time.time()))
        db.commit()
        return {"ok": True, "waypoints_added": len(pts)}
    if low.endswith(".md"):
        safe = re.sub(r"[^a-z0-9\-_.]", "-", low)
        if n > 2 * 1024 * 1024:
            raise ValueError("guide pages must be smaller than 2 MB")
        dest = os.path.join(_guide_dir(app), safe)
        tmp = _stream_to(dest, rfile, n)
        os.replace(tmp, dest)
        app.library.reload()
        return {"ok": True, "saved": "Guide → My pages → " + safe}
    raise ValueError("unsupported file: upload nav.db, map.mbtiles, a .gpx file or a .md guide page")
