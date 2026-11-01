"""Si4732 / Si4735 FM + AM (MW/LW/SW) + SSB receiver over I2C (the default radio).

Command set from Silicon Labs AN332. Audio comes straight out of the chip's
analog pins into a small amplifier and speaker, and (for weather fax / RTTY)
into a USB sound stick.

SSB (USB/LSB, needed for weather fax and RTTY) needs Silicon Labs' SSB patch
loaded into the chip's RAM after every power-up. The patch is not part of this
software: tools/get_ssb_patch.py downloads it once into data/ssb_patch.bin.
Without it, FM/AM/SW still work and the USB/LSB bands are hidden.

Wiring (Raspberry Pi 3 B+):  SDA -> GPIO2, SCL -> GPIO3, RST -> GPIO23 (configurable),
3.3 V, GND, 32.768 kHz crystal on the module. SEN low = I2C address 0x11, high = 0x63.
"""
import threading
import time

try:
    from smbus2 import i2c_msg
except ImportError:
    i2c_msg = None

# commands
POWER_UP, GET_REV, POWER_DOWN, SET_PROPERTY, GET_INT_STATUS = 0x01, 0x10, 0x11, 0x12, 0x14
FM_TUNE_FREQ, FM_SEEK_START, FM_TUNE_STATUS, FM_RSQ_STATUS, FM_RDS_STATUS = 0x20, 0x21, 0x22, 0x23, 0x24
AM_TUNE_FREQ, AM_SEEK_START, AM_TUNE_STATUS = 0x40, 0x41, 0x42
# properties
RX_VOLUME, RX_HARD_MUTE = 0x4000, 0x4001
FM_DEEMPHASIS = 0x1100
FM_SEEK_BAND_BOTTOM, FM_SEEK_BAND_TOP, FM_SEEK_FREQ_SPACING = 0x1400, 0x1401, 0x1402
FM_RDS_INT_SOURCE, FM_RDS_INT_FIFO_COUNT, FM_RDS_CONFIG = 0x1500, 0x1501, 0x1502
AM_CHANNEL_FILTER = 0x3102
AM_SEEK_BAND_BOTTOM, AM_SEEK_BAND_TOP, AM_SEEK_FREQ_SPACING = 0x3400, 0x3401, 0x3402
AM_SOFT_MUTE_MAX_ATTENUATION = 0x3302
SSB_BFO, SSB_MODE = 0x0100, 0x0101
# SSB_MODE: AUDIOBW 3 kHz (2), sideband cutoff filter on (1<<4), AVC off, DSP AFC off (1<<15)
SSB_MODE_VALUE = 0x8012
USB, LSB = 2, 1

# band name -> (mode, low, high, step, default)   FM in 10 kHz units, AM in kHz
BANDS = {
    "FM": ("fm", 8750, 10800, 10, 9800),
    "MW": ("am", 522, 1710, 9, 1008),     # 9 kHz raster in Europe
    "LW": ("am", 153, 279, 9, 198),
    "SW49m": ("am", 5900, 6200, 5, 6000),
    "SW41m": ("am", 7200, 7600, 5, 7300),
    "SW31m": ("am", 9400, 9900, 5, 9500),
    "SW25m": ("am", 11600, 12100, 5, 11700),
    "SW19m": ("am", 15100, 15800, 5, 15400),
    "SW": ("am", 2300, 26100, 5, 9500),
}
# SSB bands only appear when the patch file exists. Steps are 1 kHz (fine tuning via BFO).
SSB_BANDS = {
    "USB": ("usb", 1800, 30000, 1, 7880),
    "LSB": ("lsb", 1800, 30000, 1, 3700),
}


def load_patch(path):
    """Patch file -> bytes (rows of 8), or None if missing/invalid."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except (OSError, TypeError):
        return None
    if not data or len(data) % 8 or data[0] != 0x15:
        return None
    return data


class Si4732:
    volume_max = 63

    def __init__(self, bus, address=0x11, reset_gpio=23, ssb_patch=None):
        self.bus = bus
        self.patch = load_patch(ssb_patch) if ssb_patch else None
        self.bands = dict(BANDS, **SSB_BANDS) if self.patch else dict(BANDS)
        self.bfo = 0
        self.addr = address
        self.reset_gpio = reset_gpio
        self.mode = None
        self.band = "FM"
        self.freq = None
        self.volume = 40
        self.rds_ps = [" "] * 8
        self.lock = threading.Lock()
        self.available = False
        self.error = None
        if bus is None or i2c_msg is None:
            self.error = "smbus2 / I2C not available"
            return
        try:
            self._reset()
            self.set_band("FM")
            self.available = True
        except OSError as e:
            self.error = "Si4732 not found on I2C (%s)" % e

    # --- low level -------------------------------------------------------
    def _reset(self):
        if self.reset_gpio is None:
            return
        try:
            import lgpio
        except ImportError:
            return  # RST tied high through an RC network instead
        h = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_output(h, self.reset_gpio, 0)
        time.sleep(0.01)
        lgpio.gpio_write(h, self.reset_gpio, 1)
        time.sleep(0.01)
        lgpio.gpiochip_close(h)

    def _cmd(self, cmd, args=(), resp_len=1, timeout=0.5):
        self.bus.i2c_rdwr(i2c_msg.write(self.addr, [cmd] + list(args)))
        deadline = time.time() + timeout
        while True:
            r = i2c_msg.read(self.addr, resp_len)
            self.bus.i2c_rdwr(r)
            data = list(r)
            if data[0] & 0x80:  # CTS
                if data[0] & 0x40:
                    raise OSError("Si4732 command 0x%02x error" % cmd)
                return data
            if time.time() > deadline:
                raise OSError("Si4732 timeout on command 0x%02x" % cmd)
            time.sleep(0.002)

    def _prop(self, prop, value):
        self._cmd(SET_PROPERTY, [0, prop >> 8, prop & 0xFF, value >> 8, value & 0xFF])

    def _wait_stc(self, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._cmd(GET_INT_STATUS)[0] & 0x01:
                return True
            time.sleep(0.02)
        return False

    def _download_patch(self):
        """Send the SSB patch, 8 bytes per write, checking CTS/ERR after each row."""
        p = self.patch
        for off in range(0, len(p), 8):
            self.bus.i2c_rdwr(i2c_msg.write(self.addr, list(p[off:off + 8])))
            for _ in range(200):
                r = i2c_msg.read(self.addr, 1)
                self.bus.i2c_rdwr(r)
                st = list(r)[0]
                if st & 0x80:
                    break
            else:
                raise OSError("Si4732 patch: no CTS at byte %d" % off)
            if st & 0x40:
                raise OSError("Si4732 patch rejected at byte %d (wrong chip or patch file?)" % off)

    def _power_up(self, mode):
        try:
            self._cmd(POWER_DOWN)
        except OSError:
            pass
        func = 0x00 if mode == "fm" else 0x01
        ssb = mode in ("usb", "lsb")
        if ssb:
            self._reset()  # the patch must go into a freshly reset chip
            self._cmd(POWER_UP, [0x20 | 0x10 | func, 0x05])  # PATCH, XOSCEN, AM, analog out
            time.sleep(0.5)
            self._download_patch()
        else:
            self._cmd(POWER_UP, [0x10 | func, 0x05])  # XOSCEN, analog audio out
            time.sleep(0.5)  # crystal start-up
        self.mode = mode
        if ssb:
            self._prop(SSB_MODE, SSB_MODE_VALUE)
            self._prop(AM_SOFT_MUTE_MAX_ATTENUATION, 0)
            self._prop(SSB_BFO, self.bfo & 0xFFFF)
        elif mode == "fm":
            self._prop(FM_DEEMPHASIS, 1)  # 50 us, Europe
            self._prop(FM_RDS_INT_SOURCE, 0x0001)
            self._prop(FM_RDS_INT_FIFO_COUNT, 1)
            self._prop(FM_RDS_CONFIG, 0xAA01)
        else:
            self._prop(AM_CHANNEL_FILTER, 0x0100 | 2)  # 3 kHz bandwidth, AMPLFLT on
            self._prop(AM_SOFT_MUTE_MAX_ATTENUATION, 0)
        self._prop(RX_VOLUME, self.volume)

    # --- public API ------------------------------------------------------
    def _ssb(self):
        return self.mode in ("usb", "lsb")

    def set_band(self, band):
        mode, lo, hi, step, default = self.bands[band]
        with self.lock:
            if mode in ("usb", "lsb") and self._ssb():
                self.mode = mode  # same patched firmware, only the sideband changes
            elif mode != self.mode:
                self._power_up(mode)
            if mode == "fm":
                self._prop(FM_SEEK_BAND_BOTTOM, lo)
                self._prop(FM_SEEK_BAND_TOP, hi)
                self._prop(FM_SEEK_FREQ_SPACING, step)
            else:
                self._prop(AM_SEEK_BAND_BOTTOM, lo)
                self._prop(AM_SEEK_BAND_TOP, hi)
                self._prop(AM_SEEK_FREQ_SPACING, step)
            self.band = band
        self.tune(default if not (self.freq and lo <= self.freq <= hi) else self.freq)

    def tune(self, freq):
        """freq: FM in 10 kHz units (e.g. 9800 = 98.0 MHz), AM in kHz."""
        mode, lo, hi, _, _ = self.bands[self.band]
        freq = max(lo, min(hi, int(freq)))
        with self.lock:
            if self.mode == "fm":
                self._cmd(FM_TUNE_FREQ, [0, freq >> 8, freq & 0xFF, 0])
            elif self._ssb():
                side = USB if self.mode == "usb" else LSB
                self._cmd(AM_TUNE_FREQ, [(side << 6) | 0x01, freq >> 8, freq & 0xFF, 0, 0])
            else:
                self._cmd(AM_TUNE_FREQ, [0, freq >> 8, freq & 0xFF, 0, 0])
            self._wait_stc()
            self.rds_ps = [" "] * 8
        return self.status()

    def step(self, direction):
        _, _, _, step, _ = self.bands[self.band]
        return self.tune((self.freq or self.bands[self.band][4]) + step * direction)

    def set_bfo(self, hz):
        """SSB fine tuning in Hz (-16383..16383)."""
        self.bfo = max(-16000, min(16000, int(hz)))
        if self._ssb():
            with self.lock:
                self._prop(SSB_BFO, self.bfo & 0xFFFF)
        return self.bfo

    def seek(self, up=True):
        if self._ssb():
            return self.step(1 if up else -1)  # no seek in SSB: nothing to lock on to
        with self.lock:
            flags = (0x08 if up else 0) | 0x04  # SEEKUP, WRAP
            if self.mode == "fm":
                self._cmd(FM_SEEK_START, [flags])
            else:
                self._cmd(AM_SEEK_START, [flags, 0, 0, 0, 0])
            self._wait_stc(timeout=20)
            self.rds_ps = [" "] * 8
        return self.status()

    def set_volume(self, v):
        self.volume = max(0, min(63, int(v)))
        with self.lock:
            self._prop(RX_VOLUME, self.volume)
        return self.volume

    def mute(self, on):
        with self.lock:
            self._prop(RX_HARD_MUTE, 3 if on else 0)

    def _poll_rds(self):
        """Read any waiting RDS group and collect the 8-character station name (PS)."""
        for _ in range(8):
            r = self._cmd(FM_RDS_STATUS, [0x01], resp_len=13)
            if r[3] == 0:  # FIFO empty
                return
            block_b = (r[6] << 8) | r[7]
            block_d = (r[10] << 8) | r[11]
            if (block_b >> 12) == 0:  # group 0A/0B carries PS
                seg = block_b & 0x03
                for i, ch in enumerate((block_d >> 8, block_d & 0xFF)):
                    if 32 <= ch < 127:
                        self.rds_ps[seg * 2 + i] = chr(ch)

    def status(self):
        if not self.available:
            return {"available": False, "error": self.error}
        with self.lock:
            if self.mode == "fm":
                r = self._cmd(FM_TUNE_STATUS, [0x01], resp_len=8)
                try:
                    self._poll_rds()
                except OSError:
                    pass
            else:
                r = self._cmd(AM_TUNE_STATUS, [0x01], resp_len=8)
        self.freq = (r[2] << 8) | r[3]
        out = {"available": True, "band": self.band, "mode": self.mode, "freq": self.freq,
               "rssi": r[4], "snr": r[5], "valid": bool(r[1] & 0x01), "volume": self.volume,
               "volume_max": self.volume_max}
        if self.mode == "fm":
            out["label"] = "%.1f MHz" % (self.freq / 100)
            ps = "".join(self.rds_ps).strip()
            if ps:
                out["rds"] = ps
        elif self._ssb():
            out["label"] = "%d kHz %s" % (self.freq, self.mode.upper())
            out["bfo"] = self.bfo
        else:
            out["label"] = "%d kHz" % self.freq
        out["ssb"] = self.patch is not None
        return out

    def power_down(self):
        with self.lock:
            self._cmd(POWER_DOWN)
            self.mode = None
