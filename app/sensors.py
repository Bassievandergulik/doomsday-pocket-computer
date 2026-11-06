"""I2C sensors: BME280 weather sensor and an optional BMM150, QMC5883L or HMC5883L compass.

Everything here degrades gracefully: if smbus2 or the chip is missing the
sensor reports `available = False` and the rest of the app keeps working.
"""
import math
import struct
import time

try:
    from smbus2 import SMBus
except ImportError:  # not on a Pi, or smbus2 not installed
    SMBus = None


def open_bus(bus=1):
    if SMBus is None:
        return None
    try:
        return SMBus(bus)
    except OSError:
        return None


class BME680:
    """Bosch BME680: temperature, pressure, humidity and gas resistance (air quality).

    Uses Pimoroni's `bme680` package (pip install bme680), which already does Bosch's
    compensation maths. Address 0x76 or 0x77 (depends on the board's SDO pin).
    Gas resistance is the air-quality signal: it drops when smoke, fumes or many
    volatile organics are present, after a 5-minute warm-up. Untested on hardware.
    """

    def __init__(self, bus, addresses=(0x76, 0x77)):
        self.available = False
        self.gas_baseline = None
        self.last = None
        self.dev = None
        self.error = None
        try:
            import bme680 as lib
        except ImportError:
            self.error = "bme680 package not installed (pip install bme680)"
            return
        if bus is None:
            return
        for a in addresses:
            try:
                self.dev = lib.BME680(i2c_addr=a, i2c_device=bus)
                break
            except (OSError, RuntimeError, IOError):
                self.dev = None
        if self.dev is None:
            return
        d = self.dev
        d.set_humidity_oversample(lib.OS_2X)
        d.set_pressure_oversample(lib.OS_4X)
        d.set_temperature_oversample(lib.OS_8X)
        d.set_filter(lib.FILTER_SIZE_3)
        d.set_gas_status(lib.ENABLE_GAS_MEAS)
        d.set_gas_heater_temperature(320)
        d.set_gas_heater_duration(150)
        d.select_gas_heater_profile(0)
        self.lib = lib
        self.started = time.time()
        self.available = True

    def read(self):
        """dict(temp_c, pressure_hpa, humidity, gas_ohm, air_quality 0-100 or None) or None."""
        if not self.available:
            return None
        if not self.dev.get_sensor_data():
            return None
        d = self.dev.data
        out = {"temp_c": round(d.temperature, 2), "pressure_hpa": round(d.pressure, 2),
               "humidity": round(d.humidity, 1), "gas_ohm": None, "air_quality": None}
        if d.heat_stable:
            g = d.gas_resistance
            out["gas_ohm"] = int(g)
            # baseline = the highest resistance seen in clean air (learned while it warms up)
            if time.time() - self.started > 300:
                self.gas_baseline = max(self.gas_baseline or 0, g)
                out["air_quality"] = round(max(0.0, min(100.0, 100.0 * g / self.gas_baseline)), 0) \
                    if self.gas_baseline else None
        self.last = out
        return out


class UVSensor:
    """LTR390 UV index sensor (I2C 0x53). The index is approximate: calibrated for
    the common gain setting, not against a reference meter. Untested on hardware."""

    ADDR = 0x53

    def __init__(self, bus):
        self.bus = bus
        self.available = False
        if bus is None:
            return
        try:
            if bus.read_byte_data(self.ADDR, 0x06) != 0xB2:  # part ID
                return
            bus.write_byte_data(self.ADDR, 0x00, 0x0A)  # UVS mode, enabled
            bus.write_byte_data(self.ADDR, 0x05, 0x03)  # gain x18
            bus.write_byte_data(self.ADDR, 0x04, 0x20)  # 18-bit, 100 ms
            self.available = True
        except OSError:
            pass

    def index(self):
        """UV index (0 at night), or None."""
        if not self.available:
            return None
        d = self.bus.read_i2c_block_data(self.ADDR, 0x10, 3)
        raw = d[0] | (d[1] << 8) | (d[2] << 16)
        return round(raw / 2300.0, 1)  # approximate counts per UV index unit at x18 gain


class BME280:
    """Bosch BME280 temperature / humidity / pressure sensor (address 0x76 or 0x77)."""

    def __init__(self, bus, addresses=(0x76, 0x77)):
        self.bus = bus
        self.addr = None
        self.available = False
        if bus is None:
            return
        for a in addresses:
            try:
                if bus.read_byte_data(a, 0xD0) in (0x60, 0x58):  # 0x58 = BMP280 (no humidity)
                    self.addr = a
                    break
            except OSError:
                continue
        if self.addr is None:
            return
        self.chip = bus.read_byte_data(self.addr, 0xD0)
        self._load_calibration()
        # humidity x1, temp x1, pressure x1, forced mode is triggered per read
        if self.chip == 0x60:
            bus.write_byte_data(self.addr, 0xF2, 0x01)
        bus.write_byte_data(self.addr, 0xF5, 0x00)
        self.available = True

    def _load_calibration(self):
        c = bytes(self.bus.read_i2c_block_data(self.addr, 0x88, 24))
        (self.T1, self.T2, self.T3, self.P1, self.P2, self.P3, self.P4, self.P5,
         self.P6, self.P7, self.P8, self.P9) = struct.unpack("<HhhHhhhhhhhh", c)
        if self.chip != 0x60:
            return
        self.H1 = self.bus.read_byte_data(self.addr, 0xA1)
        h = bytes(self.bus.read_i2c_block_data(self.addr, 0xE1, 7))
        self.H2 = struct.unpack("<h", h[0:2])[0]
        self.H3 = h[2]
        self.H4 = (struct.unpack("b", h[3:4])[0] << 4) | (h[4] & 0x0F)
        self.H5 = (struct.unpack("b", h[5:6])[0] << 4) | (h[4] >> 4)
        self.H6 = struct.unpack("b", h[6:7])[0]

    def read(self):
        """Returns dict(temp_c, pressure_hpa, humidity) or None."""
        if not self.available:
            return None
        b = self.bus
        b.write_byte_data(self.addr, 0xF4, (1 << 5) | (1 << 2) | 0x01)  # forced mode
        for _ in range(20):
            time.sleep(0.01)
            if not b.read_byte_data(self.addr, 0xF3) & 0x08:
                break
        d = b.read_i2c_block_data(self.addr, 0xF7, 8)
        adc_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
        adc_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
        adc_h = (d[6] << 8) | d[7]

        v1 = (adc_t / 16384.0 - self.T1 / 1024.0) * self.T2
        v2 = ((adc_t / 131072.0 - self.T1 / 8192.0) ** 2) * self.T3
        t_fine = v1 + v2
        temp = t_fine / 5120.0

        v1 = t_fine / 2.0 - 64000.0
        v2 = v1 * v1 * self.P6 / 32768.0 + v1 * self.P5 * 2.0
        v2 = v2 / 4.0 + self.P4 * 65536.0
        v1 = (self.P3 * v1 * v1 / 524288.0 + self.P2 * v1) / 524288.0
        v1 = (1.0 + v1 / 32768.0) * self.P1
        pressure = None
        if v1:
            p = 1048576.0 - adc_p
            p = (p - v2 / 4096.0) * 6250.0 / v1
            v1 = self.P9 * p * p / 2147483648.0
            v2 = p * self.P8 / 32768.0
            pressure = (p + (v1 + v2 + self.P7) / 16.0) / 100.0

        hum = None
        if self.chip == 0x60:
            h = t_fine - 76800.0
            h = (adc_h - (self.H4 * 64.0 + self.H5 / 16384.0 * h)) * (
                self.H2 / 65536.0 * (1.0 + self.H6 / 67108864.0 * h * (1.0 + self.H3 / 67108864.0 * h)))
            h = h * (1.0 - self.H1 * h / 524288.0)
            hum = max(0.0, min(100.0, h))
        return {"temp_c": round(temp, 2), "pressure_hpa": round(pressure, 2) if pressure else None,
                "humidity": round(hum, 1) if hum is not None else None}


class BMM150:
    """Bosch BMM150 magnetometer (e.g. DFRobot Fermion board, I2C 0x13 by default).

    The raw readings are only usable after Bosch's temperature/hall compensation,
    which needs the factory trim values stored in the chip (registers 0x5D-0x71).
    compensate_xy() is Bosch's floating-point formula from the BMM150 API.
    """
    ADDRESSES = (0x13, 0x12, 0x11, 0x10)
    CHIP_ID = 0x32
    OVERFLOW_XY = -4096

    def __init__(self, bus, addr):
        self.bus, self.addr = bus, addr
        bus.write_byte_data(addr, 0x4B, 0x01)       # power control on (leaves suspend mode)
        time.sleep(0.005)
        if bus.read_byte_data(addr, 0x40) != self.CHIP_ID:
            raise OSError("no BMM150 at 0x%02X" % addr)
        bus.write_byte_data(addr, 0x4C, 0x00)       # normal mode, 10 Hz
        bus.write_byte_data(addr, 0x51, 0x04)       # XY repetitions 9 ("regular" preset)
        bus.write_byte_data(addr, 0x52, 0x0E)       # Z repetitions 15
        self._read_trim()

    @classmethod
    def probe(cls, bus):
        for addr in cls.ADDRESSES:
            try:
                return cls(bus, addr)
            except OSError:
                continue
        return None

    def _read_trim(self):
        r = lambda reg, n: bytes(self.bus.read_i2c_block_data(self.addr, reg, n))
        self.dig_x1, self.dig_y1 = struct.unpack("<bb", r(0x5D, 2))
        self.dig_x2, self.dig_y2 = struct.unpack("<bb", r(0x64, 2))
        xyz1 = struct.unpack("<H", r(0x6C, 2))[0]
        self.dig_xyz1 = xyz1 & 0x7FFF
        self.dig_xy2, self.dig_xy1 = struct.unpack("<bB", r(0x70, 2))

    @staticmethod
    def parse(d):
        """8 data bytes from 0x42 -> (x, y, z, rhall) raw ADC values."""
        x = struct.unpack("<h", d[0:2])[0] >> 3   # 13-bit signed
        y = struct.unpack("<h", d[2:4])[0] >> 3
        z = struct.unpack("<h", d[4:6])[0] >> 1   # 15-bit signed
        rhall = struct.unpack("<H", d[6:8])[0] >> 2  # 14-bit unsigned
        return x, y, z, rhall

    def _comp(self, raw, rhall, d1, d2):
        if raw == self.OVERFLOW_XY:
            return None
        x0 = rhall or self.dig_xyz1
        if not x0:
            return None
        r = self.dig_xyz1 * 16384.0 / x0 - 16384.0
        a = self.dig_xy2 * (r * r / 268435456.0) + r * self.dig_xy1 / 16384.0
        v = raw * (a + 256.0) * (d2 + 160.0)
        return (v / 8192.0 + d1 * 8.0) / 16.0  # microtesla

    def compensate_xy(self, x, y, rhall):
        return self._comp(x, rhall, self.dig_x1, self.dig_x2), self._comp(y, rhall, self.dig_y1, self.dig_y2)

    def read_xy(self):
        x, y, _z, rhall = self.parse(bytes(self.bus.read_i2c_block_data(self.addr, 0x42, 8)))
        return self.compensate_xy(x, y, rhall)


class Compass:
    """BMM150 (0x10-0x13), QMC5883L (0x0D) or HMC5883L (0x1E) magnetometer. Hold the device flat.

    Calibrate by calling start_calibration(), turning the device through a few
    full circles, then finish_calibration(). Offsets are returned so they can be saved.
    """

    def __init__(self, bus, calibration=None, declination=0.0):
        self.bus = bus
        self.kind = None
        self.available = False
        self.declination = declination
        self.cal = calibration or {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}
        self._calibrating = None
        self._last = None
        if bus is None:
            return
        try:
            self.bmm = BMM150.probe(bus)
        except OSError:
            self.bmm = None
        if self.bmm is not None:
            self.kind, self.addr = "bmm150", self.bmm.addr
        try:
            if self.kind is None and bus.read_byte_data(0x0D, 0x0D) == 0xFF:
                self.kind, self.addr = "qmc", 0x0D
                bus.write_byte_data(0x0D, 0x0B, 0x01)
                bus.write_byte_data(0x0D, 0x09, 0x1D)  # continuous, 200Hz, 8G, OSR 512
        except OSError:
            pass
        if self.kind is None:
            try:
                if bus.read_byte_data(0x1E, 0x0A) == 0x48:
                    self.kind, self.addr = "hmc", 0x1E
                    bus.write_byte_data(0x1E, 0x00, 0x70)
                    bus.write_byte_data(0x1E, 0x01, 0x20)
                    bus.write_byte_data(0x1E, 0x02, 0x00)
            except OSError:
                pass
        self.available = self.kind is not None

    def raw(self):
        if self.kind == "bmm150":
            x, y = self.bmm.read_xy()
            if x is None or y is None:  # overflow (strong magnet nearby): keep the last good reading
                if self._last is None:
                    raise OSError("BMM150 overflow")
                return self._last
            self._last = (x, y)
            return x, y
        if self.kind == "qmc":
            d = bytes(self.bus.read_i2c_block_data(self.addr, 0x00, 6))
            x, y, _z = struct.unpack("<hhh", d)
        else:
            d = bytes(self.bus.read_i2c_block_data(self.addr, 0x03, 6))
            x, _z, y = struct.unpack(">hhh", d)
        return x, y

    def heading(self):
        """Degrees from true north (magnetic + declination), or None."""
        if not self.available:
            return None
        x, y = self.raw()
        if self._calibrating is not None:
            c = self._calibrating
            c["xmin"], c["xmax"] = min(c["xmin"], x), max(c["xmax"], x)
            c["ymin"], c["ymax"] = min(c["ymin"], y), max(c["ymax"], y)
        c = self.cal
        sx = (c["xmax"] - c["xmin"]) / 2 or 1
        sy = (c["ymax"] - c["ymin"]) / 2 or 1
        xn = (x - (c["xmax"] + c["xmin"]) / 2) / sx
        yn = (y - (c["ymax"] + c["ymin"]) / 2) / sy
        h = math.degrees(math.atan2(yn, xn))
        return round((h + self.declination + 360) % 360, 1)

    def start_calibration(self):
        self._calibrating = {"xmin": 1e9, "xmax": -1e9, "ymin": 1e9, "ymax": -1e9}

    def finish_calibration(self):
        if self._calibrating and self._calibrating["xmax"] > self._calibrating["xmin"]:
            self.cal = self._calibrating
        self._calibrating = None
        return self.cal


class Battery:
    """INA219 battery monitor, as on the Waveshare UPS HAT (C) for the Pi Zero (address 0x43).

    Only the battery voltage is used: percentage is a rough single-cell Li-ion
    curve, and the device shuts down cleanly when the cell is nearly empty, so
    the SD card is never cut off mid-write.
    """
    CURVE = [(3.30, 0), (3.50, 5), (3.60, 12), (3.70, 30), (3.75, 42), (3.80, 52), (3.85, 62),
             (3.90, 70), (4.00, 82), (4.10, 93), (4.20, 100)]

    def __init__(self, bus, address=0x43):
        self.bus = bus
        self.addr = address
        self.available = False
        if bus is None:
            return
        try:
            bus.read_word_data(address, 0x02)
            self.available = True
        except OSError:
            pass

    def voltage(self):
        raw = self.bus.read_word_data(self.addr, 0x02)
        raw = ((raw & 0xFF) << 8) | (raw >> 8)  # INA219 registers are big-endian
        return (raw >> 3) * 0.004

    @classmethod
    def percent(cls, v):
        if v <= cls.CURVE[0][0]:
            return 0
        for (v0, p0), (v1, p1) in zip(cls.CURVE, cls.CURVE[1:]):
            if v <= v1:
                return round(p0 + (p1 - p0) * (v - v0) / (v1 - v0))
        return 100
