# Listening to aircraft

Pilots, airports and air traffic control talk on **VHF airband, 118–137 MHz, AM**. With the SDR stick this device can listen in. It can't transmit.

## Why listen
- **Weather:** airports broadcast **ATIS** (automatic terminal information) every few minutes on a fixed frequency: wind, visibility, cloud base, temperature, pressure (QNH). Good local weather when everything else is down.
- **What's going on:** search and rescue helicopters, coastguard aircraft and military flights talk on airband. In a disaster you hear where help is going.
- **121.5 MHz** is the international aviation emergency frequency ("guard"). Emergency beacons (ELT/PLB) also give a sweeping tone here.

## Using it
Radio tab, **Airband**. Tap a frequency, then **Listen**. **Scan all** goes through your list and stops on whichever channel is busy. Use **Add...** to type a frequency from an aviation chart or airport page, e.g. `118.275 Rotterdam Tower`. Tap a selected frequency again to remove it.

**Squelch** silences the hiss between transmissions. Too high cuts off weak stations; for scanning use low or medium.

## Range
Aircraft at cruising height can be heard **200–300 km** away. Airport towers and ground vehicles only 20–50 km, and only with a clear view. Height helps a lot: go upstairs or up a hill. The stick's antenna should be about 55 cm long and vertical.

## Reading ATIS and VOLMET
Weather is read out in a fixed order:

| Item | Example | Means |
|---|---|---|
| Wind | "two four zero degrees, one five knots, gusting two five" | from 240° (SW), 15 kt, gusts 25 kt |
| Visibility | "visibility one zero kilometres or more" / "CAVOK" | 10 km or more; CAVOK = no significant cloud or weather |
| Weather | "light rain", "thunderstorm", "fog" | |
| Cloud | "broken one thousand two hundred feet" | FEW 1-2/8, SCT 3-4/8, BKN 5-7/8, OVC 8/8 of sky, base in feet |
| Temperature / dew point | "one two, dew point one zero" | close together = fog or low cloud likely |
| QNH | "one zero zero eight" | sea-level pressure in hPa: compare with this device's barometer |
| Trend | "NOSIG", "BECMG", "TEMPO" | no change / becoming / temporarily |

## Shortwave aviation weather (VOLMET)
The main radio (not the SDR stick) receives **VOLMET**: airport weather for whole regions read out on shortwave every few minutes, heard across the North Atlantic and Europe. They're saved as presets on the **USB** band:

| Station | Frequencies (kHz, USB) |
|---|---|
| Shannon VOLMET (Ireland: main European airports) | 3413 (night), 5505, 8957, 13264 (day) |
| RAF VOLMET (UK military airfields) | 5450, 11253 |
| Gander VOLMET (Canada, North Atlantic) | 3485, 6604, 10051, 13270 |

Use the long wire antenna. Low frequencies at night, high by day. If voices sound like ducks, use the **Fine** buttons.

> Receiving aviation radio is allowed in some countries and restricted in others (in the Netherlands listening is generally allowed, but don't pass on what you hear). In a real emergency, no one will mind.
