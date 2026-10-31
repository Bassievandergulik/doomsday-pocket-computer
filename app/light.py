"""Torch: a 1 W white LED and a red LED, each switched by a MOSFET from a GPIO.

Default pins: white GPIO12, red GPIO13 (free next to the 3.5" screen, the I2C bus,
the GPS UART and the radio reset pin). Brightness is PWM via lgpio; without lgpio
(on a PC) the light just reports itself unavailable.
"""
import threading

try:
    import lgpio
except ImportError:
    lgpio = None

PWM_HZ = 800  # well above visible flicker
# SOS in Morse: ... --- ...   (dot 0.2 s; dash 3 dots; gaps 1 dot; letters 3; repeat after 7)
DOT = 0.2
SOS = [1, 1, 1, 0, 3, 3, 3, 0, 1, 1, 1]


class Light:
    def __init__(self, white_gpio=12, red_gpio=13):
        self.pins = {"white": white_gpio, "red": red_gpio}
        self.level = {"white": 0, "red": 0}
        self.bright = {"white": 100, "red": 30}
        self.sos = False
        self.available = False
        self.error = None
        self.h = None
        self._sos_thread = None
        self._wake = threading.Event()
        if lgpio is None:
            self.error = "lgpio not installed (not on a Raspberry Pi?)"
            return
        try:
            self.h = lgpio.gpiochip_open(0)
            for p in self.pins.values():
                lgpio.gpio_claim_output(self.h, p, 0)
            self.available = True
        except Exception as e:  # lgpio raises its own error type
            self.error = "GPIO not available: %s" % e

    def _out(self, which, pct):
        if not self.available:
            return
        pin = self.pins[which]
        if pct <= 0:
            lgpio.tx_pwm(self.h, pin, PWM_HZ, 0)
            lgpio.gpio_write(self.h, pin, 0)
        elif pct >= 100:
            lgpio.tx_pwm(self.h, pin, PWM_HZ, 0)
            lgpio.gpio_write(self.h, pin, 1)
        else:
            lgpio.tx_pwm(self.h, pin, PWM_HZ, pct)

    def set(self, which, on=None, brightness=None):
        if which not in self.pins:
            raise ValueError("light is white or red")
        if brightness is not None:
            self.bright[which] = max(5, min(100, int(brightness)))
        if on is None:
            on = self.level[which] > 0
        if which == "white" and self.sos:
            self.set_sos(False)
        self.level[which] = self.bright[which] if on else 0
        self._out(which, self.level[which])
        return self.status()

    def set_sos(self, on):
        self.sos = bool(on)
        if self.sos and not (self._sos_thread and self._sos_thread.is_alive()):
            self._sos_thread = threading.Thread(target=self._sos_loop, daemon=True)
            self._sos_thread.start()
        if not self.sos:
            self._wake.set()
            if self._sos_thread:
                self._sos_thread.join(2)
            self._wake.clear()
            self._out("white", self.level["white"])
        return self.status()

    def _sleep(self, t):
        self._wake.wait(t)

    def _sos_loop(self):
        while self.sos:
            for i, d in enumerate(SOS):
                if not self.sos:
                    break
                if d:
                    self._out("white", 100)
                    self._sleep(d * DOT)
                    self._out("white", 0)
                    self._sleep(DOT)
                else:
                    self._sleep(2 * DOT)  # letter gap (3 dots incl. the one above)
            self._sleep(6 * DOT)  # word gap

    def status(self):
        return {"available": self.available, "error": self.error, "sos": self.sos,
                "white": {"on": self.level["white"] > 0, "brightness": self.bright["white"]},
                "red": {"on": self.level["red"] > 0, "brightness": self.bright["red"]}}
