"""Meshtastic node on USB (Heltec or LilyGO LoRa boards): messages, nodes, text and position.

Uses the official `meshtastic` Python package (pip install meshtastic). The node
does the radio work (LoRa, no internet, no phone network); this just talks to it
over USB serial. Without the package or a node, the section says so and nothing else breaks.
"""
import collections
import threading
import time

try:
    import meshtastic.serial_interface
    from pubsub import pub
except ImportError:
    meshtastic = None
    pub = None

MAX_TEXT = 200  # bytes; Meshtastic's text limit is about 230


class Mesh:
    def __init__(self, port="auto", get_position=None, max_messages=200):
        self.port = port
        self.get_position = get_position   # callable -> (lat, lon) or None
        self.iface = None
        self.error = None
        self.messages = collections.deque(maxlen=max_messages)
        self.available = meshtastic is not None
        if not self.available:
            self.error = "meshtastic package not installed (pip install meshtastic)"
        self._lock = threading.Lock()

    def start(self):
        if self.available:
            threading.Thread(target=self._connect_loop, daemon=True).start()

    def _connect_loop(self):
        while True:
            if self.iface is None:
                try:
                    dev = None if self.port == "auto" else self.port
                    self.iface = meshtastic.serial_interface.SerialInterface(dev)
                    pub.subscribe(self._on_text, "meshtastic.receive.text")
                    self.error = None
                except Exception as e:  # no node plugged in, or port busy
                    self.iface = None
                    self.error = "No Meshtastic node found (%s)" % str(e).splitlines()[0][:120]
            time.sleep(15)

    def _on_text(self, packet, interface=None):
        try:
            text = packet["decoded"]["text"]
            sender = packet.get("fromId") or str(packet.get("from"))
        except (KeyError, TypeError):
            return
        with self._lock:
            self.messages.append({"t": time.time(), "from": sender, "text": text, "out": False,
                                  "snr": packet.get("rxSnr")})

    def send_text(self, text):
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        if len(text.encode()) > MAX_TEXT:
            raise ValueError("message too long (max %d characters)" % MAX_TEXT)
        if self.iface is None:
            raise RuntimeError(self.error or "no node")
        self.iface.sendText(text)
        with self._lock:
            self.messages.append({"t": time.time(), "from": "me", "text": text, "out": True, "snr": None})

    def share_position(self):
        pos = self.get_position() if self.get_position else None
        if not pos:
            raise RuntimeError("no position yet: set one on the map or wait for GPS")
        if self.iface is None:
            raise RuntimeError(self.error or "no node")
        self.iface.localNode.sendPosition(pos[0], pos[1])
        self.send_text("My position: %.5f, %.5f" % pos)  # plain text too, so any app shows it

    def nodes(self):
        if self.iface is None:
            return []
        out = []
        for n in list((self.iface.nodes or {}).values()):
            user = n.get("user", {})
            pos = n.get("position", {})
            out.append({"name": user.get("longName") or user.get("shortName") or n.get("num"),
                        "lat": pos.get("latitude"), "lon": pos.get("longitude"),
                        "snr": n.get("snr"), "last_heard": n.get("lastHeard")})
        return out

    def status(self):
        with self._lock:
            msgs = list(self.messages)[-50:]
        return {"available": self.available and self.iface is not None, "error": self.error,
                "messages": msgs, "nodes": self.nodes()}
