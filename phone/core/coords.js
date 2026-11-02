// Typed coordinates: decimal degrees, degrees + decimal minutes, or degrees minutes seconds,
// with N/S/E/W letters before or after the numbers, or plain signs.
//   "52.3702, 4.8952"   "52,3702 4,8952"   "52 22.2 N 004 53.4 E"   "N52 22.2 E4 53.4"   52°22'12.7"N 4°53'42.7"E

export function parseCoords(text) {
  if (!text) return null;
  let s = String(text).trim().toUpperCase();
  // a decimal comma ("52,37 4,89"): only when there is no other separator between the two numbers
  if (/^-?\d+,\d+\s+-?\d+,\d+$/.test(s)) s = s.replace(/(\d),(\d)/g, "$1.$2");
  s = s.replace(/[°º'’′"”″:]/g, " ").replace(/,/g, " ").replace(/\s+/g, " ").trim();
  // split into two halves at a hemisphere letter if there is one
  const tokens = s.match(/[NSEW]|[-+]?\d+(?:\.\d+)?/g);
  if (!tokens || tokens.join("").length < s.replace(/ /g, "").length) return null;
  const groups = [];
  let cur = { nums: [], hemi: null };
  const push = () => { if (cur.nums.length || cur.hemi) groups.push(cur); cur = { nums: [], hemi: null }; };
  const letters = tokens.filter((x) => /[NSEW]/.test(x)).length;
  const lettersFirst = letters && /[NSEW]/.test(tokens[0]);
  for (const tk of tokens) {
    if (/[NSEW]/.test(tk)) {
      if (lettersFirst) { push(); cur.hemi = tk; } else { cur.hemi = tk; push(); }
    } else cur.nums.push(parseFloat(tk));
  }
  push();
  let parts;
  if (letters === 2 && groups.length === 2) parts = groups;
  else if (letters === 0) {
    const n = groups[0] ? groups[0].nums : [];
    if (n.length % 2 !== 0 || n.length === 0 || n.length > 6) return null;
    const h = n.length / 2;
    parts = [{ nums: n.slice(0, h), hemi: null }, { nums: n.slice(h), hemi: null }];
  } else return null;
  const val = (p) => {
    const [d, m = 0, sec = 0] = p.nums;
    if (p.nums.length < 1 || p.nums.length > 3 || m < 0 || m >= 60 || sec < 0 || sec >= 60) return null;
    let v = Math.abs(d) + m / 60 + sec / 3600;
    if (d < 0 || Object.is(d, -0) || p.hemi === "S" || p.hemi === "W") v = -v;
    return v;
  };
  let a = parts[0], b = parts[1];
  if (a.hemi === "E" || a.hemi === "W") [a, b] = [b, a];
  if ((a.hemi && !"NS".includes(a.hemi)) || (b.hemi && !"EW".includes(b.hemi))) return null;
  const lat = val(a), lon = val(b);
  if (lat == null || lon == null || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

const pad = (n, w) => String(n).padStart(w, "0");

/** 52°22.212'N 004°53.712'E (the format used on charts and by most GPS units). */
export function formatDM(lat, lon) {
  const f = (v, w, pos, neg) => {
    const a = Math.abs(v), d = Math.floor(a);
    let m = (a - d) * 60;
    let dd = d;
    if (m >= 59.9995) { dd += 1; m = 0; }
    return `${pad(dd, w)}°${m.toFixed(3).padStart(6, "0")}'${v >= 0 ? pos : neg}`;
  };
  return `${f(lat, 2, "N", "S")} ${f(lon, 3, "E", "W")}`;
}
