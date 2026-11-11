// Offline canvas map: draws vector tiles from /vt/z/x/y (and optional raster
// tiles from /tiles/z/x/y) with touch pan, pinch zoom and long-press menu.
"use strict";

const TILE = 256, MAX_DATA_Z = 14;

const AREA_STYLE = {
  water: "#a9cbe6", wetland: "#c4dcd6", forest: "#b5d29e", grass: "#d3e5b5", farm: "#ece8d2",
  urban: "#dcd6d0", sand: "#f1e3b3", rock: "#d0ccc6", ice: "#eef4f8", building: "#cbbfb4",
};
const AREA_ORDER = ["farm", "grass", "urban", "forest", "wetland", "sand", "rock", "ice", "water", "building"];
// class: [colour, width at z14, min width]
const LINE_STYLE = {
  coast: ["#5d8fbd", 1.5, 1], river: ["#7fb0db", 4, 1.2], canal: ["#7fb0db", 3, 1], stream: ["#8fbde3", 1.5, .6],
  power: ["#999", .8, .4], rail: ["#666", 2, .8], path: ["#b05a3c", 1.2, .6], track: ["#9a7b4f", 1.6, .6],
  service: ["#fff", 2, .6], minor: ["#fff", 3.5, .8], tertiary: ["#fdfcd0", 5, 1], secondary: ["#f8d98a", 6, 1.2],
  primary: ["#f5b971", 7, 1.4], trunk: ["#ef8f6a", 8, 1.6], motorway: ["#e5706a", 9, 2],
};
const LINE_ORDER = ["coast", "stream", "canal", "river", "power", "path", "track", "service", "minor",
  "tertiary", "secondary", "primary", "trunk", "rail", "motorway"];
const POI_STYLE = {
  water: ["#1e88e5", "W"], shelter: ["#6d4c41", "S"], hospital: ["#d32f2f", "H"], doctor: ["#e57373", "+"],
  pharmacy: ["#2e7d32", "+"], aed: ["#c62828", "♥"], police: ["#283593", "P"], fire: ["#e65100", "F"],
  fuel: ["#455a64", "⛽"], food: ["#f9a825", "F"], hardware: ["#5d4037", "T"], camp: ["#33691e", "▲"],
  toilet: ["#00838f", "WC"], phone: ["#6a1b9a", "☎"], peak: ["#4e342e", "▲"], cave: ["#3e2723", "C"],
};

const WORLD_SEA = "#a9cbe6", WORLD_LAND = "#efebe3", WORLD_EDGE = "#8f8778";

function lon2x(lon, z) { return (lon + 180) / 360 * TILE * Math.pow(2, z); }
function lat2y(lat, z) {
  const s = Math.sin(lat * Math.PI / 180);
  return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * TILE * Math.pow(2, z);
}
function x2lon(x, z) { return x / (TILE * Math.pow(2, z)) * 360 - 180; }
function y2lat(y, z) {
  const n = Math.PI - 2 * Math.PI * y / (TILE * Math.pow(2, z));
  return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

class OfflineMap {
  constructor(canvas) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.lat = 52.1; this.lon = 5.3; this.zoom = 8;
    this.tiles = new Map();   // "z/x/y" -> data | "loading"
    this.raster = new Map();
    this.useRaster = false;
    this.overlay = { pos: null, heading: null, waypoints: [], target: null, track: [], marks: [] };
    this.onLongPress = null;
    this.onMove = null;
    this._pending = false;
    this._setupInput();
    new ResizeObserver(() => this.resize()).observe(canvas);
    this.resize();
  }

  resize() {
    const r = this.c.getBoundingClientRect();
    this.dpr = window.devicePixelRatio || 1;
    this.w = r.width; this.h = r.height;
    this.c.width = Math.max(1, r.width * this.dpr); this.c.height = Math.max(1, r.height * this.dpr);
    this.redraw();
  }

  setView(lat, lon, zoom) {
    this.lat = Math.max(-85, Math.min(85, lat));
    this.lon = ((lon + 540) % 360) - 180;
    if (zoom !== undefined) this.zoom = Math.max(3, Math.min(19, zoom));
    this.redraw();
    if (this.onMove) this.onMove();
  }

  screenToLatLon(sx, sy) {
    const cx = lon2x(this.lon, this.zoom) + sx - this.w / 2;
    const cy = lat2y(this.lat, this.zoom) + sy - this.h / 2;
    return [y2lat(cy, this.zoom), x2lon(cx, this.zoom)];
  }

  zoomAt(sx, sy, factor) {
    const [lat, lon] = this.screenToLatLon(sx, sy);
    const nz = Math.max(3, Math.min(19, this.zoom + Math.log2(factor)));
    // keep the point under the finger fixed
    const px = lon2x(lon, nz) - (sx - this.w / 2), py = lat2y(lat, nz) - (sy - this.h / 2);
    this.zoom = nz;
    this.setView(y2lat(py, nz), x2lon(px, nz));
  }

  _setupInput() {
    const pts = new Map();
    let last = null, pinch = null, pressTimer = null, moved = false, lastTap = 0;
    const c = this.c;
    const local = (e) => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, local(e));
      moved = false;
      if (pts.size === 1) {
        last = local(e);
        const p = last;
        pressTimer = setTimeout(() => { if (!moved && this.onLongPress) this.onLongPress(...this.screenToLatLon(...p)); }, 650);
      } else if (pts.size === 2) {
        clearTimeout(pressTimer);
        const [a, b] = [...pts.values()];
        pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), z: this.zoom };
      }
    });
    c.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId)) return;
      const p = local(e);
      pts.set(e.pointerId, p);
      if (pts.size === 2 && pinch) {
        const [a, b] = [...pts.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        const target = pinch.z + Math.log2(d / pinch.d);
        this.zoomAt(mid[0], mid[1], Math.pow(2, target - this.zoom));
        moved = true;
      } else if (pts.size === 1 && last) {
        const dx = p[0] - last[0], dy = p[1] - last[1];
        if (Math.abs(dx) + Math.abs(dy) > 3) { moved = true; clearTimeout(pressTimer); }
        if (moved) {
          const cx = lon2x(this.lon, this.zoom) - dx, cy = lat2y(this.lat, this.zoom) - dy;
          this.setView(y2lat(cy, this.zoom), x2lon(cx, this.zoom));
          if (this.onPan) this.onPan();
          last = p;
        }
      }
    });
    const up = (e) => {
      clearTimeout(pressTimer);
      pts.delete(e.pointerId);
      if (pts.size < 2) pinch = null;
      if (pts.size === 1) last = [...pts.values()][0];
      if (!moved && pts.size === 0 && e.type === "pointerup") {
        const now = Date.now();
        if (now - lastTap < 300) { this.zoomAt(...local(e), 2); lastTap = 0; } else lastTap = now;
      }
    };
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", (e) => { e.preventDefault(); this.zoomAt(...local(e), e.deltaY < 0 ? 1.25 : 0.8); },
      { passive: false });
  }

  _fetchTile(key) {
    this.tiles.set(key, "loading");
    fetch("/vt/" + key).then(r => r.json()).then(d => {
      this.tiles.set(key, d);
      if (this.tiles.size > 400) {  // drop oldest
        for (const k of this.tiles.keys()) { if (this.tiles.size <= 300) break; this.tiles.delete(k); }
      }
      this.redraw();
    }).catch(() => this.tiles.delete(key));
  }

  _rasterTile(z, x, y) {
    const key = z + "/" + x + "/" + y;
    let img = this.raster.get(key);
    if (!img) {
      img = new Image();
      img.onload = () => { img.ok = true; this.redraw(); };
      img.onerror = () => { img.failed = true; this.redraw(); };
      img.src = "/tiles/" + key + ".png";
      this.raster.set(key, img);
      if (this.raster.size > 400) this.raster.delete(this.raster.keys().next().value);
    }
    return img;
  }

  // Draw a raster tile, or the matching part of a lower-zoom tile when this one
  // is missing (e.g. world imagery to zoom 8, sharp imagery only around home).
  // (sx, sy, sw) is the wanted square inside the tile, in 256-pixel units.
  _rasterDraw(ctx, z, x, y, sx, sy, sw, dx, dy, ds) {
    const img = this._rasterTile(z, x, y);
    if (img.ok) {
      const k = img.naturalWidth / TILE;
      ctx.drawImage(img, sx * k, sy * k, sw * k, sw * k, dx, dy, ds + 0.5, ds + 0.5);
      return;
    }
    if (z === 0) return;
    const parent = this.raster.get((z - 1) + "/" + (x >> 1) + "/" + (y >> 1));
    if (img.failed || (parent && parent.ok))
      this._rasterDraw(ctx, z - 1, x >> 1, y >> 1, (x & 1) * 128 + sx / 2, (y & 1) * 128 + sy / 2, sw / 2, dx, dy, ds);
  }

  // the airport drawn nearest to a map point, if one is within a finger's width
  airportNear(lat, lon, px = 30) {
    const z = this.zoom, ox = lon2x(this.lon, z) - this.w / 2, oy = lat2y(this.lat, z) - this.h / 2;
    const x = lon2x(lon, z) - ox, y = lat2y(lat, z) - oy;
    let best = null, bd = px;
    for (const [ax, ay, a] of this._airports || []) {
      const d = Math.hypot(ax - x, ay - y);
      if (d < bd) { bd = d; best = { icao: a[0], name: a[1], lon: a[3], lat: a[4], info: a[5] }; }
    }
    return best;
  }

  redraw() {
    if (this._pending) return;
    this._pending = true;
    requestAnimationFrame(() => { this._pending = false; this._draw(); });
  }

  _draw() {
    const ctx = this.ctx, z = this.zoom, w = this.w, h = this.h;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = "#efebe3";
    ctx.fillRect(0, 0, w, h);
    const ox = lon2x(this.lon, z) - w / 2, oy = lat2y(this.lat, z) - h / 2;
    const P = (lon, lat) => [lon2x(lon, z) - ox, lat2y(lat, z) - oy];

    const tz = Math.min(MAX_DATA_Z, Math.max(0, Math.floor(z)));
    const scale = Math.pow(2, z - tz), ts = TILE * scale;
    const x0 = Math.floor(ox / ts), x1 = Math.floor((ox + w) / ts);
    const y0 = Math.floor(oy / ts), y1 = Math.floor((oy + h) / ts);
    const n = Math.pow(2, tz);
    const visible = [], worldTiles = [];
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) {
      if (y < 0 || y >= n) continue;
      const xx = ((x % n) + n) % n;
      const key = tz + "/" + xx + "/" + y;
      const d = this.tiles.get(key);
      if (d === undefined) this._fetchTile(key);
      else if (d !== "loading") {
        visible.push(d);
        // (x - xx) * ts shifts tiles of the next/previous copy of the world when the map wraps
        if (d.world) worldTiles.push([d.world, x * ts - ox, y * ts - oy, (x - xx) * ts]);
      }
    }

    if (this.useRaster) {
      const rz = Math.min(18, Math.round(z)), rs = TILE * Math.pow(2, z - rz), rn = Math.pow(2, rz);
      for (let x = Math.floor(ox / rs); x <= Math.floor((ox + w) / rs); x++)
        for (let y = Math.floor(oy / rs); y <= Math.floor((oy + h) / rs); y++) {
          if (y < 0 || y >= rn) continue;
          this._rasterDraw(ctx, rz, ((x % rn) + rn) % rn, y, 0, 0, TILE, x * rs - ox, y * rs - oy, rs);
        }
    }

    const path = (flat, close) => {
      for (let i = 0; i < flat.length; i += 2) {
        const [px, py] = P(flat[i], flat[i + 1]);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      if (close) ctx.closePath();
    };

    // rough world map (sea, land, lakes) under the detailed map, each tile clipped to its square
    if (!this.useRaster) {
      for (const [wd, tx, ty, shift] of worldTiles) {
        ctx.save();
        ctx.beginPath(); ctx.rect(tx, ty, ts + 0.5, ts + 0.5); ctx.clip();
        ctx.fillStyle = WORLD_SEA; ctx.fillRect(tx, ty, ts + 0.5, ts + 0.5);
        ctx.translate(shift, 0);
        for (const [layer, fill] of [["land", WORLD_LAND], ["lakes", WORLD_SEA]]) {
          for (const poly of wd[layer]) {
            ctx.beginPath();
            for (const ring of poly) path(ring, true);
            ctx.fillStyle = fill; ctx.fill("evenodd");
            ctx.strokeStyle = layer === "land" ? WORLD_EDGE : "#7fa9cf"; ctx.lineWidth = 0.8; ctx.stroke();
          }
        }
        ctx.restore();
      }
    }

    // areas
    if (!this.useRaster) {
      for (const cls of AREA_ORDER) {
        ctx.beginPath();
        let any = false;
        for (const t of visible) for (const a of t.areas) if (a[0] === cls) { any = true; for (const ring of a[1]) path(ring, true); }
        if (any) { ctx.fillStyle = AREA_STYLE[cls]; ctx.fill("evenodd"); }
      }
    }
    // lines
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const wf = Math.pow(2, (z - 14) * 0.75);
    for (const cls of LINE_ORDER) {
      const st = LINE_STYLE[cls];
      ctx.beginPath();
      let any = false;
      for (const t of visible) for (const l of t.lines) if (l[0] === cls) { any = true; for (const part of l[2]) path(part, false); }
      if (!any) continue;
      const lw = Math.max(st[2], st[1] * wf);
      if (["minor", "service", "tertiary", "secondary", "primary", "trunk", "motorway"].includes(cls) && lw > 1.5) {
        ctx.strokeStyle = "#a59b8e"; ctx.lineWidth = lw + 1.5; ctx.stroke();
      }
      ctx.strokeStyle = st[0]; ctx.lineWidth = lw;
      if (cls === "path" || cls === "track") ctx.setLineDash([lw * 2.5, lw * 1.8]);
      if (cls === "rail") ctx.setLineDash([6, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // road names at high zoom (simple: at middle of the longest segment)
    if (z >= 16) {
      ctx.font = "11px sans-serif"; ctx.fillStyle = "#333"; ctx.textAlign = "center";
      const seen = new Set();
      for (const t of visible) for (const l of t.lines) {
        if (!l[1] || seen.has(l[1])) continue;
        const f = l[2][0];
        if (f.length < 4) continue;
        const m = Math.floor(f.length / 4) * 2;
        const [ax, ay] = P(f[m - 2] ?? f[0], f[m - 1] ?? f[1]), [bx, by] = P(f[m], f[m + 1]);
        let ang = Math.atan2(by - ay, bx - ax);
        if (ang > Math.PI / 2) ang -= Math.PI; if (ang < -Math.PI / 2) ang += Math.PI;
        seen.add(l[1]);
        ctx.save(); ctx.translate((ax + bx) / 2, (ay + by) / 2); ctx.rotate(ang);
        ctx.strokeStyle = "rgba(255,255,255,.85)"; ctx.lineWidth = 3; ctx.strokeText(l[1], 0, -3); ctx.fillText(l[1], 0, -3);
        ctx.restore();
      }
    }

    // track
    const ov = this.overlay;
    if (ov.track.length > 1) {
      ctx.beginPath();
      ov.track.forEach((p, i) => { const [x, y] = P(p[1], p[0]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.strokeStyle = "rgba(156,39,176,.8)"; ctx.lineWidth = 3; ctx.stroke();
    }

    // POIs
    if (z >= 12) {
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const r = z >= 15 ? 9 : 6;
      for (const t of visible) for (const p of t.pois) {
        const st = POI_STYLE[p[1]] || ["#555", "?"];
        const [x, y] = P(p[3], p[4]);
        if (x < -10 || y < -10 || x > w + 10 || y > h + 10) continue;
        ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fillStyle = st[0]; ctx.fill();
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
        if (r > 6) { ctx.fillStyle = "#fff"; ctx.font = "bold 10px sans-serif"; ctx.fillText(st[1], x, y + 0.5); }
        if (z >= 16 && p[2]) { ctx.fillStyle = "#222"; ctx.font = "10px sans-serif"; ctx.fillText(p[2], x, y + r + 7); }
      }
    }

    // place labels, larger places first, skip overlaps
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const boxes = [];
    const label = (text, x, y, font, color, halo) => {
      ctx.font = font;
      const tw = ctx.measureText(text).width, fs = parseInt(font.match(/(\d+)px/)[1]);
      const b = [x - tw / 2 - 2, y - fs / 2 - 2, x + tw / 2 + 2, y + fs / 2 + 2];
      if (boxes.some(o => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1])) return false;
      boxes.push(b);
      if (halo) { ctx.strokeStyle = halo; ctx.lineWidth = 3; ctx.strokeText(text, x, y); }
      ctx.fillStyle = color; ctx.fillText(text, x, y);
      return true;
    };
    // country and sea names
    const seenLbl = new Set();
    for (const [wd] of worldTiles) for (const l of wd.labels) {
      if (seenLbl.has(l[1])) continue;
      seenLbl.add(l[1]);
      const [x, y] = P(l[2], l[3]);
      if (l[0] === "country") label(l[1], x, y, "bold 12px sans-serif", "#4a4238", "rgba(255,255,255,.8)");
      else label(l[1], x, y, "italic 11px serif", "#2f5f8a", null);
    }
    // airports: plane symbol, ICAO code next to it. Zoomed out they are small dots that
    // do not cover each other or the names.
    this._airports = [];
    const seenAp = new Set(), dots = [];
    for (const t of visible) for (const a of (t.airports || [])) {
      if (seenAp.has(a[0])) continue;
      seenAp.add(a[0]);
      const [x, y] = P(a[3], a[4]);
      if (x < -20 || y < -20 || x > w + 20 || y > h + 20) continue;
      const big = a[2] === "large", small = z < 8;
      const r = small ? (big ? 4.5 : 3.5) : (big ? 8 : 6.5);
      if (small && dots.some(d => Math.hypot(d[0] - x, d[1] - y) < 12)) continue;
      dots.push([x, y]);
      this._airports.push([x, y, a]);
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7);
      ctx.fillStyle = big ? "#5e35b1" : "#7e57c2"; ctx.fill(); ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
      if (!small) { ctx.fillStyle = "#fff"; ctx.font = (big ? 11 : 9) + "px sans-serif"; ctx.fillText("✈", x, y + 0.5); }
      if (z >= 8 || (big && z >= 6)) {
        const text = a[0] + (z >= 10 ? "  " + a[1] : "");
        ctx.font = "bold 10px sans-serif";
        label(text, x + r + 3 + ctx.measureText(text).width / 2, y, ctx.font, "#4527a0", "rgba(255,255,255,.85)");
      }
    }
    const size = { city: 16, town: 14, village: 12, suburb: 12, hamlet: 11 };
    const places = [];
    for (const t of visible) for (const p of t.places) places.push(p);
    places.sort((a, b) => (size[b[0]] || 10) - (size[a[0]] || 10));
    for (const p of places) {
      const fs = size[p[0]] || 10;
      const [x, y] = P(p[2], p[3]);
      ctx.font = (fs >= 14 ? "bold " : "") + fs + "px sans-serif";
      const tw = ctx.measureText(p[1]).width;
      const b = [x - tw / 2 - 2, y - fs / 2 - 2, x + tw / 2 + 2, y + fs / 2 + 2];
      if (boxes.some(o => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1])) continue;
      boxes.push(b);
      ctx.strokeStyle = "rgba(255,255,255,.9)"; ctx.lineWidth = 3; ctx.strokeText(p[1], x, y);
      ctx.fillStyle = "#222"; ctx.fillText(p[1], x, y);
    }

    // waypoints & marks
    for (const wp of ov.waypoints.concat(ov.marks)) {
      const [x, y] = P(wp.lon, wp.lat);
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - 7, y - 16); ctx.lineTo(x + 7, y - 16); ctx.closePath();
      ctx.fillStyle = wp.mark ? "#ff9800" : "#e53935"; ctx.fill(); ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
      if (z >= 11 && wp.name) {
        ctx.font = "11px sans-serif"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 3;
        ctx.strokeText(wp.name, x, y - 23); ctx.fillStyle = "#b71c1c"; ctx.fillText(wp.name, x, y - 23);
      }
    }

    // target line
    if (ov.pos && ov.target) {
      const [ax, ay] = P(ov.pos.lon, ov.pos.lat), [bx, by] = P(ov.target.lon, ov.target.lat);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by);
      ctx.setLineDash([8, 6]); ctx.strokeStyle = "#e53935"; ctx.lineWidth = 2.5; ctx.stroke(); ctx.setLineDash([]);
    }

    // own position
    if (ov.pos) {
      const [x, y] = P(ov.pos.lon, ov.pos.lat);
      if (ov.pos.err_m) {  // estimated position: show how far off it may be
        const mppHere = 156543.03 * Math.cos(this.lat * Math.PI / 180) / Math.pow(2, z);
        ctx.beginPath(); ctx.arc(x, y, Math.max(10, ov.pos.err_m / mppHere), 0, 7);
        ctx.fillStyle = "rgba(245,124,0,.15)"; ctx.fill();
        ctx.strokeStyle = "rgba(245,124,0,.8)"; ctx.lineWidth = 1.5; ctx.stroke();
      }
      if (ov.heading != null) {
        ctx.save(); ctx.translate(x, y); ctx.rotate(ov.heading * Math.PI / 180);
        ctx.beginPath(); ctx.moveTo(0, -20); ctx.lineTo(-7, -6); ctx.lineTo(7, -6); ctx.closePath();
        ctx.fillStyle = "rgba(25,118,210,.75)"; ctx.fill(); ctx.restore();
      }
      ctx.beginPath(); ctx.arc(x, y, 8, 0, 7); ctx.fillStyle = ov.pos.err_m || ov.pos.manual ? "#f57c00" : "#1976d2"; ctx.fill();
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 3; ctx.stroke();
    }

    // scale bar
    const mpp = 156543.03 * Math.cos(this.lat * Math.PI / 180) / Math.pow(2, z);
    let meters = mpp * 90;
    const pow = Math.pow(10, Math.floor(Math.log10(meters)));
    meters = [1, 2, 5].map(m => m * pow).filter(m => m <= meters).pop() || pow;
    const px = meters / mpp;
    ctx.fillStyle = "rgba(255,255,255,.8)"; ctx.fillRect(6, 6, px + 8, 18);
    ctx.strokeStyle = "#222"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(10, 14); ctx.lineTo(10, 19); ctx.lineTo(10 + px, 19); ctx.lineTo(10 + px, 14); ctx.stroke();
    ctx.fillStyle = "#222"; ctx.font = "10px sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
    ctx.fillText(meters >= 1000 ? meters / 1000 + " km" : meters + " m", 14, 16);
  }
}
