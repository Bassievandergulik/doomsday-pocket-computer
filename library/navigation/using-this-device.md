# Using this device

## Tabs
- **Map**: drag to pan, pinch or +/− to zoom, double-tap zooms in. **Long-press** anywhere to save a waypoint, navigate there, or list what's near. ◎ follows your GPS position; ▦ switches to raster maps if `map.mbtiles` is installed.
- **Go**: compass with an orange arrow to your target, distance, bearing, back-bearing, walking time, your coordinates in decimal and UTM, sunrise/sunset/last light. "Mark here" saves your position (camp, car, water source). Waypoints list: Go / Map / delete.
- **Find**: nearest water, shelter, hospitals, pharmacies, AEDs, police, food shops, fuel... with distance and arrow. Search box finds towns, villages, named places and your waypoints. Works without GPS from the map centre.
- **Radio**: FM (with station names), MW, LW, shortwave bands and USB/LSB. ◀◀/▶▶ seek the next station, ◀/▶ step. "Scan band" finds and saves all stations. Save your regional emergency station as the first preset. In USB/LSB the **Fine** buttons shift ±100 Hz until voices sound natural. See [Radio guide](page:comms/radio).
- **Airband** (Radio tab): listen to aircraft and airports on 118–137 MHz with the SDR stick, and scan your list of frequencies. See [Listening to aircraft](page:comms/airband).
- **Weather by shortwave** (bottom of the Radio tab, or the button in the Weather tab): receive weather fax charts and text from weather services, no internet needed. See [Weather fax and text by radio](page:comms/weather-fax).
- **Weather**: temperature, humidity, pressure, 12-hour forecast from the pressure trend, frost/storm warnings (needs 3 hours of readings after start-up). Below it the **downloaded forecast** (16 days, area map of rain and wind, next 48 hours). It refreshes by itself whenever the device has WiFi or a phone hotspot, and keeps working offline from the last download: check its age. The first 3-5 days after a download are fairly reliable, later days only trends. Without any recent download, rely on the barometer, the sky ([Reading the weather](page:comms/weather-signs)) and radio news.
- **Guide**: this library. Search box searches every page.
- **⇄ Connect a computer**: turns on the device's own WiFi hotspot and shows its name and password. Join it from a laptop and open the address shown (http://10.42.0.1:8080/files) to upload maps, GPX waypoints and your own guide pages, or download your waypoints, walked track and weather log. Turn it off when done (it also switches itself off after an hour) to save battery.
- **🔦 Torch**: white light on/off with brightness, a red light (keeps your night vision, hard to see from far away), and **SOS** which flashes ... --- ... with the white light. The bright white light drains the battery fast: use the red one around camp.
- **☾**: red night mode, saves your night vision and battery.
- **No GPS fix? Dead reckoning.** When GPS loses its fix, the device keeps **estimating** your position: on foot from counted steps and the compass, on a boat from the boat's speed and course. The dot turns orange with a circle showing how far off it may be, and the top bar says "Estimated ±…". Choose **On foot / Boat / Off** in the Go tab. For a boat, tap **Boat speed and course** and type e.g. `5.5 230` (knots, degrees), or leave it empty to keep the last GPS speed and course.
- **Correct the estimate** whenever you know where you are: Go tab, **Enter coordinates** (from a chart, a sign, a phone, a passing ship), or long-press the map and **I am here**. You can type `52.3702 4.8952`, `52 22.2 N 4 53.7 E` (degrees and minutes, as on sea charts), `52°22'12"N 4°53'43"E` or UTM like `31U 629025 5803904`. Dead reckoning carries on from there.
- The step length (about 72 cm to start) learns itself while you walk with GPS. Hold or carry the device the same way you'd walk with it. For the compass: calibrate it (Go tab) and keep it away from metal and the speaker.
- **Clock wrong?** The clock chip keeps time while the device is off, and GPS or internet correct it. If it's still wrong, tap the clock (top right) and type the date and time, or just open the device's page from your computer over the hotspot: it copies the computer's time. Weather fax schedules are in UTC, so a correct clock matters.
- **Typing**: tap any text box and an on-screen keyboard appears. **123** switches to numbers and symbols, **↵** confirms, **✕** cancels.

## Saving battery
- Dim the screen, use night mode.
- GPS uses the most power after the screen. Put the GPS module on a switch or remove its power when not navigating; the last position stays on the map.
- Turn the radio volume down instead of leaving it on in the background.
- Shut down properly (`sudo poweroff`) to protect the SD card.

## Coordinates for rescuers
Read them out from the Go tab: decimal degrees (52.12345, 5.12345) or UTM (31U 123456 E 5778899 N). Say "decimal degrees" or "UTM" first. Repeat numbers digit by digit.

## Updating the maps
On a computer with internet: download a region from download.geofabrik.de, run `tools/build_navdb.py region.osm.pbf nav.db`, copy `nav.db` to the device's `data/` folder.
