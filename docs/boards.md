# Boards: Pi first, Radxa Zero 3W as fallback

Status: **not tested on any real board.** The Pi Zero 2 W and Pi 3 A+ are sold out in the EU, so this lists what a Radxa Zero 3W would need. Everything marked "check" must be verified on hardware before buying.

## What the software relies on, and the Radxa equivalent
| Need | Raspberry Pi (tested in simulation) | Radxa Zero 3W (check) |
|---|---|---|
| Screen, Waveshare 3.5" SPI LCD (A) | Waveshare driver with a device-tree overlay | Needs a Waveshare/Radxa overlay for this panel. Check the Waveshare wiki for a Radxa build; the driver is not in this repo. Without it the device has no screen. |
| Touch | same panel driver | same overlay; check touch works in the kiosk |
| I2C (Si4732, BME280, MPU-6050, DS3231, INA219, compass) | `/dev/i2c-1`, `smbus2` | Enable the I2C bus in the Radxa overlay; the bus number may differ. Set `i2c_bus` in config.json. |
| GPIO for the Si4732 reset (GPIO23) and the LEDs (12, 13) | `lgpio` | `lgpio` is Pi-specific. Radxa needs `libgpiod` (`gpiod` Python) and different chip/pin numbers. **Code change needed** in `app/light.py` and `app/radio_si4732.py` (`_reset`). |
| PWM for LED brightness | `lgpio.tx_pwm` (hardware-independent of the Pi model) | Use the Radxa PWM sysfs/overlay or software PWM through `gpiod`. **Code change needed.** |
| GPS (ATGM336H) on the UART | `/dev/serial0` via gpsd | Port name differs (typically `/dev/ttyS*` or `/dev/ttyUSB*`). Set `gps_serial` in config.json and check gpsd. |
| UPS HAT (C) battery monitor | INA219 on I2C 0x43 | Same I2C; works if the bus is enabled. |
| Chromium kiosk under cage | `deploy/kiosk.sh` | Install Chromium for the Radxa OS image; `cage` should be available. Check Wayland/DRM support for the panel. |
| Meshtastic (USB) | `/dev/ttyACM*` | Same, USB works. |
| RTL-SDR and USB sound stick | USB | Same; check the Radxa kernel has the RTL2832U driver. |

## install.sh changes for Radxa
- Packages: use the Radxa OS package names (`python3-libgpiod` instead of `python3-lgpio`; `gpsd`, `cage`, `network-manager`, `alsa-utils` likely the same). Check each.
- `raspi-config` calls must be skipped (they don't exist). Enable I2C, UART and the Waveshare overlay with the Radxa tool (`rsetup` / `armbianconfig`-style), then reboot.
- The DS3231 overlay line `dtoverlay=i2c-rtc,ds3231` is Pi syntax; Radxa uses its own device-tree overlay for the RTC.
- The `NO_WIFI` option uses Pi config.txt overlays; not applicable.

## Selecting the board
`data/config.json` has `"board": "pi"`, the default. Setting `"board": "radxa-zero3w"` is reserved for the changes above; until they're made the app logs a warning and keeps the Pi settings. The app itself runs unchanged on both once the GPIO and display layers are ported.

## Untested items to add to the parts list
- Radxa Zero 3W board itself (1 GB or 2 GB RAM is enough for this app)
- Waveshare 3.5" SPI LCD (A) with a Radxa-compatible overlay (confirm first)
- Everything above in the table
