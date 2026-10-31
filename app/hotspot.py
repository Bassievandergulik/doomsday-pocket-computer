"""Direct WiFi link: the device becomes a WiFi hotspot your computer joins.

Uses NetworkManager (standard on Raspberry Pi OS Bookworm and newer). While the
hotspot is on, the device is at http://10.42.0.1:8080 for the computer: the
full app plus the Files page for uploading maps and downloading your data.
The single WiFi chip can either be a hotspot or join a network, not both, so
turning the hotspot off reconnects to known networks as before.
"""
import secrets
import shutil
import string
import subprocess
import threading
import time

CON_NAME = "doomsday-hotspot"
HOTSPOT_PREFIX = "10.42.0."  # NetworkManager's shared-mode subnet


def _nmcli(*args, timeout=30):
    if not shutil.which("nmcli"):
        raise OSError("NetworkManager (nmcli) not installed")
    r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise OSError((r.stderr or r.stdout).strip() or "nmcli failed")
    return r.stdout


def new_password():
    alphabet = string.ascii_lowercase + string.digits
    alphabet = "".join(c for c in alphabet if c not in "l1o0")  # easy to read off a small screen
    return "".join(secrets.choice(alphabet) for _ in range(10))


class Hotspot:
    def __init__(self, get_setting, set_setting, auto_off_min=60, ifname="wlan0"):
        self.get_setting = get_setting
        self.set_setting = set_setting
        self.auto_off_min = auto_off_min
        self.ifname = ifname
        self.started = None
        self.last_activity = time.time()
        self.error = None
        creds = get_setting("hotspot") or {}
        if not creds.get("password"):
            creds = {"ssid": "Survival-%s" % secrets.token_hex(2).upper(), "password": new_password()}
            set_setting("hotspot", creds)
        self.ssid, self.password = creds["ssid"], creds["password"]
        threading.Thread(target=self._watch, daemon=True).start()

    def active(self):
        try:
            out = _nmcli("-t", "-f", "NAME", "connection", "show", "--active", timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        return CON_NAME in out.splitlines()

    def on(self):
        try:
            _nmcli("device", "wifi", "hotspot", "ifname", self.ifname, "con-name", CON_NAME,
                   "ssid", self.ssid, "password", self.password, timeout=45)
            self.started = self.last_activity = time.time()
            self.error = None
        except (OSError, subprocess.SubprocessError) as e:
            self.error = str(e)
        return self.status()

    def off(self):
        try:
            _nmcli("connection", "down", CON_NAME)
            self.error = None
        except (OSError, subprocess.SubprocessError) as e:
            self.error = str(e)
        self.started = None
        return self.status()

    def new_password(self):
        self.password = new_password()
        self.set_setting("hotspot", {"ssid": self.ssid, "password": self.password})
        if self.active():
            self.off()
            return self.on()
        return self.status()

    def touch(self):
        self.last_activity = time.time()

    def clients(self):
        """IP addresses of computers on the hotspot (from the ARP table)."""
        try:
            with open("/proc/net/arp") as f:
                rows = f.read().splitlines()[1:]
        except OSError:
            return []
        return [r.split()[0] for r in rows if r.startswith(HOTSPOT_PREFIX) and r.split()[2] != "0x0"]

    def status(self):
        act = self.active()
        return {"active": act, "ssid": self.ssid, "password": self.password,
                "url": "http://%s1:8080" % HOTSPOT_PREFIX if act else None,
                "files_url": "http://%s1:8080/files" % HOTSPOT_PREFIX if act else None,
                "clients": self.clients() if act else [], "error": self.error,
                "auto_off_min": self.auto_off_min,
                "nmcli": shutil.which("nmcli") is not None}

    def _watch(self):
        # switch off after a while without anyone using it, to save the battery
        while True:
            time.sleep(60)
            if self.started and self.auto_off_min:
                if self.clients():
                    self.touch()
                if time.time() - self.last_activity > self.auto_off_min * 60 and self.active():
                    self.off()
