"""Torch: a white LED and a red LED, or one 3 W RGB LED, switched by MOSFETs from GPIOs.

Separate LEDs (default): white GPIO12, red GPIO13 (free next to the 3.5" screen, the
I2C bus, the GPS UART and the radio reset pin).

RGB LED (set light_blue_gpio, e.g. 16): GPIO12 drives the green die, GPIO13 the red
die and the blue GPIO the blue die. "White" lights all three dies, "red" only the
red die, so one LED gives both the torch and the night light. Brightness is PWM via lgpio; without lgpio
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
    def __init__(self, white_gpio=12, red_gpio=13, blue_gpio=None):
        self.pins = {"white": white_gpio, "red": red_gpio}
        self.rgb = blue_gpio is not None
        self.blue = blue_gpio
        self._white_now = 0   # what the white channel shows right now (SOS flashes change it)
        self._pin_now = {}
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
            for p in self._all_pins():
                lgpio.gpio_claim_output(self.h, p, 0)
            self.available = True
        except Exception as e:  # lgpio raises its own error type
            self.error = "GPIO not available: %s" % e

    def _all_pins(self):
        return [self.pins["red"]] + ([self.blue] if self.rgb else []) + [self.pins["white"]]

    def _out(self, which, pct):
        if which == "white":
            self._white_now = pct
        if not self.available:
            return
        w, r = self._white_now, self.level["red"]
        if self.rgb:  # green and blue dies follow white; the red die serves both
            want = {self.pins["red"]: max(w, r), self.blue: w, self.pins["white"]: w}
        else:
            want = {self.pins["red"]: r, self.pins["white"]: w}
        for pin in self._all_pins():  # white pin last, so a change of white is the final write
            if self._pin_now.get(pin) != want[pin]:
                self._pin_now[pin] = want[pin]
                self._pwm(pin, want[pin])

    def _pwm(self, pin, pct):
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
        return {"available": self.available, "error": self.error, "sos": self.sos, "rgb": self.rgb,
                "white": {"on": self.level["white"] > 0, "brightness": self.bright["white"]},
                "red": {"on": self.level["red"] > 0, "brightness": self.bright["red"]}}
