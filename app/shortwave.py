"""Weather by shortwave: receive weather fax charts and RTTY text bulletins
with the Si4732 (SSB patch) and the USB sound stick, without any internet.

A reception tunes the radio to USB, records the sound stick for a few minutes,
puts the radio back the way it was, then decodes the recording in a separate
low-priority process (so the screen stays responsive) into PNG charts or text.

Results live in data/shortwave/: <stamp>-<station>.png (full 1810 px), .small.png
(905 px, for the screen), .txt (RTTY) and a .json with what/when/how good.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time

import audio

HERE = os.path.dirname(os.path.abspath(__file__))

# Assigned frequencies in kHz. In USB the radio is tuned ~1.9 kHz lower so the
# signal lands in the middle of the audio band; the decoders find the exact tones.
def _st(region, sid, short, name, kind, khz):
    return sid, {"region": region, "short": short, "name": name, "kind": kind, "khz": khz}


# Carrier ("assigned") frequencies in kHz, as broadcast schedules list them. The radio
# is tuned about 1.9 kHz lower in USB; the decoders then find the exact tones.
# Schedules change; check the current lists (DWD, NOAA "Worldwide Marine Radiofacsimile
# Broadcast Schedules") when you have internet and add daily times on the device.
STATIONS = dict([
    _st("Europe", "dwd-fax-3855", "Fax 3855", "DWD Germany fax 3855 kHz (night)", "fax", 3855.0),
    _st("Europe", "dwd-fax-7880", "Fax 7880", "DWD Germany fax 7880 kHz (day and night)", "fax", 7880.0),
    _st("Europe", "dwd-fax-13882", "Fax 13882", "DWD Germany fax 13882.5 kHz (day, long range)", "fax", 13882.5),
    _st("Europe", "nwd-fax-4610", "UK fax 4610", "Northwood UK fax 4610 kHz", "fax", 4610.0),
    _st("Europe", "nwd-fax-8040", "UK fax 8040", "Northwood UK fax 8040 kHz", "fax", 8040.0),
    _st("Europe", "dwd-rtty-4583", "Text 4583", "DWD Germany text (RTTY) 4583 kHz (night)", "rtty", 4583.0),
    _st("Europe", "dwd-rtty-7646", "Text 7646", "DWD Germany text (RTTY) 7646 kHz", "rtty", 7646.0),
    _st("Europe", "dwd-rtty-10100", "Text 10101", "DWD Germany text (RTTY) 10100.8 kHz (day)", "rtty", 10100.8),
    _st("Atlantic", "nmf-fax-4235", "Boston 4235", "NOAA Boston (NMF) fax 4235 kHz (night)", "fax", 4235.0),
    _st("Atlantic", "nmf-fax-6340", "Boston 6340", "NOAA Boston (NMF) fax 6340.5 kHz", "fax", 6340.5),
    _st("Atlantic", "nmf-fax-9110", "Boston 9110", "NOAA Boston (NMF) fax 9110 kHz", "fax", 9110.0),
    _st("Atlantic", "nmf-fax-12750", "Boston 12750", "NOAA Boston (NMF) fax 12750 kHz (day)", "fax", 12750.0),
    _st("Atlantic", "nmg-fax-8503", "N.Orleans 8504", "NOAA New Orleans (NMG) fax 8503.9 kHz", "fax", 8503.9),
    _st("Atlantic", "nmg-fax-12789", "N.Orleans 12790", "NOAA New Orleans (NMG) fax 12789.9 kHz", "fax", 12789.9),
    _st("Pacific", "nmc-fax-8682", "Pt Reyes 8682", "NOAA Point Reyes (NMC) fax 8682 kHz", "fax", 8682.0),
    _st("Pacific", "nmc-fax-12786", "Pt Reyes 12786", "NOAA Point Reyes (NMC) fax 12786 kHz", "fax", 12786.0),
    _st("Pacific", "nmc-fax-17151", "Pt Reyes 17151", "NOAA Point Reyes (NMC) fax 17151.2 kHz (day)", "fax", 17151.2),
    _st("Pacific", "kvm-fax-9982", "Hawaii 9982", "NOAA Honolulu (KVM70) fax 9982.5 kHz", "fax", 9982.5),
    _st("Pacific", "kvm-fax-11090", "Hawaii 11090", "NOAA Honolulu (KVM70) fax 11090 kHz", "fax", 11090.0),
    _st("Pacific", "kvm-fax-16135", "Hawaii 16135", "NOAA Honolulu (KVM70) fax 16135 kHz (day)", "fax", 16135.0),
    _st("Asia", "jmh-fax-3622", "Japan 3622", "JMA Tokyo (JMH) fax 3622.5 kHz (night)", "fax", 3622.5),
    _st("Asia", "jmh-fax-7795", "Japan 7795", "JMA Tokyo (JMH) fax 7795 kHz", "fax", 7795.0),
    _st("Asia", "jmh-fax-13988", "Japan 13988", "JMA Tokyo (JMH) fax 13988.5 kHz (day)", "fax", 13988.5),
    _st("Australia", "vmc-fax-5100", "Charleville 5100", "BoM Charleville (VMC) fax 5100 kHz", "fax", 5100.0),
    _st("Australia", "vmc-fax-11030", "Charleville 11030", "BoM Charleville (VMC) fax 11030 kHz", "fax", 11030.0),
    _st("Australia", "vmc-fax-13920", "Charleville 13920", "BoM Charleville (VMC) fax 13920 kHz (day)", "fax", 13920.0),
    _st("Australia", "vmw-fax-7535", "Wiluna 7535", "BoM Wiluna (VMW) fax 7535 kHz", "fax", 7535.0),
    _st("Australia", "vmw-fax-10555", "Wiluna 10555", "BoM Wiluna (VMW) fax 10555 kHz", "fax", 10555.0),
    _st("Australia", "vmw-fax-15615", "Wiluna 15615", "BoM Wiluna (VMW) fax 15615 kHz (day)", "fax", 15615.0),
])
AUDIO_CENTRE_KHZ = 1.9


def dial_for(khz):
    """Carrier frequency -> (USB dial kHz, expected audio centre Hz). The radio tunes in
    whole kHz, so the centre lands between 1.4 and 2.4 kHz, inside the 3 kHz filter."""
    import math
    dial = int(math.floor(khz - 1.4))
    return dial, round((khz - dial) * 1000.0, 1)


class Shortwave:
    def __init__(self, app, out_dir, device="auto", capture_volume=45, keep_audio=False):
        self.app = app
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.device_setting = device
        self.capture_volume = capture_volume
        self.keep_audio = keep_audio
        self.job = None          # the reception in progress (dict) or None
        self.last = None         # outcome of the last reception
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._rec = None
        self._ran = {}           # schedule id -> date it last ran

    # --- what the screen needs --------------------------------------------
    def ready(self):
        """(ok, reason): can we receive at all?"""
        r = self.app.radio
        if not r.available:
            return False, "No radio found"
        if "USB" not in getattr(r, "bands", {}):
            return False, "SSB patch missing: run tools/get_ssb_patch.py once (needs internet)"
        if not audio.find_device(self.device_setting):
            return False, "USB sound stick not found"
        return True, None

    def status(self):
        ok, why = self.ready()
        job = dict(self.job) if self.job else None
        if job and self._rec and job.get("state") == "recording":
            job["level"] = self._rec.level()
            job["elapsed_s"] = round(time.time() - job["started"])
        return {"ready": ok, "reason": why, "job": job, "last": self.last,
                "stations": [dict(id=k, **v, dial=dial_for(v["khz"])[0]) for k, v in STATIONS.items()],
                "regions": list(dict.fromkeys(v["region"] for v in STATIONS.values())),
                "schedule": self.schedule(), "results": self.results(), "utc": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%H:%M")}

    def results(self, limit=40):
        out = []
        try:
            names = sorted((n for n in os.listdir(self.out_dir) if n.endswith(".json")), reverse=True)
        except OSError:
            return out
        for n in names[:limit]:
            try:
                with open(os.path.join(self.out_dir, n)) as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                pass
        return out

    def delete(self, rid):
        base = os.path.basename(str(rid))
        n = 0
        for ext in (".json", ".png", ".small.png", ".txt", ".wav"):
            p = os.path.join(self.out_dir, base + ext)
            if os.path.exists(p):
                os.remove(p)
                n += 1
        return n > 0

    # --- schedule (times in UTC, like the published broadcast schedules) ---
    def schedule(self):
        return self.app.get_setting("sw_schedule") or []

    def add_schedule(self, hhmm, station, minutes):
        h, m = (int(v) for v in str(hhmm).split(":"))
        if not (0 <= h < 24 and 0 <= m < 60) or station not in STATIONS:
            raise ValueError("bad time or station")
        items = self.schedule()
        items.append({"id": int(time.time() * 1000) % 10 ** 10, "time": "%02d:%02d" % (h, m),
                      "station": station, "minutes": max(2, min(40, int(minutes)))})
        items.sort(key=lambda s: s["time"])
        self.app.set_setting("sw_schedule", items)
        return items

    def remove_schedule(self, sid):
        items = [s for s in self.schedule() if s["id"] != int(sid)]
        self.app.set_setting("sw_schedule", items)
        return items

    def start_scheduler(self):
        threading.Thread(target=self._scheduler, daemon=True).start()

    def _scheduler(self):
        while True:
            now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            for s in self.schedule():
                h, m = (int(v) for v in s["time"].split(":"))
                due = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if 0 <= (now - due).total_seconds() < 90 and self._ran.get(s["id"]) != now.date():
                    self._ran[s["id"]] = now.date()
                    try:
                        self.receive(s["station"], s["minutes"], scheduled=True)
                    except RuntimeError:
                        pass  # busy with another reception
            time.sleep(20)

    # --- a reception ------------------------------------------------------
    def receive(self, station, minutes=12, scheduled=False):
        if station not in STATIONS:
            raise ValueError("unknown station")
        ok, why = self.ready()
        if not ok:
            raise RuntimeError(why)
        with self.lock:
            if self.job:
                raise RuntimeError("Already receiving")
            st = STATIONS[station]
            self.job = {"station": station, "name": st["name"], "kind": st["kind"], "state": "tuning",
                        "minutes": max(1, min(40, int(minutes))), "started": time.time(), "scheduled": scheduled}
            self._stop.clear()
        threading.Thread(target=self._run, daemon=True).start()
        return self.job

    def stop(self):
        self._stop.set()
        if self._rec:
            self._rec.stop()

    def _run(self):
        job = self.job
        st = STATIONS[job["station"]]
        r = self.app.radio
        stamp = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y%m%d-%H%M")
        base = "%s-%s" % (stamp, job["station"])
        wav = os.path.join(self.out_dir, base + ".wav")
        saved = None
        outcome = {"station": job["station"], "name": st["name"], "kind": st["kind"], "time_utc": stamp}
        try:
            before = r.status()
            saved = (before.get("band"), before.get("freq"), r.volume)
            dial, centre = dial_for(st["khz"])
            r.set_band("USB")
            r.set_bfo(0)
            r.tune(dial)
            r.set_volume(self.capture_volume)
            time.sleep(1.0)
            sig = r.status()
            job.update(state="recording", started=time.time(), rssi=sig.get("rssi"), snr=sig.get("snr"))
            self._rec = audio.Recorder(audio.find_device(self.device_setting), wav, job["minutes"] * 60).start()
            while not self._rec.done.wait(2):
                if self._stop.is_set():
                    self._rec.stop()
                    break
                try:
                    s = r.status()
                    job.update(rssi=s.get("rssi"), snr=s.get("snr"))
                except OSError:
                    pass
            if self._rec.error:
                raise RuntimeError(self._rec.error)
        except (OSError, RuntimeError, KeyError) as e:
            outcome.update(ok=False, message="Reception failed: %s" % e)
            self._finish(outcome, saved, wav)
            return
        finally:
            self._rec = None
        self._restore(saved)
        if self._stop.is_set() and time.time() - job["started"] < 60:
            outcome.update(ok=False, message="Stopped")
            self._finish(outcome, None, wav)
            return
        job["state"] = "decoding"
        try:
            res = decode_in_background(wav, st["kind"], centre, os.path.join(self.out_dir, base))
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            res = {"ok": False, "message": "Decoding failed: %s" % e}
        outcome.update(res)
        if res.get("ok"):
            for i, item in enumerate(res.get("items", [])):
                meta = dict(outcome, id=item["id"], file=item.get("file"), small=item.get("small"),
                            lines=item.get("lines"), complete=item.get("complete"), quality=item.get("quality"),
                            chars=item.get("chars"))
                meta.pop("items", None)
                with open(os.path.join(self.out_dir, item["id"] + ".json"), "w") as f:
                    json.dump(meta, f)
        self._finish(outcome, None, wav)

    def _restore(self, saved):
        if not saved:
            return
        band, freq, vol = saved
        r = self.app.radio
        try:
            if band:
                r.set_band(band)
            if freq:
                r.tune(freq)
            r.set_volume(vol)
        except (OSError, KeyError, ValueError):
            pass

    def _finish(self, outcome, saved, wav):
        self._restore(saved)
        if not self.keep_audio and os.path.exists(wav):
            os.remove(wav)
        outcome.pop("items", None)
        self.last = outcome
        self.job = None


def decode_in_background(wav, kind, centre, out_base, timeout=900):
    """Run decode_file in a separate, low-priority process and return its result."""
    cmd = ["nice", "-n", "15", sys.executable, os.path.join(HERE, "shortwave.py"), wav, kind, str(centre), out_base]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
    if not lines:
        raise ValueError((p.stderr or "no output").strip().splitlines()[-1][:200])
    return json.loads(lines[-1])


def decode_file(wav, kind, centre, out_base):
    """Decode one recording. Fax -> PNG charts; RTTY -> text. Returns a result dict."""
    x, fs = audio.read_wav(wav)
    if len(x) < fs * 20:
        return {"ok": False, "message": "Recording too short"}
    if kind == "fax":
        import wefax
        found = wefax.decode(x, fs, centre=centre, find_centre=True)
        items = []
        for i, r in enumerate(found):
            if r["lines"] < 60:
                continue
            rid = os.path.basename(out_base) + ("-%d" % (i + 1) if len(found) > 1 else "")
            path = os.path.join(os.path.dirname(out_base), rid)
            wefax.write_png(path + ".png", r["image"])
            wefax.write_png(path + ".small.png", wefax.downscale(r["image"]))
            items.append({"id": rid, "file": rid + ".png", "small": rid + ".small.png",
                          "lines": r["lines"], "complete": r["complete"]})
        if not items:
            return {"ok": False, "message": "No chart found: weak signal, or nothing was sent at this time"}
        return {"ok": True, "items": items,
                "message": "%d chart%s received" % (len(items), "" if len(items) == 1 else "s")}
    if kind == "rtty":
        import rtty
        text, info = rtty.decode(x, fs)
        text = text.replace("\r", "").strip()
        letters = sum(c.isalnum() for c in text)
        if letters < 40 or info["quality"] < 0.7:
            return {"ok": False, "message": "No readable text: weak signal, or nothing was sent at this time"}
        rid = os.path.basename(out_base)
        with open(out_base + ".txt", "w") as f:
            f.write(text + "\n")
        return {"ok": True, "items": [{"id": rid, "file": rid + ".txt", "quality": info["quality"],
                                       "chars": len(text)}], "message": "%d characters of text received" % len(text)}
    raise ValueError("unknown kind " + kind)


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    wav_, kind_, centre_, out_ = sys.argv[1:5]
    print(json.dumps(decode_file(wav_, kind_, float(centre_), out_)))
