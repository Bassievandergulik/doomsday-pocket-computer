"""Hardware-facing checks with fake chips (no Pi needed).

Run with:  python3 -m unittest discover tests
"""
import os
import sys
import threading
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import sensors  # noqa: E402

try:
    import bme680  # noqa: F401
except ImportError:
    bme680 = None


class RacyBus:
    """Behaves like smbus2.SMBus: choosing the chip (I2C_SLAVE) and the transfer are two
    separate steps, and the last address is cached so the first step is skipped when it
    looks unchanged. Each chip answers its own address, so a misdirected read shows up."""

    def __init__(self):
        self.address = None   # smbus2's cached address
        self.kernel = None    # what the kernel really has selected
        self.wrong = 0

    def _set_address(self, addr):
        if self.address != addr:
            self.kernel = addr
            time.sleep(0.0002)  # let the other thread run between the two steps
            self.address = addr

    def read_byte_data(self, addr, reg):
        self._set_address(addr)
        time.sleep(0.0001)
        got = self.kernel
        if got != addr:
            self.wrong += 1
        return got


class LockedBusTest(unittest.TestCase):
    def _hammer(self, bus):
        def worker(addr):
            for _ in range(300):
                bus.read_byte_data(addr, 0)
        ts = [threading.Thread(target=worker, args=(a,)) for a in (0x69, 0x77, 0x13)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

    def test_threads_without_lock_hit_the_wrong_chip(self):
        raw = RacyBus()
        self._hammer(raw)
        self.assertGreater(raw.wrong, 0, "the fake should show the smbus2 race")

    def test_locked_bus_never_hits_the_wrong_chip(self):
        raw = RacyBus()
        self._hammer(sensors.LockedBus(raw))
        self.assertEqual(raw.wrong, 0)

    def test_locked_bus_passes_attributes_through(self):
        raw = RacyBus()
        bus = sensors.LockedBus(raw)
        self.assertEqual(bus.read_byte_data(0x43, 2), 0x43)


class FakeBme680:
    """Register-level BME680 at 0x77 that takes as long as the real chip to measure:
    about 33 ms for 8x/4x/2x oversampling plus the 150 ms gas heater."""

    ADDR = 0x77
    MEASURE_S = 0.19

    def __init__(self):
        self.regs = [0] * 256
        self.regs[0xD0] = 0x61   # chip id
        self.regs[0xF0] = 0x00   # variant: BME680 (low gas range)
        # plausible factory calibration (values from a real module's dump)
        cal1 = [0x3F, 0x66, 0x03, 0x00, 0x25, 0x8E, 0x56, 0xD7, 0x58, 0x00, 0x21, 0x22, 0xBE, 0xFF,
                0x1E, 0x1E, 0x00, 0x00, 0x2A, 0xF8, 0x3D, 0xF0, 0x1E, 0x00, 0x00]
        cal2 = [0x3E, 0x30, 0x46, 0x2D, 0x00, 0x2D, 0x14, 0x78, 0x9C, 0x5F, 0x66, 0xF3, 0xED, 0xE6, 0x12, 0x00]
        for i, v in enumerate(cal1):
            self.regs[0x8A + i] = v
        for i, v in enumerate(cal2):
            self.regs[0xE1 + i] = v
        self.regs[0x00] = 0x34   # res_heat_val
        self.regs[0x02] = 0x14   # res_heat_range
        self.regs[0x04] = 0x01   # range_sw_err
        self.triggered = None

    def _measuring_done(self):
        # ~35 ms without the gas heater; ~190 ms once a 150 ms heater time is set (gas_wait_0)
        need = self.MEASURE_S if self.regs[0x64] else 0.035
        return self.triggered is not None and time.time() - self.triggered >= need

    def _read(self, reg):
        if reg == 0x74:   # ctrl_meas: the mode bits fall back to sleep once a forced reading is done
            v = self.regs[0x74]
            return v & ~0x03 if self._measuring_done() else v
        if reg == 0x1D:   # meas_status_0
            return 0x80 if self._measuring_done() else 0x00
        if 0x1F <= reg <= 0x2B and self._measuring_done():
            data = {0x1F: 0x50, 0x20: 0x00, 0x21: 0x00, 0x22: 0x7E, 0x23: 0x00, 0x24: 0x00,
                    0x25: 0x6A, 0x26: 0x00, 0x2A: 0x60, 0x2B: 0x30 | 0x05}  # gas valid + heat stable
            return data.get(reg, 0)
        return self.regs[reg]

    def read_byte_data(self, addr, reg):
        if addr != self.ADDR:
            raise OSError(121, "no device")
        return self._read(reg)

    def read_i2c_block_data(self, addr, reg, n):
        if addr != self.ADDR:
            raise OSError(121, "no device")
        return [self._read(reg + i) for i in range(n)]

    def write_byte_data(self, addr, reg, value):
        if addr != self.ADDR:
            raise OSError(121, "no device")
        self.regs[reg] = value
        if reg == 0x74 and value & 0x03 == 0x01:
            self.triggered = time.time()

    def write_i2c_block_data(self, addr, reg, data):
        for i in range(0, len(data)):
            self.write_byte_data(addr, reg + i, data[i])


@unittest.skipIf(bme680 is None, "Pimoroni bme680 package not installed")
class Bme680TimingTest(unittest.TestCase):
    def test_reading_waits_for_the_gas_heater(self):
        s = sensors.BME680(sensors.LockedBus(FakeBme680()))
        self.assertTrue(s.available)
        r = s.read()
        self.assertIsNotNone(r, "a forced reading takes ~190 ms; the driver must wait for it")
        self.assertTrue(-40 < r["temp_c"] < 85, r)
        self.assertTrue(300 < r["pressure_hpa"] < 1100, r)
        self.assertIsNotNone(s.read(), "second reading works as well")


class FakeLgpio(types.ModuleType):
    def __init__(self):
        super().__init__("lgpio")
        self.opened = self.closed = 0
        self.writes = []

    def gpiochip_open(self, chip):
        self.opened += 1
        return 7

    def gpiochip_close(self, h):
        self.closed += 1

    def gpio_claim_output(self, h, pin, level):
        self.writes.append((pin, level))

    def gpio_write(self, h, pin, level):
        self.writes.append((pin, level))


class Si4732ResetTest(unittest.TestCase):
    def test_reset_pin_stays_driven(self):
        import radio_si4732 as si
        fake = FakeLgpio()
        old = sys.modules.get("lgpio")
        sys.modules["lgpio"] = fake
        try:
            r = si.Si4732.__new__(si.Si4732)
            r.reset_gpio = 23
            r._reset()
            r._reset()  # again, as before loading the SSB patch
        finally:
            if old is None:
                del sys.modules["lgpio"]
            else:
                sys.modules["lgpio"] = old
        self.assertEqual(fake.opened, 1, "one GPIO handle for the life of the app")
        self.assertEqual(fake.closed, 0, "closing it would let RST float")
        self.assertEqual(fake.writes[-1], (23, 1), "RST ends high (radio running)")


if __name__ == "__main__":
    unittest.main()
