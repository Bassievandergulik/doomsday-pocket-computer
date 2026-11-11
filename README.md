# Pocket Survival Computer: software

Offline software for a Raspberry Pi 3 Model B+ pocket computer (1 GB RAM) with a 3.5" touchscreen.
No internet needed after setup.

| Tab | What it does |
|---|---|
| **🔍** | **Search everything at once**: survival guide, offline Wikipedia / WikiMed / Khan Academy and other Kiwix libraries, your videos and the map. Type in English, Dutch, Spanish, German, French, Portuguese, Italian, Polish, Ukrainian, Russian, Arabic or Turkish: survival words are recognised in all 12 (brandwond = quemadura = burn = ожог), each Wikipedia is searched in its own language, typos and word endings are forgiven, accents optional. Words like "water" or "ziekenhuis" also list the nearest ones on the map. No AI: it only shows what is really stored. Articles and videos open full-screen. |
| **Map** | Offline OpenStreetMap: roads, paths, rivers, water, forest, towns, survival points. Pan, pinch-zoom, long-press for waypoint / navigate / what's near. Shows GPS position, heading and walked track. |
| **Go** | Compass with arrow to target, distance, bearing, back-bearing, walking time, coordinates (decimal + UTM), sunrise/sunset/last light, waypoint list. |
| **Find** | Nearest drinking water, shelters, hospitals, doctors, pharmacies, AEDs, police, fire stations, food shops, fuel, hardware, campsites... plus offline search for towns, places and waypoints. |
| **Radio** | Si4732 receiver: FM with RDS station names, MW, LW, shortwave bands and (with the SSB patch) USB/LSB with ±100 Hz fine tuning. Seek, step, volume, presets, band scan. |
| **Airband** | Radio tab: VHF aircraft and airport radio (118–137 MHz AM) through an RTL-SDR stick (`rtl_fm` → USB sound stick), single channel or scanning your own list with squelch. Shortwave VOLMET (aviation weather) presets are added for the main radio. |
| **Weather by shortwave** | Bottom of the Radio tab: receives weather fax charts (DWD, Northwood, NOAA, JMA, BoM) and DWD RTTY text bulletins with no internet. Receive now or every day at set UTC times; charts are decoded on the device and shown full screen with zoom. Needs the SSB patch, a USB sound stick and the long wire antenna. |
| **Weather** | BME280 temperature/humidity/pressure, 12-hour Zambretti forecast from the pressure trend, storm/frost/heat warnings, 48-hour pressure graph. Plus a downloaded 16-day forecast grid (Open-Meteo), refreshed automatically whenever a connection happens to be available, kept and shown offline with its age. |
| **Guide** | 29-page survival library: first aid (CPR, bleeding, choking, burns, fractures, shock, hypothermia, heat, wounds, medicines), water, food, shelter, fire, navigation without GPS, signalling, radio, weather fax, weather signs, hygiene, knots, disasters. Searchable. |
| **⇄** | Direct WiFi to your computer: the device becomes a hotspot (password on screen). On the computer, `http://10.42.0.1:8080/files` uploads maps (nav.db, map.mbtiles), GPX waypoints and your own guide pages, and downloads waypoints/track (GPX), the weather log (CSV) and a full backup. `http://10.42.0.1:8080` runs the whole app in the computer's browser. Switches itself off after an hour unused. Only computers on the device's own hotspot can reach it; when the device has joined some other WiFi network, nobody there can connect. |
| **🔦** | Torch: 3 W RGB LED, white (all dies: brightness, SOS strobe) or red night light (red die), each die on a MOSFET from GPIO12 green / GPIO13 red / GPIO16 blue (PWM via lgpio; `light_white_gpio`, `light_red_gpio`, `light_blue_gpio`). Set `light_blue_gpio` to null for a separate white LED + red LED. |
| **☾** | Red night mode. |

**Touch only:** no keyboard needed. Every text field opens an on-screen keyboard (letters, numbers, symbols); a plugged-in keyboard still works too.

**Durability (software side):** the installer keeps logs in RAM, turns off the swap file and access-time writes to spare the SD card, repairs the file system automatically after a power cut, enables the hardware watchdog (the Pi reboots itself if it ever freezes), and the app restarts by itself if it crashes. Your data is stored in a power-cut-safe database mode. With the UPS HAT fitted, the battery level shows in the top bar and the device shuts down cleanly before the battery is empty, so the card is never cut off mid-write.

Every piece of hardware is optional: without GPS the map works from the map centre, without a compass the arrow is relative to north (or your GPS course while walking), without the radio or BME280 those tabs say so.

## Layout
```
app/server.py        web server + API (Python standard library only)
app/geo.py           geometry, distance/bearing, UTM, sun times
app/gps.py           gpsd or raw NMEA serial GPS reader
app/sensors.py       BME280 weather sensor, BMM150/QMC5883L/HMC5883L compass
app/radio.py         picks the radio driver from config (radio_chip)
app/radio_si4732.py  Si4732/Si4735 FM/AM/SW/SSB driver (default), loads the SSB patch
app/radio_rda5807.py RDA5807M FM-only driver (alternative)
app/weather.py       logging + Zambretti forecast + warnings
app/forecast.py      downloaded 16-day forecast grid (Open-Meteo), kept offline
app/hotspot.py       direct WiFi hotspot (NetworkManager)
app/exports.py       uploads and downloads for the computer (GPX, CSV, backup)
app/shortwave.py     weather fax / RTTY receptions: stations, schedule, recording, decoding
app/audio.py         USB sound stick capture (arecord)
app/deadreck.py      MPU-6050 step counter + dead reckoning (on foot / boat)
app/airband.py       VHF airband listening and scanning via rtl_fm
app/wefax.py, rtty.py  weather fax and RTTY decoders (numpy)
tools/get_ssb_patch.py downloads the Si4732 SSB patch once (not included: not ours to distribute)
app/static/keyboard.js on-screen keyboard
app/static/files.html  the computer's upload/download page
app/library.py       Markdown library
app/search.py        multilingual search over everything (no AI, no internet)
app/lexicon.txt      survival words in 12 languages used by the search (edit/extend freely)
app/kiwix.py         talks to kiwix-serve (Wikipedia etc.) and passes articles through
app/static/          touchscreen UI (no external libraries, canvas map renderer)
library/             the survival guide pages (Markdown, edit or add freely)
tools/build_navdb.py builds data/nav.db from an OpenStreetMap extract (run on a PC)
tools/build_imagery.py downloads satellite/aerial imagery into data/map.mbtiles
deploy/              Pi install script, kiosk launcher, kiwix.sh (serves the .zim files)
tests/               python3 -m unittest discover tests
```

## 1. Build the map database (on your PC, with internet)
```bash
pip install osmium
# pick your region from https://download.geofabrik.de/europe.html
# e.g. a province: https://download.geofabrik.de/europe/netherlands/utrecht-latest.osm.pbf
python3 tools/build_navdb.py utrecht-latest.osm.pbf data/nav.db
```
Rough sizes: a Dutch province gives a 30–150 MB database in 5–20 minutes; all of the Netherlands (≈1.3 GB pbf) needs 8+ GB RAM, about an hour, and gives roughly 1–1.5 GB. Add `--buildings` for house outlines (much larger). Map data © OpenStreetMap contributors, ODbL.

## 1b. Satellite imagery (optional, on your PC)
`tools/build_imagery.py` downloads imagery into `data/map.mbtiles`; the ▦ button on the map switches to it, with roads drawn on top. Run it several times to layer sources: where sharp tiles are missing the map shows the low-detail world imagery instead. Interrupted downloads continue where they stopped.
```bash
python3 tools/build_imagery.py --list                                              # sources + licences
python3 tools/build_imagery.py data/map.mbtiles --source bluemarble --maxzoom 8    # whole world, ~90k tiles, ~1-2 GB
python3 tools/build_imagery.py data/map.mbtiles --source s2cloudless --around 52.09,5.12,60 --minzoom 9 --maxzoom 13
python3 tools/build_imagery.py data/map.mbtiles --source pdok --around 52.09,5.12,15 --minzoom 14 --maxzoom 17   # NL only
```
Add `--dry-run` to see the tile count and size first. Blue Marble (NASA) is public domain; Sentinel-2 cloudless (EOX) is non-commercial only; PDOK aerial photos are Dutch open data. Google/Bing/Esri imagery may not be downloaded for offline use.

## 1c. Offline Wikipedia, WikiMed, Khan Academy (optional, on your PC)

Khan Academy courses are played through **Kolibri**, which needs about 1 GB of RAM. The Raspberry Pi 3 Model B+ (1 GB) is the target board for this. Use the Kiwix libraries for offline reading and Kolibri for lessons.
Download `.zim` files from https://library.kiwix.org (or https://download.kiwix.org/zim/) on your PC and copy them to `data/zim/` on the SD card (or a `zim` folder on a USB stick / the boot partition). They are picked up within a minute and appear in the search automatically. Approximate sizes (2026):

| File | Size |
|---|---|
| `wikipedia_en_all_maxi` (English, with pictures) | ~110–120 GB |
| `wikipedia_en_all_nopic` (English, no pictures) | ~50–55 GB |
| `wikipedia_nl_all_maxi` / `_nopic` (Dutch) | ~35–40 GB / ~10–15 GB |
| `wikipedia_es_all_nopic` (Spanish, no pictures) | ~20–30 GB |
| `mdwiki_en_all_maxi` (WikiMed medical encyclopedia) | ~2–4 GB |
| Wikivoyage, Wikibooks, iFixit, Gutenberg, Khan Academy subsets | 1–15 GB each |

Search for "khan" on library.kiwix.org for Khan Academy collections. Pick what fits: a 256 GB card holds English Wikipedia with pictures plus Dutch and Spanish without pictures and WikiMed. Every official Wikipedia ZIM has a full-text index, so every word is searchable (expect 1–5 s per library on the Pi 3 B+).

**Videos** (e.g. Khan Academy downloads): put them in `data/videos/<Subject>/`, `.mp4` or `.webm`, at 360p/480p to save space. A subtitle file with the same name (`.vtt`/`.srt`) makes everything said in the video searchable. Sound needs an audio output (I2S amp board or USB sound stick): the Pi Zero has none built in.

After adding guide pages or videos, the search picks them up on the next restart (or `curl -X POST http://127.0.0.1:8080/api/find/reload`).

## 2. Install on the Pi
Flash Raspberry Pi OS Lite (64-bit), copy this folder to the Pi, then (WiFi is only needed during this setup):
```bash
bash deploy/install.sh
cp nav.db map.mbtiles ~/doomsday/data/     # copy your maps BEFORE the reboot
sudo reboot
```
The app runs as the `doomsday` systemd service on port 8080 and Chromium shows it full-screen through `cage`.

**Nothing relies on a connection.** Maps, search, navigation, the guide, the radio and the barometer forecast all work with no network at all. WiFi stays on only so the device can refresh the downloaded forecast whenever it happens to be in range of a known network or your phone's hotspot; with no connection it keeps the last forecast and shows its age.
- **Screen:** the installer sets up the Waveshare 3.5" RPi LCD (B) touchscreen itself (`deploy/screen.sh`); don't run Waveshare's LCD-show script, its old framebuffer driver can't be used by the kiosk. It uses the kernel's DRM driver for this panel, sends Waveshare's own colour and gamma settings for the (B) panel (`lcd-init` service; the driver's defaults look washed-out grey), and maps touch with a calibration matrix in `/etc/udev/rules.d/99-waveshare35b-touch.rules` (adjust the six numbers if taps land off). Using an HDMI monitor instead: `SCREEN=hdmi bash deploy/install.sh`. Tested on a real Pi 3 B+ (SPI at 16 MHz; 24 MHz gives speckled text). Use a proper 5.1 V / 2.5 A power supply: on a computer USB port the Pi is under-powered (`vcgencmd get_throttled` not 0x0), slows down and the kiosk can crash.
- Want WiFi and Bluetooth fully off (less power)? Install with `NO_WIFI=1 bash deploy/install.sh`.
- Updating maps without WiFi: put the SD card in any PC and copy files to the `doomsday` folder on the boot partition (the one Windows/Mac can open). The app looks there too. Big satellite files may not fit there: copy those over WiFi or during setup.

## 3. Wiring (all I2C devices share the bus)
| Part | Pi pin |
|---|---|
| Si4732 SDA / SCL | GPIO2 (pin 3) / GPIO3 (pin 5), 3.3 V, GND |
| Si4732 RST / SEN | RST → GPIO23 (pin 16); SEN → GND (I2C address 0x11) |
| Si4732 audio out | → PAM8403 amp → speaker, **and** → 10 µF capacitor + resistor divider → USB sound stick mic input |
| Si4732 antennas | FM: ~75 cm wire. AM/SW input: 5–10 m long wire, as high as possible |
| USB sound stick | via a micro-USB OTG adapter in the Zero's **data** port (the one marked USB, not PWR) |
| BME280 SDA / SCL | same bus, address 0x76 or 0x77, 3.3 V |
| BMM150 compass (optional; QMC5883L and HMC5883L also work) | same bus (0x13 on the DFRobot Fermion board), mount flat away from the speaker magnet |
| GPS (u-blox NEO-6M/M8N) TX → RX | GPIO15 (pin 10); GPS RX ← GPIO14 (pin 8); or use a USB GPS |

| RGB LED green / red / blue die | MOSFET gates on GPIO12 (pin 32) / GPIO13 (pin 33) / GPIO16 (pin 36). Series resistor per die from 5 V, about 250 mA: red 4× 47 Ω ¼ W in parallel (≈12 Ω), green and blue each 3× 22 Ω ¼ W in parallel (≈7 Ω) |
| MPU-6050 (GY-521) | same I2C bus, 3.3 V, **AD0 → 3.3 V** (address 0x69; the DS3231 has 0x68). Mount it firmly in the case |
| DS3231 clock | same I2C bus, 3.3 V |
| RTL-SDR stick + USB sound stick | plugged straight into two of the Pi's USB-A ports (the 4-port hub is no longer needed) |

Check with `i2cdetect -y 1` (expect 11 Si4732, 76 BME280, 0d compass, 43 UPS HAT, 68 DS3231 shown as UU once its driver loads, 69 MPU-6050), `arecord -l` (sound stick), `rtl_test -t` (SDR stick) and `cgps` (GPS).

Keep the BME280 away from the Pi CPU (on a short cable or outside the case), or the temperature reads several degrees high. Pressure (the forecast) is unaffected.

## Weather fax and RTTY
The installer downloads the Si4732 SSB patch once (`tools/get_ssb_patch.py`; it comes from the PU2CLR SI4735 library and is for personal, non-commercial use, so it is not part of this package). Without it FM/AM/SW still work and the fax section says what is missing. A reception tunes the radio to USB about 1.9 kHz below the station's listed frequency, records the sound stick at 8 kHz, puts the radio back, then decodes in a low-priority process (about a minute for a 12-minute chart on the Pi 3 B+). The fax decoder finds the exact tone frequency by itself (radio crystals are often a few hundred Hz off on shortwave) and corrects sound-card clock drift (slant). Results are in `data/shortwave/` and can be downloaded over the hotspot. The station list (`app/shortwave.py`) and frequencies need checking against current schedules; add daily times on the device.


**No GPS fix: dead reckoning** (`app/deadreck.py`). An MPU-6050 accelerometer (GY-521; MPU-6500/9250 clones accepted, at 0x69 with AD0 high because the DS3231 clock uses 0x68) counts steps; each step moves the estimate one step length (learned from GPS) along the compass heading. In Boat mode the estimate continues with the last GPS speed and course, or a speed and course typed in. It restarts from every GPS fix and from coordinates you type (Go tab, "Enter coordinates": decimal, degrees + decimal minutes, DMS or UTM) or set on the map ("I am here"). The map shows it as an orange dot with an error circle (on foot 10 m + 5% of distance; boat 50 m + 10% + drift). Estimated points are added to the track.

**Messages (Meshtastic):** plug a Meshtastic node (Heltec or LilyGO LoRa board) into a USB port of the Pi. The ⇄ tab's "Messages" section lists messages and nearby nodes, sends short text (on-screen keyboard), and shares your position. Needs `pip install meshtastic`. Untested with real nodes.

**Board:** Raspberry Pi 3 Model B+ (1 GB), the default. Its UPS HAT (D) wakes the Pi with I2C; the battery readout works at 0x43. Optional: set the HAT's auto power-on by writing 0x55 to register 0x01 of its MCU at 0x2D (`i2cset -y 1 0x2d 0x01 0x55`), so it starts when charging. Untested.

**Other boards:** See [docs/boards.md](docs/boards.md) for what a Radxa Zero 3W would need. Not tested.

**Air and UV (weather tab):** a BME680 (I2C 0x76/0x77) gives pressure, temperature, humidity and a gas reading. The air quality is relative to the cleanest air seen after 5 minutes of warm-up, so it shows *change* (smoke, fumes), not an absolute level. Needs `pip install bme680`. An LTR390 (I2C 0x53) gives a UV index with a sunburn warning; it's calibrated approximately. Both untested on hardware.

**Clock:** a DS3231 clock chip keeps time while off (`dtoverlay=i2c-rtc,ds3231`); GPS time and a computer on the hotspot correct it, or tap the clock on screen.

## Configuration
`data/config.json` is created on first start:
| Key | Meaning |
|---|---|
| `simulate_position` | `[lat, lon]` to test without GPS |
| `home_altitude_m` | your altitude, for sea-level pressure when there's no GPS fix |
| `magnetic_declination` | degrees east, ~+2 to +5 in NL/BE/DE |
| `radio_chip` | `si4732` (default), `rda5807m` (FM only) or `none` |
| `radio_address`, `radio_reset_gpio` | I2C address (0x11 = 17) and Si4732 reset pin |
| `ssb_patch` | SSB patch file in the data folder (`ssb_patch.bin`, made by `tools/get_ssb_patch.py`; the installer fetches it) |
| `audio_device` | sound stick for fax/RTTY: `auto` or e.g. `plughw:1,0` |
| `airband_gain` | RTL-SDR tuner gain in dB (default 40) |
| `airband_ppm` | RTL-SDR frequency correction in ppm (default 0). Generic RTL2832U + R820T2 sticks can drift tens of ppm: tune a known station (e.g. an airport ATIS) and adjust until it's clear |
| `sw_capture_volume`, `sw_keep_audio` | radio volume while recording (0–63; lower it if charts look smeared, raise it if the sound level bar stays low) and whether to keep the WAV files |
| `gps_serial`, `gps_baud` | if not using gpsd |
| `start_view` | `[lat, lon, zoom]` shown before a GPS fix (and the forecast location without GPS) |
| `forecast_auto_download` | `true` (default): refresh the forecast whenever internet is available (checked every 30 min, refreshed when older than 3 h); `false`: never connect |
| `hotspot_auto_off_min` | hotspot switches off after this many minutes unused (0 = never) |
| `battery_shutdown_v` | UPS HAT: clean shutdown below this battery voltage (default 3.35 V) |
| `extra_data_dirs` | other folders searched for nav.db / map.mbtiles and `videos/` (boot partition, USB stick) |
| `kiwix_url` | where kiwix-serve runs (default `http://127.0.0.1:8081/kiwix`) |
| `forecast_grid_half`, `forecast_grid_step` | grid size (2 = 5×5 points) and spacing in degrees |

## Try it on a PC
```bash
python3 app/server.py --data data     # then open http://127.0.0.1:8080, ideally at 480x320
```

## Search languages
`app/lexicon.txt` has ~85 survival topics with their words in 12 languages; the first word of each language is what that language's Wikipedia is searched for. Add words or topics in any text editor. To add a language: add a column to every line and its code to `LANGS` in `app/search.py`. Typing in Arabic, Ukrainian or Russian works from a phone or laptop over the ⇄ hotspot (the on-screen keyboard is Latin letters only); place names are searched as typed.

## Editing the guide
Each page is a Markdown file under `library/<section>/`. Link pages with `[text](page:section/name)`. Supported: headings, lists, tables, **bold**, *italic*, `> warning box`. The content is general guidance, not a substitute for a first-aid course.
