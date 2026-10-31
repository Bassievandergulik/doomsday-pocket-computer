"""VHF airband (118-137 MHz AM) through an RTL-SDR USB stick (e.g. Nooelec NESDR SMArt).

Listening uses `rtl_fm` (package rtl-sdr) piped into `aplay` on the USB sound
stick's output. With several frequencies rtl_fm scans them and stops on the
first one that opens the squelch, like a scanner.
"""
import glob
import os
import shutil
import subprocess
import threading

import audio

RTL_IDS = {("0bda", "2838"), ("0bda", "2832")}  # RTL2832U dongles
RATE = 12000  # 12 kHz: an AM airband channel with room for 8.33 kHz channel offsets
SQUELCH = {"off": 0, "low": 50, "medium": 120, "high": 250}
DEFAULT_FREQS = [
    {"name": "Emergency (guard)", "mhz": 121.5},
    {"name": "Air-to-air", "mhz": 123.45},
]


def dongle_present():
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            with open(os.path.join(d, "idVendor")) as f:
                v = f.read().strip()
            with open(os.path.join(d, "idProduct")) as f:
                p = f.read().strip()
        except OSError:
            continue
        if (v, p) in RTL_IDS:
            return True
    return False


class Airband:
    def __init__(self, get_setting, set_setting, audio_out="auto", gain=40):
        self._get, self._set = get_setting, set_setting
        self.audio_out = audio_out
        self.gain = gain
        self.procs = []
        self.lock = threading.Lock()
        self.listening = None   # {"freqs": [...], "squelch": "..."}
        self.error = None

    def ready(self):
        if not shutil.which("rtl_fm"):
            return False, "rtl_fm not installed (sudo apt install rtl-sdr)"
        if not dongle_present():
            return False, "SDR stick not found: plug it into the USB hub"
        if not audio.find_device(self.audio_out, playback=True):
            return False, "No sound output found (USB sound stick)"
        return True, None

    def freqs(self):
        return self._get("air_freqs") or list(DEFAULT_FREQS)

    def add_freq(self, name, mhz):
        mhz = round(float(mhz), 3)
        if not 108.0 <= mhz <= 137.0:
            raise ValueError("airband is 108-137 MHz")
        items = [f for f in self.freqs() if f["mhz"] != mhz] + [{"name": (name or "%.3f" % mhz)[:30], "mhz": mhz}]
        items.sort(key=lambda f: f["mhz"])
        self._set("air_freqs", items)
        return items

    def remove_freq(self, mhz):
        items = [f for f in self.freqs() if f["mhz"] != round(float(mhz), 3)]
        self._set("air_freqs", items)
        return items

    def listen(self, mhz_list, squelch="low"):
        ok, why = self.ready()
        if not ok:
            raise RuntimeError(why)
        mhz_list = [round(float(m), 3) for m in mhz_list][:20]
        if not mhz_list:
            raise ValueError("no frequency")
        if len(mhz_list) > 1 and squelch == "off":
            squelch = "low"  # scanning needs the squelch to know when a channel is busy
        self.stop()
        cmd = ["rtl_fm", "-M", "am", "-s", str(RATE), "-g", str(self.gain), "-l", str(SQUELCH.get(squelch, 50))]
        for m in mhz_list:
            cmd += ["-f", "%.4fM" % m]
        cmd += ["-"]
        play = ["aplay", "-q", "-D", audio.find_device(self.audio_out, playback=True), "-r", str(RATE),
                "-f", "S16_LE", "-t", "raw", "-c", "1"]
        with self.lock:
            p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p2 = subprocess.Popen(play, stdin=p1.stdout, stderr=subprocess.DEVNULL)
            p1.stdout.close()
            self.procs = [p1, p2]
            self.listening = {"freqs": mhz_list, "squelch": squelch}
        return self.status()

    def stop(self):
        with self.lock:
            for p in self.procs:
                if p.poll() is None:
                    p.terminate()
            for p in self.procs:
                try:
                    p.wait(3)
                except subprocess.TimeoutExpired:
                    p.kill()
            self.procs = []
            self.listening = None

    def status(self):
        ok, why = self.ready()
        if self.procs and any(p.poll() is not None for p in self.procs):
            self.error = "The receiver stopped (stick unplugged or busy?)"
            self.stop()
        return {"ready": ok, "reason": why, "listening": self.listening, "freqs": self.freqs(),
                "squelch_levels": list(SQUELCH), "error": self.error}
