# Weather fax and text by radio

Weather services send **weather maps (radiofax)** and **text forecasts (RTTY)** by shortwave for ships at sea. This device receives them with no internet and no phone network: radio, USB sound stick and the long wire antenna are all it needs.

## Quick start
1. Unroll the **long wire antenna** (5–10 m) and get it as high and clear as you can: up a tree, along a mast, out of a window. Keep it away from the device's own power supply and solar charger.
2. Radio tab, scroll down to **Weather by shortwave** (or tap the button in the Weather tab).
3. Pick a region and a station, pick minutes (12 is a good start), tap **Receive now**.
4. Wait. The device records, puts the radio back as it was, then decodes for a minute or two. Charts and texts appear in the list. Tap **Open**, then **Zoom** for full detail (drag to move around).

The speaker plays the fax tones while recording. Turn the amplifier's knob down if that bothers you; it does not affect the recording.

## Which station and when
| Where you are | Station | Night | Day |
|---|---|---|---|
| North Sea, Baltic, Western Europe | DWD Germany (Pinneberg) fax | 3855 kHz | 7880, 13882.5 kHz |
| | DWD Germany text (RTTY, German/English sea forecasts) | 4583 kHz | 7646, 10100.8 kHz |
| UK waters, North Atlantic east | Northwood (UK Met Office) fax | 4610 kHz | 8040 kHz |
| North Atlantic west, Gulf of Mexico | NOAA Boston / New Orleans fax | 4235, 6340.5 kHz | 9110, 12750, 12789.9 kHz |
| North and central Pacific | NOAA Point Reyes / Honolulu fax | 8682, 9982.5 kHz | 12786, 16135, 17151.2 kHz |
| Northwest Pacific | JMA Tokyo fax | 3622.5 kHz | 7795, 13988.5 kHz |
| Around Australia | BoM Charleville / Wiluna fax | 5100, 7535 kHz | 11030, 13920, 15615 kHz |

Rules of thumb: **low frequencies at night, high frequencies by day**, and the further away the station, the higher the frequency. If one gives nothing, try the next.

> These frequencies are from published lists and can change. When you have internet, look up the current schedules (search for "DWD Sendeplan Seefunk" and NOAA "Worldwide Marine Radiofacsimile Broadcast Schedules") and write down the times you need. The device cannot check them for you.

## Daily automatic reception
Broadcast schedules give each chart's time in **UTC**. Tap **Every day at...**, type the time (e.g. `10:30`), and the device records that station every day at that time by itself, as long as it is switched on. Start 1–2 minutes before the listed time and allow 12–20 minutes per chart. Remove a time with ✕. Check the device's clock first (tap it to set it).

## Reading a weather fax chart
- **Surface analysis / forecast ("Bodenanalyse", "Surface prog")**: lines are **isobars** (equal pressure). **H** = high pressure, fair weather. **L / T** = low, wind and rain. Lines close together = **strong wind**. Wind blows nearly along the lines, anticlockwise around a low in the northern hemisphere (clockwise in the southern), slightly inwards.
- **Fronts**: line with triangles = cold front (squalls, wind shift, then clearer); with half circles = warm front (long rain, poor visibility); both = occluded front.
- **Wind arrows**: each long barb = 10 knots, short barb = 5, flag (triangle) = 50 knots. 34+ knots = gale.
- **Wave charts**: lines of equal significant wave height in metres.
- A chart starts with a title block: read the **valid time** (e.g. "VT 31/12 UTC" or "+24h"). A 48-hour forecast is much less certain than an analysis.

## Reading RTTY text
DWD text bulletins are ship forecasts by sea area (Deutsche Bucht, Nordsee, Ostsee ...), wind in **Beaufort** (e.g. "SW 6, BOEEN 8" = south-west force 6, gusts 8) and sea state in metres. Garbled letters mean a weak signal: the start and end of a word are usually enough.

## If nothing comes through
- "No chart found": no signal, wrong time, or the station sends on another frequency now. Try another frequency of the same station, or another time of day.
- Weak signal (low "Signal" number, sound level bar near zero): raise the antenna, make it longer, move away from electronics and solar chargers.
- Text that is pure nonsense: interference. Try another frequency.
- "SSB patch missing": run `python3 tools/get_ssb_patch.py` once while the device has internet.
- "USB sound stick not found": check the stick and the OTG adapter in the Pi's **data** USB port (not the power port).

Without any of this, the barometer forecast in the Weather tab still works: see [Reading the weather](page:comms/weather-signs).
