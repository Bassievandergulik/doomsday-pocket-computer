// Simulated sensors, so the app can be tried on a computer or a phone without moving.
// A phone lies still for alignment, then someone walks a square with it, screen up, pointing ahead.
// Buttons at the bottom of the screen fake a GPS jump, a GPS speed lie, or a GPS outage.

export function startDemo({ onMotion, onOrientation, onPosition }) {
  const RAD = Math.PI / 180, G0 = 9.80665;
  const st = { t0: performance.now() / 1000, psi: 0, lat: 52.3702, lon: 4.8952, speed: 0, turn: 0,
    gpsOff: false, jump: 0, lie: 0, phase: 0, lastFix: 0 };
  const noise = (s) => s * (Math.random() + Math.random() + Math.random() - 1.5);
  const bias = [0.2, -0.15, 0.3];   // gyro zero offset the alignment has to find (deg/s)

  function plan(el) {
    // 0-35 s still, then walk 40 s legs at 1.4 m/s with 90 degree right turns of 6 s
    if (el < 35) return { speed: 0, turn: 0 };
    const k = (el - 35) % 46;
    return k < 40 ? { speed: 1.4, turn: 0 } : { speed: 1.0, turn: 15 };
  }

  setInterval(() => {
    const t = performance.now() / 1000, el = t - st.t0, dt = 0.02;
    const p = plan(el);
    st.speed = p.speed; st.turn = p.turn;
    st.psi = (st.psi + st.turn * dt + 360) % 360;
    st.lat += (st.speed * Math.cos(st.psi * RAD) * dt) / 111320;
    st.lon += (st.speed * Math.sin(st.psi * RAD) * dt) / (111320 * Math.cos(st.lat * RAD));
    const bump = st.speed > 0 ? 0.3 * Math.sin(2 * Math.PI * 1.8 * el) : 0;   // footsteps, ~1.8 per second
    // phone axes, screen up: gravity reads +1 g on z (as the W3C spec says); a right turn is a negative z rotation
    onMotion({
      accelerationIncludingGravity: { x: noise(0.05), y: noise(0.05), z: G0 * (1 + bump) + noise(0.05) },
      rotationRate: { alpha: bias[2] - st.turn + noise(0.1), beta: bias[0] + noise(0.1), gamma: bias[1] + noise(0.1) },
    });
    if (Math.round(el / dt) % 10 === 0) {
      onOrientation({ beta: 0, gamma: 0, alpha: 0, webkitCompassHeading: (st.psi + noise(6) + 360) % 360 }, false);
    }
    if (!st.gpsOff && t - st.lastFix >= 1) {
      st.lastFix = t;
      let lat = st.lat, lon = st.lon, speed = st.speed, heading = st.speed > 0.3 ? st.psi : NaN;
      if (st.jump) { lat += st.jump / 111320; }
      if (st.lie) { speed = st.lie; heading = st.psi; }
      onPosition({ coords: { latitude: lat + noise(0.00002), longitude: lon + noise(0.00003), speed, heading, accuracy: 5 },
        timestamp: Date.now() });
    }
  }, 20);

  const bar = document.createElement("div");
  bar.id = "demo-bar";
  bar.innerHTML = `<span class="small muted">Simulated sensors:</span>
    <button data-a="jump">GPS jump 1 km</button><button data-a="lie">GPS says 15 m/s</button><button data-a="off">GPS off</button>`;
  bar.style.cssText = "position:sticky;bottom:0;display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:8px 16px;background:var(--card);border-top:1px solid var(--line);max-width:560px;margin:0 auto";
  document.body.appendChild(bar);
  bar.addEventListener("click", (e) => {
    const a = e.target.dataset.a;
    if (a === "jump") { st.jump = st.jump ? 0 : 1000; e.target.textContent = st.jump ? "Undo GPS jump" : "GPS jump 1 km"; }
    if (a === "lie") { st.lie = st.lie ? 0 : 15; e.target.textContent = st.lie ? "Undo speed lie" : "GPS says 15 m/s"; }
    if (a === "off") { st.gpsOff = !st.gpsOff; e.target.textContent = st.gpsOff ? "GPS on" : "GPS off"; }
  });
}
