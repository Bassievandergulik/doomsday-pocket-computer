"""Inertial navigation: alignment, gyro-stabilised heading, GPS spoof checks, IMU drivers.
Everything runs on simulated sensors and a simulated clock; nothing here has seen a real chip."""
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import deadreck  # noqa: E402
import ins as insmod  # noqa: E402


class FakeIMU:
    available = True
    model = "ICM-42688-P"


class Sim:
    """A device on a boat or table. Time is simulated; INS.clock reads it."""

    def __init__(self, seed=1, sea=False, bias=(0.3, -0.2, 0.5), gps=True, vehicle=False):
        random.seed(seed)
        self.t = 1000.0
        self.bias = bias
        self.fix = {"mode": 0}
        self.steps = 0
        self.ins = insmod.INS(FakeIMU(), lambda: None, lambda: self.fix, ({}.get, {}.__setitem__),
                              get_sea=lambda: sea or vehicle, get_steps=lambda: self.steps,
                              get_vehicle=lambda: vehicle)
        self.ins.clock = lambda: self.t
        self.psi = 90.0          # true heading of the device, deg clockwise
        self.crab = 0.0          # travel direction minus device heading (device on a car seat at an angle)
        self.lat, self.lon = 50.0, -10.0
        self.speed = 0.0         # m/s along the heading (the boat goes where it points)
        self.acc_fwd = 0.0       # m/s2 along the heading
        self.v = (0.0, 0.0)      # east, north m/s
        self.acc = (0.0, 0.0)
        self.turn = 0.0          # deg/s clockwise
        self.roll_amp = 0.0
        self.compass_on = True
        self.compass_err = 0.0

    def step(self, seconds, gps_every=1.0, gps=True, gps_pos=None, gps_vel=None, gps_track=None):
        """gps_*: what a spoofer reports instead of the truth."""
        n = int(seconds * 50)
        for k in range(n):
            self.t += 0.02
            self.psi = (self.psi + self.turn * 0.02) % 360
            self.speed += self.acc_fwd * 0.02
            trav = math.radians(self.psi + self.crab)
            v = (self.speed * math.sin(trav), self.speed * math.cos(trav))
            self.acc = ((v[0] - self.v[0]) / 0.02, (v[1] - self.v[1]) / 0.02)   # includes the centripetal push
            self.v = v
            self.lat += self.v[1] * 0.02 / 111320.0
            self.lon += self.v[0] * 0.02 / (111320.0 * math.cos(math.radians(self.lat)))
            phi = self.roll_amp * math.sin(2 * math.pi * 0.15 * self.t)
            dphi = self.roll_amp * 2 * math.pi * 0.15 * math.cos(2 * math.pi * 0.15 * self.t)
            up = (0.0, math.sin(math.radians(phi)), math.cos(math.radians(phi)))
            # body acceleration: gravity direction + horizontal acceleration rotated into device axes
            s, c = math.sin(math.radians(self.psi)), math.cos(math.radians(self.psi))
            af = (self.acc[0] * s + self.acc[1] * c) / insmod.G     # along heading
            al = (-self.acc[0] * c + self.acc[1] * s) / insmod.G    # to the left
            a = [af + random.gauss(0, 0.01), al + up[1] + random.gauss(0, 0.01), up[2] + random.gauss(0, 0.01)]
            g = [self.bias[0] + dphi + random.gauss(0, 0.05), self.bias[1] - self.turn * up[1] + random.gauss(0, 0.05),
                 self.bias[2] - self.turn * up[2] + random.gauss(0, 0.05)]
            self.ins.feed(self.t, a, g)
            if k % 10 == 0 and self.compass_on:
                self.ins.feed_compass(self.t, (self.psi + self.compass_err + random.gauss(0, 4)) % 360)
            if k % int(50 * gps_every) == 0 and gps:
                self.send_fix(gps_pos, gps_vel, gps_track)

    def send_fix(self, pos=None, vel=None, track=None):
        lat, lon = pos or (self.lat, self.lon)
        ve, vn = vel or self.v
        speed = math.hypot(ve, vn)
        trk = track if track is not None else (math.degrees(math.atan2(ve, vn)) % 360 if speed > 0.3 else None)
        self.fix = {"mode": 3, "lat": lat, "lon": lon, "speed": speed, "track": trk, "hdop": 1.0,
                    "time_local": self.t}
        return self.ins.vet(self.fix)


class AlignmentTest(unittest.TestCase):
    def test_align_then_hold_heading(self):
        s = Sim()
        s.step(10)
        st = s.ins.status()
        self.assertEqual(st["state"], "align")
        self.assertIsNone(s.ins.heading())
        s.step(30)
        st = s.ins.status()
        self.assertEqual(st["state"], "nav")
        self.assertAlmostEqual(st["heading"], 90, delta=3)
        self.assertAlmostEqual(st["gyro_bias_dps"][2], 0.5, delta=0.03)   # zero offset measured at rest
        s.compass_on = False
        s.step(120)                                    # two minutes with no compass at all
        self.assertAlmostEqual(s.ins.heading(), 90, delta=1.5)
        s.turn = 10.0
        s.step(9)                                      # a 90 degree right turn is felt by the gyro
        s.turn = 0.0
        self.assertAlmostEqual(s.ins.heading(), 180, delta=2)

    def test_motion_restarts_land_alignment(self):
        s = Sim()
        s.step(20)
        s.turn = 40.0
        s.step(3)
        s.turn = 0.0
        self.assertEqual(s.ins.status()["state"], "align")
        self.assertLess(s.ins.status()["align_pct"], 10)

    def test_sea_alignment_tolerates_rocking(self):
        s = Sim(sea=True)
        s.roll_amp = 8.0
        s.step(70)
        self.assertEqual(s.ins.status()["state"], "nav")
        self.assertAlmostEqual(s.ins.heading(), 90, delta=4)

    def test_rolling_boat_and_magnet(self):
        s = Sim()
        s.step(160)                                    # settled for a couple of minutes
        s.roll_amp = 12.0
        s.compass_err = 25.0                          # a magnet or iron nearby: compass off by 25 degrees
        s.step(60)
        self.assertAlmostEqual(s.ins.heading(), 90, delta=6)   # the gyro keeps the heading, compass barely tugs

    def test_tilted_device_turn(self):
        s = Sim()
        s.step(40)
        s.compass_on = False
        s.roll_amp = 40.0                              # heavy heel: vertical axis is not the device z axis
        s.turn = 10.0
        s.step(9)
        self.assertAlmostEqual(s.ins.heading(), 180, delta=4)

    def test_set_heading_by_hand(self):
        s = Sim()
        s.step(40)
        s.ins.set_heading(200)
        self.assertAlmostEqual(s.ins.heading(), 200, delta=0.1)


class SpoofTest(unittest.TestCase):
    def cruise(self, seconds=30, sea=False):
        s = Sim(sea=sea)
        s.step(40)
        s.psi = 0.0
        s.ins.set_heading(0.0)
        s.speed = 5.0
        s.step(seconds)
        return s

    def test_honest_gps_is_never_flagged(self):
        s = self.cruise(60)
        s.acc_fwd = 0.5           # speeds up 0.5 m/s2 for 10 s: the accelerometer feels it
        s.step(10)
        s.acc_fwd = 0.0
        s.turn = 6.0
        s.step(15)                # then a right turn
        s.turn = 0.0
        s.step(20)
        st = s.ins.status()
        self.assertEqual(st["gps"], "ok", st)
        self.assertEqual(st["flags_total"], 0)

    def test_position_jump_is_flagged(self):
        s = self.cruise()
        s.step(2, gps_pos=(s.lat + 0.01, s.lon))      # 1.1 km north in a second
        st = s.ins.status()
        self.assertEqual(st["gps"], "suspect")
        self.assertIn("jumped", st["reasons"][0])
        self.assertFalse(s.ins.gps_trusted())

    def test_speed_jump_without_push_is_flagged(self):
        s = self.cruise()
        s.step(8, gps_vel=(0.0, 18.0))                # GPS says 18 m/s, but nothing pushed the device
        self.assertEqual(s.ins.status()["gps"], "suspect")

    def test_course_turn_without_gyro_is_flagged(self):
        s = self.cruise()
        s.step(10, gps_vel=(5.0, 0.0))                # GPS says we now go east; the gyro felt no turn
        st = s.ins.status()
        self.assertEqual(st["gps"], "suspect")

    def test_standing_still_but_walking(self):
        s = self.cruise(5)
        s.speed = 0.0
        for _ in range(14):
            s.step(1.0, gps_vel=(0.0, 0.0))
            s.steps += 2
        self.assertEqual(s.ins.status()["gps"], "suspect")

    def test_suspect_gps_is_not_used_by_dead_reckoning(self):
        s = self.cruise()
        dr_state = {}
        dr = deadreck.DeadReckoner(None, lambda: s.fix, lambda: None, lambda: None,
                                   (dr_state.get, dr_state.__setitem__), ins=s.ins)
        dr.set_mode("boat")
        dr.tick(s.t)
        good = (s.lat, s.lon)
        s.step(3, gps_pos=(s.lat + 0.05, s.lon + 0.05), gps_vel=(0, 5))
        dr.tick(s.t + 1)
        self.assertAlmostEqual(dr.anchor["lat"], good[0], delta=0.001)    # the fake position never became the anchor
        e = dr.estimate()
        self.assertIsNotNone(e)
        self.assertLess(abs(e["lat"] - s.lat), 0.002)

    def test_trust_by_hand_and_auto_release(self):
        s = self.cruise()
        s.step(2, gps_pos=(s.lat + 0.01, s.lon))
        self.assertEqual(s.ins.status()["gps"], "suspect")
        s.ins.trust_gps(30)
        self.assertTrue(s.ins.gps_trusted())
        s2 = self.cruise()
        s2.step(2, gps_pos=(s2.lat + 0.01, s2.lon))
        s2.step(400)                                    # honest again for 5+ minutes
        self.assertEqual(s2.ins.status()["gps"], "ok")

    def test_warn_only_mode(self):
        s = self.cruise()
        s.ins.spoof_action = "warn"
        s.step(2, gps_pos=(s.lat + 0.01, s.lon))
        self.assertEqual(s.ins.status()["gps"], "suspect")
        self.assertTrue(s.ins.gps_trusted())             # flagged on screen, but still used


class VehicleTest(unittest.TestCase):
    def test_airliner_is_not_a_jump(self):
        s = Sim(vehicle=True)
        s.step(70)
        self.assertEqual(s.ins.status()["state"], "nav")
        s.acc_fwd = 3.0                                # take-off run and climb, up to ~830 km/h
        s.step(76.6)
        s.acc_fwd = 0.0
        s.step(60)
        s.turn = 3.0                                   # standard-rate turn
        s.step(30)
        s.turn = 0.0
        s.step(30)
        st = s.ins.status()
        self.assertEqual(st["gps"], "ok", st)
        self.assertEqual(st["flags_total"], 0)

    def test_device_at_an_angle_in_a_car(self):
        s = Sim(vehicle=True)
        s.step(70)
        s.crab = 50.0                                  # phone-holder or seat: device points 50 deg off the road
        s.speed = 25.0
        s.step(60)
        s.turn = 9.0
        s.step(10)                                     # 90 degree corner
        s.turn = 0.0
        s.step(60)
        st = s.ins.status()
        self.assertEqual(st["gps"], "ok", st)
        self.assertAlmostEqual(s.ins.heading(), s.psi, delta=3)   # GPS course did not drag the heading

    def test_car_still_catches_a_jump(self):
        s = Sim(vehicle=True)
        s.step(70)
        s.speed = 25.0
        s.step(20)
        s.step(2, gps_pos=(s.lat + 0.05, s.lon))      # 5.5 km in a second is too fast even for a plane
        self.assertEqual(s.ins.status()["gps"], "suspect")

    def test_vehicle_dead_reckoning(self):
        fix = [{"mode": 3, "lat": 52.0, "lon": 5.0, "speed": 25.0, "track": 0.0}]
        st = {}
        dr = deadreck.DeadReckoner(None, lambda: fix[0], lambda: None, lambda: None, (st.get, st.__setitem__))
        dr.set_mode("vehicle")
        dr.tick(1000.0)
        fix[0] = {"mode": 1}
        for k in range(1, 11):
            dr.tick(1000.0 + k)
        e = dr.estimate()
        self.assertAlmostEqual((e["lat"] - 52.0) * 111320, 250, delta=1)
        self.assertEqual(e["mode"], "vehicle")
        self.assertEqual(e["err_m"], round(50 + 0.2 * 250))


class TurnTrackingTest(unittest.TestCase):
    def test_boat_course_follows_gyro_turn(self):
        class StubIns:
            h = 0.0

            def heading(self):
                return self.h

            def gps_trusted(self, f=None):
                return True
        ins = StubIns()
        fix = [{"mode": 3, "lat": 50.0, "lon": -10.0, "speed": 3.0, "track": 0.0}]
        st = {}
        dr = deadreck.DeadReckoner(None, lambda: fix[0], lambda: None, lambda: None, (st.get, st.__setitem__), ins=ins)
        dr.set_mode("boat")
        dr.tick(1000.0)
        fix[0] = {"mode": 1}
        ins.h = 90.0                                  # the gyro felt a 90 degree right turn after GPS was lost
        for k in range(1, 11):
            dr.tick(1000.0 + k)
        e = dr.estimate()
        self.assertAlmostEqual((e["lat"] - 50.0) * 111320, 0, delta=1)       # no longer going north
        self.assertAlmostEqual((e["lon"] + 10.0) * 111320 * math.cos(math.radians(50)), 30, delta=1)   # but east


class ImuDriverTest(unittest.TestCase):
    class Bus:
        def __init__(self, who, block):
            self.who, self.block, self.writes = who, block, []

        def read_byte_data(self, a, r):
            if a == 0x69 and r == 0x75:
                return self.who
            raise OSError

        def write_byte_data(self, a, r, v):
            self.writes.append((r, v))

        def read_i2c_block_data(self, a, r, n):
            self.last = (r, n)
            return self.block[:n]

    def test_icm42688(self):
        # accel z = +1 g (8192 at +-4 g), gyro z = +10 dps (328 at 32.8 LSB/dps), big endian
        blk = [0, 0, 0, 0, 0x20, 0x00, 0, 0, 0, 0, 0x01, 0x48]
        bus = self.Bus(0x47, blk)
        imu = deadreck.IMU(bus)
        self.assertTrue(imu.available)
        self.assertEqual(imu.model, "ICM-42688-P")
        self.assertIn((0x4E, 0x0F), bus.writes)
        a, g = imu.read6()
        self.assertEqual(bus.last, (0x1F, 12))
        self.assertAlmostEqual(a[2], 1.0, places=3)
        self.assertAlmostEqual(g[2], 10.0, delta=0.05)
        self.assertAlmostEqual(imu.accel()[2], 1.0, places=3)

    def test_mpu6050_gyro(self):
        blk = [0, 0, 0, 0, 0x40, 0, 0, 0] + [0, 0, 0, 0, 0xFE, 0xB8]      # gyro z = -328 -> -10 dps
        bus = self.Bus(0x68, blk)
        imu = deadreck.IMU(bus)
        self.assertEqual(imu.model, "MPU-6050")
        self.assertIn((0x1B, 0x10), bus.writes)
        a, g = imu.read6()
        self.assertEqual(bus.last, (0x3B, 14))
        self.assertAlmostEqual(a[2], 1.0, places=3)
        self.assertAlmostEqual(g[2], -10.0, delta=0.05)

    def test_mount_remap(self):
        i = insmod.INS(FakeIMU(), lambda: None, lambda: {}, ({}.get, {}.__setitem__), mount=("y", "-x", "z"))
        self.assertEqual(i._remap((1.0, 2.0, 3.0)), (2.0, -1.0, 3.0))


if __name__ == "__main__":
    unittest.main()
