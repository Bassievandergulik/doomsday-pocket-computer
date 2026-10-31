"""Radio receiver selection.

Every driver offers the same API (set_band, tune, step, seek, set_volume, mute,
status) plus `bands` and `volume_max`, so the server and UI don't care which
chip is fitted. FM frequencies are in 10 kHz units (9800 = 98.0 MHz), AM in kHz.

    "radio_chip": "si4732"     FM + MW/LW/shortwave + SSB (default; weather fax kit)
    "radio_chip": "rda5807m"   FM only
    "radio_chip": "none"       no radio fitted
"""
from radio_rda5807 import RDA5807M
from radio_si4732 import Si4732


class NoRadio:
    available = False
    bands = {}
    volume_max = 0
    error = "No radio hardware"

    def __init__(self, error=None):
        if error:
            self.error = error

    def status(self):
        return {"available": False, "error": self.error}


def open_radio(bus, chip="si4732", address=None, reset_gpio=None, ssb_patch=None):
    chip = (chip or "none").lower()
    if bus is None or chip == "none":
        return NoRadio("No I2C bus" if bus is None and chip != "none" else None)
    if chip == "si4732":
        r = Si4732(bus, address or 0x11, reset_gpio, ssb_patch=ssb_patch)
    elif chip == "rda5807m":
        r = RDA5807M(bus, address or 0x11)
    else:
        return NoRadio("Unknown radio_chip '%s' in config" % chip)
    return r if r.available else NoRadio(r.error)
