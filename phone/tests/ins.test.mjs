// Port of tests/test_ins.py for the phone INS. Simulated sensors and clock; run with: node --test phone/tests
import { test } from "node:test";
import assert from "node:assert/strict";
import { INS, DeadReckoner, StepDetector, G, wrap180 } from "../core/ins.js";
import { parseCoords } from "../core/coords.js";

function rng(seed) {
  let s = seed >>> 0;
  const u = () => { s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  return (sd) => sd * Math.sqrt(-2 * Math.log(u() || 1e-12)) * Math.cos(2 * Math.PI * u());
}

const near = (a, b, d, msg) => assert.ok(Math.abs(a - b) <= d, `${msg || ""} ${a} not within ${d} of ${b}`);
const RAD = Math.PI / 180;

class Sim {
  constructor({ seed = 1, sea = false, bias = [0.3, -0.2, 0.5], model = "ICM-42688-P" } = {}) {
    this.gauss = rng(seed);
    this.t = 1000;
    this.bias = bias;
    this.fix = { mode: 0 };
    this.steps = 0;
    this.ins = new INS({ model, getSea: () => sea, getSteps: () => this.steps, clock: () => this.t });
    this.psi = 90; this.lat = 50; this.lon = -10;
    this.speed = 0; this.accFwd = 0; this.v = [0, 0]; this.acc = [0, 0];
    this.turn = 0; this.rollAmp = 0; this.compassOn = true; this.compassErr = 0;
  }

  step(seconds, { gpsEvery = 1, gps = true, gpsPos = null, gpsVel = null, gpsTrack = null } = {}) {
    const n = Math.round(seconds * 50);
    for (let k = 0; k < n; k++) {
      this.t += 0.02;
      this.psi = (this.psi + this.turn * 0.02) % 360;
      this.speed += this.accFwd * 0.02;
      const v = [this.speed * Math.sin(this.psi * RAD), this.speed * Math.cos(this.psi * RAD)];
      this.acc = [(v[0] - this.v[0]) / 0.02, (v[1] - this.v[1]) / 0.02];
      this.v = v;
      this.lat += (this.v[1] * 0.02) / 111320;
      this.lon += (this.v[0] * 0.02) / (111320 * Math.cos(this.lat * RAD));
      const phi = this.rollAmp * Math.sin(2 * Math.PI * 0.15 * this.t);
      const dphi = this.rollAmp * 2 * Math.PI * 0.15 * Math.cos(2 * Math.PI * 0.15 * this.t);
      const up = [0, Math.sin(phi * RAD), Math.cos(phi * RAD)];
      const s = Math.sin(this.psi * RAD), c = Math.cos(this.psi * RAD);
      const af = (this.acc[0] * s + this.acc[1] * c) / G;
      const al = (-this.acc[0] * c + this.acc[1] * s) / G;
      const a = [af + this.gauss(0.01), al + up[1] + this.gauss(0.01), up[2] + this.gauss(0.01)];
      const g = [this.bias[0] + dphi + this.gauss(0.05), this.bias[1] - this.turn * up[1] + this.gauss(0.05),
        this.bias[2] - this.turn * up[2] + this.gauss(0.05)];
      this.ins.feed(this.t, a, g);
      if (k % 10 === 0 && this.compassOn) this.ins.feedCompass(this.t, (this.psi + this.compassErr + this.gauss(4) + 360) % 360);
      if (gps && k % Math.round(50 * gpsEvery) === 0) this.sendFix(gpsPos, gpsVel, gpsTrack);
    }
  }

  sendFix(pos, vel, track) {
    const [lat, lon] = pos || [this.lat, this.lon];
    const [ve, vn] = vel || this.v;
    const speed = Math.hypot(ve, vn);
    const trk = track != null ? track : speed > 0.3 ? ((Math.atan2(ve, vn) / RAD) + 360) % 360 : null;
    this.fix = { mode: 3, lat, lon, speed, track: trk, hdop: 1, time_local: this.t };
    return this.ins.vet(this.fix);
  }
}

test("align, then hold heading without compass, then track a turn", () => {
  const s = new Sim();
  s.step(10);
  assert.equal(s.ins.status().state, "align");
  assert.equal(s.ins.heading(), null);
  s.step(30);
  const st = s.ins.status();
  assert.equal(st.state, "nav");
  near(st.heading, 90, 3);
  near(st.gyroBias[2], 0.5, 0.03);
  s.compassOn = false;
  s.step(120);
  near(s.ins.heading(), 90, 1.5);
  s.turn = 10; s.step(9); s.turn = 0;
  near(s.ins.heading(), 180, 2);
});

test("movement restarts a land alignment", () => {
  const s = new Sim();
  s.step(20);
  s.turn = 40; s.step(3); s.turn = 0;
  assert.equal(s.ins.status().state, "align");
  assert.ok(s.ins.status().alignPct < 10);
});

test("sea alignment tolerates rocking", () => {
  const s = new Sim({ sea: true });
  s.rollAmp = 8;
  s.step(70);
  assert.equal(s.ins.status().state, "nav");
  near(s.ins.heading(), 90, 4);
});

test("rolling boat and a magnet nearby", () => {
  const s = new Sim();
  s.step(160);
  s.rollAmp = 12; s.compassErr = 25;
  s.step(60);
  near(s.ins.heading(), 90, 6);
});

test("tilted device still tracks a turn", () => {
  const s = new Sim();
  s.step(40);
  s.compassOn = false; s.rollAmp = 40; s.turn = 10;
  s.step(9);
  near(s.ins.heading(), 180, 4);
});

test("heading set by hand", () => {
  const s = new Sim();
  s.step(40);
  s.ins.setHeading(200);
  near(s.ins.heading(), 200, 0.1);
});

test("phone noise model also aligns and tracks a turn", () => {
  const s = new Sim({ model: "phone", seed: 7 });
  s.step(40);
  assert.equal(s.ins.status().state, "nav");
  s.compassOn = false; s.turn = -10; s.step(9); s.turn = 0;
  near(wrap180(s.ins.heading()), 0, 3);
});

function cruise(seconds = 30, opts = {}) {
  const s = new Sim(opts);
  s.step(40);
  s.psi = 0;
  s.ins.setHeading(0);
  s.speed = 5;
  s.step(seconds);
  return s;
}

test("honest GPS is never flagged", () => {
  const s = cruise(60);
  s.accFwd = 0.5; s.step(10); s.accFwd = 0;
  s.turn = 6; s.step(15); s.turn = 0;
  s.step(20);
  const st = s.ins.status();
  assert.equal(st.gps, "ok", JSON.stringify(st));
  assert.equal(st.flagsTotal, 0);
});

test("honest GPS is never flagged with the phone model", () => {
  const s = cruise(60, { model: "phone", seed: 3 });
  s.accFwd = 0.5; s.step(10); s.accFwd = 0;
  s.turn = 6; s.step(15); s.turn = 0;
  s.step(20);
  assert.equal(s.ins.status().flagsTotal, 0);
});

test("a position jump is flagged", () => {
  const s = cruise();
  s.step(2, { gpsPos: [s.lat + 0.01, s.lon] });
  const st = s.ins.status();
  assert.equal(st.gps, "suspect");
  assert.match(st.reasons[0], /jumped/);
  assert.equal(s.ins.vet({ ...s.fix, time_local: s.t + 0.5 }), false);
});

test("a speed jump nobody felt is flagged", () => {
  const s = cruise();
  s.step(8, { gpsVel: [0, 18] });
  assert.equal(s.ins.status().gps, "suspect");
});

test("a course turn the gyro did not feel is flagged", () => {
  const s = cruise();
  s.step(10, { gpsVel: [5, 0] });
  assert.equal(s.ins.status().gps, "suspect");
});

test("GPS standing still while walking is flagged", () => {
  const s = cruise(5);
  s.speed = 0;
  for (let i = 0; i < 14; i++) { s.step(1, { gpsVel: [0, 0] }); s.steps += 2; }
  assert.equal(s.ins.status().gps, "suspect");
});

function memStore() { const m = {}; return { get: (k) => m[k], set: (k, v) => { m[k] = v; } }; }

test("a suspect GPS is not used by dead reckoning", () => {
  const s = cruise();
  const dr = new DeadReckoner({ getFix: () => s.fix, getHeading: () => null, store: memStore(), ins: s.ins, clock: () => s.t });
  dr.setMode("boat");
  dr.tick(s.t);
  const good = [s.lat, s.lon];
  s.step(3, { gpsPos: [s.lat + 0.05, s.lon + 0.05], gpsVel: [0, 5] });
  dr.tick(s.t + 1);
  near(dr.anchor.lat, good[0], 0.001);
  const e = dr.estimate();
  assert.ok(e);
  assert.ok(Math.abs(e.lat - s.lat) < 0.002);
});

test("trust by hand, and automatic release after honest minutes", () => {
  const s = cruise();
  s.step(2, { gpsPos: [s.lat + 0.01, s.lon] });
  assert.equal(s.ins.status().gps, "suspect");
  s.ins.trustGps(30);
  assert.equal(s.ins.vet({ ...s.fix, time_local: s.t + 0.5 }), true);
  const s2 = cruise();
  s2.step(2, { gpsPos: [s2.lat + 0.01, s2.lon] });
  s2.step(400);
  assert.equal(s2.ins.status().gps, "ok");
});

test("warn-only mode flags but keeps using GPS", () => {
  const s = cruise();
  s.ins.spoofAction = "warn";
  s.step(2, { gpsPos: [s.lat + 0.01, s.lon] });
  assert.equal(s.ins.status().gps, "suspect");
  assert.equal(s.ins.vet({ ...s.fix, time_local: s.t + 0.5 }), true);
});

test("boat course follows a gyro turn after GPS is lost", () => {
  const ins = { h: 0, heading() { return this.h; }, vet() { return true; } };
  let fix = { mode: 3, lat: 50, lon: -10, speed: 3, track: 0 };
  let t = 1000;
  const dr = new DeadReckoner({ getFix: () => fix, getHeading: () => null, store: memStore(), ins, clock: () => t });
  dr.setMode("boat");
  dr.tick(1000);
  fix = { mode: 1 };
  ins.h = 90;
  for (let k = 1; k <= 10; k++) { t = 1000 + k; dr.tick(t); }
  const e = dr.estimate();
  near((e.lat - 50) * 111320, 0, 1);
  near((e.lon + 10) * 111320 * Math.cos(50 * RAD), 30, 1);
});

test("walking without GPS moves one step length per step along the heading", () => {
  let fix = { mode: 3, lat: 52, lon: 5, speed: 0, track: null, hdop: 1 };
  const dr = new DeadReckoner({ getFix: () => fix, getHeading: () => 0, store: memStore(), clock: () => 1 });
  dr.tick(1);
  fix = { mode: 0 };
  dr.tick(2);
  for (let i = 0; i < 100; i++) dr.onStep(2);
  near((dr.estimate().lat - 52) * 111320, 72, 0.5);
});

test("step detector counts steps", () => {
  const sd = new StepDetector();
  let n = 0;
  for (let i = 0; i < 500; i++) { const t = i / 50; if (sd.feed(t, 0, 0, 1 + 0.3 * Math.sin(2 * Math.PI * 2 * t))) n++; }
  near(n, 20, 1);
});

test("wrap180", () => {
  assert.equal(wrap180(190), -170);
  assert.equal(wrap180(-190), 170);
});

test("typed coordinates", () => {
  const d = (s) => parseCoords(s);
  near(d("52.3702, 4.8952").lat, 52.3702, 1e-6);
  near(d("52.3702 -4.8952").lon, -4.8952, 1e-6);
  near(d("52°22'12.7\"N 4°53'42.7\"E").lat, 52.370194, 1e-5);
  near(d("52 22.2 N 004 53.4 E").lon, 4.89, 1e-6);
  near(d("S 33 52.1 W 151 12.5").lat, -33.868333, 1e-5);
  near(d("N52 22.2 E4 53.4").lat, 52.37, 1e-6);
  near(d("52,3702 4,8952").lon, 4.8952, 1e-6);
  assert.equal(d("hello"), null);
  assert.equal(d("95 10"), null);
});

test("car mode: dead reckoning carries on and turns with the gyro, any mount", () => {
  const ins = { h: 37, heading() { return this.h; }, vet() { return true; } };
  let fix = { mode: 3, lat: 52, lon: 5, speed: 20, track: 90 };
  let t = 1000;
  const dr = new DeadReckoner({ getFix: () => fix, getHeading: () => null, store: memStore(), ins, clock: () => t });
  dr.setMode("car");
  dr.tick(t);
  fix = { mode: 0 };
  ins.h = 37 - 90;                             // phone mounted at 37 deg; the car turns 90 deg left
  for (let k = 1; k <= 10; k++) { t = 1000 + k; dr.tick(t); }
  const e = dr.estimate();
  near((e.lat - 52) * 111320, 200, 2);           // heading north now at 20 m/s
  assert.ok(e.err_m > 50 && e.err_m < 120);
});

test("plane mode allows airliner speed but still flags a jump", () => {
  const s = new Sim();
  s.ins.setMaxSpeed(350);
  s.psi = 0; s.speed = 230;                     // cruising at 230 m/s from the start
  s.step(40);
  s.ins.setHeading(0);
  s.step(20);
  assert.equal(s.ins.status().gps, "ok");
  s.step(2, { gpsPos: [s.lat + 0.05, s.lon] });
  assert.equal(s.ins.status().gps, "suspect");
});

test("vehicle alignment tolerates vibration", () => {
  const s = new Sim();
  s.ins.getAlign = () => "vehicle";
  s.ins.realign();
  s.rollAmp = 1.5;
  s.step(60);
  assert.equal(s.ins.status().state, "nav");
});

test("without a course reference the GPS course does not pull the heading", () => {
  const s = new Sim();
  s.ins.courseRef = () => false;
  s.step(40);
  s.compassOn = false;
  s.psi = 0; s.ins.setHeading(30);              // phone mounted 30 deg off the direction of travel
  s.speed = 10;
  s.step(60);
  near(s.ins.heading(), 30, 2);
  assert.equal(s.ins.status().notes.length, 0);
});
