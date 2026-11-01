"""RDA5807M FM receiver (87-108 MHz, RDS) over I2C.

Uses the chip's random-access I2C address 0x11 (16-bit registers, MSB first).
Audio comes from the chip's LOUT/ROUT pins into a small amplifier and speaker,
or straight into headphones; the Pi does no audio work.

Wiring (Raspberry Pi): SDA -> GPIO2, SCL -> GPIO3, VCC 3.3 V, GND.
Antenna: ~75 cm wire on the ANT pin (or the headphone cable via a small cap).
"""
import threading
import time

ADDR = 0x11

# register 0x02 bits
DHIZ, DMUTE, MONO, BASS = 1 << 15, 1 << 14, 1 << 13, 1 << 12
SEEKUP, SEEK, SKMODE = 1 << 9, 1 << 8, 1 << 7
RDS_EN, NEW_METHOD, SOFT_RESET, ENABLE = 1 << 3, 1 << 2, 1 << 1, 1 << 0
# register 0x03
TUNE = 1 << 4
# register 0x04
DE_50US, SOFTMUTE_EN = 1 << 11, 1 << 9
# register 0x0A (status)
RDSR, STC, SF, ST = 1 << 15, 1 << 14, 1 << 13, 1 << 10

# band name -> (mode, low, high, step, default), FM in 10 kHz units like the other drivers
BANDS = {"FM": ("fm", 8700, 10800, 10, 9800)}
BAND_BOTTOM = 8700  # BAND bits 00 = 87-108 MHz, channel 0 = 87.0 MHz, 100 kHz spacing


class RDA5807M:
    bands = BANDS
    volume_max = 15

    def __init__(self, bus, address=ADDR):
        self.bus = bus
        self.addr = address
        self.band = "FM"
        self.mode = "fm"
        self.freq = None
        self.volume = 8
        self.muted = False
        self.rds_ps = [" "] * 8
        self.lock = threading.Lock()
        self.available = False
        self.error = None
        if bus is None:
            self.error = "smbus2 / I2C not available"
            return
        try:
            chip = self._read(0x00)
            if chip >> 8 != 0x58:
                self.error = "chip at 0x%02x is not an RDA5807M (id 0x%04x)" % (address, chip)
                return
            self._write(0x02, SOFT_RESET | ENABLE)
            time.sleep(0.05)
            self._write(0x02, self._reg2())
            time.sleep(0.6)  # oscillator start-up
            self._write(0x04, DE_50US | SOFTMUTE_EN)  # 50 us de-emphasis (Europe)
            self._write_volume()
            self.available = True
            self.tune(BANDS["FM"][4])
        except OSError as e:
            self.error = "RDA5807M not found on I2C (%s)" % e

    # --- low level -------------------------------------------------------
    def _read(self, reg):
        hi, lo = self.bus.read_i2c_block_data(self.addr, reg, 2)
        return (hi << 8) | lo

    def _write(self, reg, value):
        self.bus.write_i2c_block_data(self.addr, reg, [(value >> 8) & 0xFF, value & 0xFF])

    def _reg2(self, extra=0):
        return DHIZ | (0 if self.muted else DMUTE) | RDS_EN | NEW_METHOD | ENABLE | extra

    def _write_volume(self):
        # INT_MODE=1, seek threshold 8, LNA input port 2 (LNAP), volume 0-15
        self._write(0x05, 0x8880 | (self.volume & 0x0F))

    def _wait_stc(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._read(0x0A) & STC:
                return True
            time.sleep(0.02)
        return False

    def _chan_to_freq(self, chan):
        return BAND_BOTTOM + chan * 10

    # --- public API (same as the Si4732 driver) ---------------------------
    def set_band(self, band):
        if band not in BANDS:
            raise ValueError("RDA5807M only receives FM")
        self.band = band
        return self.status()

    def tune(self, freq):
        _, lo, hi, step, _ = BANDS["FM"]
        freq = max(lo, min(hi, int(freq)))
        chan = (freq - BAND_BOTTOM) // step
        with self.lock:
            self._write(0x03, (chan << 6) | TUNE)  # band 00, 100 kHz spacing
            self._wait_stc(1.0)
            self.rds_ps = [" "] * 8
        return self.status()

    def step(self, direction):
        _, _, _, step, default = BANDS["FM"]
        return self.tune((self.freq or default) + step * direction)

    def seek(self, up=True):
        with self.lock:
            self._write(0x02, self._reg2(SEEK | (SEEKUP if up else 0)))  # SKMODE 0 = wrap at band edge
            self._wait_stc(10.0)
            self._write(0x02, self._reg2())  # clear SEEK
            self.rds_ps = [" "] * 8
        return self.status()

    def set_volume(self, v):
        self.volume = max(0, min(self.volume_max, int(v)))
        with self.lock:
            self._write_volume()
        return self.volume

    def mute(self, on):
        self.muted = bool(on)
        with self.lock:
            self._write(0x02, self._reg2())

    def _poll_rds(self, status):
        if not status & RDSR:
            return
        block_b = self._read(0x0D)
        block_d = self._read(0x0F)
        if (block_b >> 12) == 0:  # group 0A/0B carries the station name (PS)
            seg = block_b & 0x03
            for i, ch in enumerate((block_d >> 8, block_d & 0xFF)):
                if 32 <= ch < 127:
                    self.rds_ps[seg * 2 + i] = chr(ch)

    def status(self):
        if not self.available:
            return {"available": False, "error": self.error}
        with self.lock:
            s = self._read(0x0A)
            r = self._read(0x0B)
            try:
                self._poll_rds(s)
            except OSError:
                pass
        self.freq = self._chan_to_freq(s & 0x3FF)
        out = {"available": True, "band": "FM", "mode": "fm", "freq": self.freq,
               "label": "%.1f MHz" % (self.freq / 100), "rssi": r >> 9, "snr": None,
               "valid": bool(r & 0x0100), "stereo": bool(s & ST),
               "volume": self.volume, "volume_max": self.volume_max}
        ps = "".join(self.rds_ps).strip()
        if ps:
            out["rds"] = ps
        return out

    def power_down(self):
        with self.lock:
            self._write(0x02, 0)
