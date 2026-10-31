"""Audio capture from the USB sound stick (the radio's audio goes into its mic input).

Uses `arecord` (alsa-utils), so nothing extra is needed in Python. The Pi Zero
has no audio input of its own, so the first USB capture card is the sound stick.
"""
import os
import re
import subprocess
import threading
import wave

import numpy as np

RATE = 8000  # enough for fax (tones up to ~2.9 kHz) and RTTY, and light on the Pi Zero


def find_device(setting="auto", playback=False):
    """ALSA device for arecord (or aplay with playback=True), e.g. 'plughw:1,0', or None."""
    if setting and setting != "auto":
        return setting
    try:
        out = subprocess.run(["aplay" if playback else "arecord", "-l"], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    cards = re.findall(r"^card (\d+): (\S+) \[(.*?)\], device (\d+):", out, re.M)
    if not cards:
        return None
    usb = [c for c in cards if "usb" in (c[1] + c[2]).lower()] or cards
    return "plughw:%s,%s" % (usb[0][0], usb[0][3])


class Recorder:
    """Records one WAV file in the background; stop() ends it early."""

    def __init__(self, device, path, seconds, rate=RATE):
        self.device, self.path, self.seconds, self.rate = device, path, int(seconds), rate
        self.proc = None
        self.error = None
        self.done = threading.Event()

    def start(self):
        cmd = ["arecord", "-q", "-D", self.device, "-f", "S16_LE", "-c", "1", "-r", str(self.rate),
               "-d", str(self.seconds), "-t", "wav", self.path]
        try:
            self.proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
        except OSError as e:
            self.error = "arecord not found (%s)" % e
            self.done.set()
            return self
        threading.Thread(target=self._wait, daemon=True).start()
        return self

    def _wait(self):
        _, err = self.proc.communicate()
        if self.proc.returncode not in (0, -2, -15) and not os.path.exists(self.path):
            self.error = (err or b"").decode(errors="replace").strip() or "recording failed"
        self.done.set()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()  # arecord closes the WAV properly on SIGTERM
        self.done.wait(10)

    def level(self):
        """Rough input level 0..1 from the last second written, for the screen."""
        try:
            size = os.path.getsize(self.path)
            if size < 44 + 2 * self.rate:
                return None
            with open(self.path, "rb") as f:
                f.seek(size - 2 * self.rate)
                x = np.frombuffer(f.read(2 * self.rate), dtype="<i2").astype(np.float32)
            return float(min(1.0, np.sqrt(np.mean(x * x)) / 8000.0))
        except OSError:
            return None


def read_wav(path):
    """WAV file -> (float32 samples -1..1, sample rate). Tolerates a truncated header."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        with wave.open(path, "rb") as w:
            fs, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
    except (wave.Error, EOFError):
        fs, ch, width = RATE, 1, 2
    data = raw[44:] if raw[:4] == b"RIFF" else raw
    n = len(data) // (width * ch) * (width * ch)
    x = np.frombuffer(data[:n], dtype="<i2" if width == 2 else np.uint8).astype(np.float32)
    if width == 1:
        x = x - 128
    x = x.reshape(-1, ch).mean(axis=1) / (32768.0 if width == 2 else 128.0)
    return x.astype(np.float32), fs
