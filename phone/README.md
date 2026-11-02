# Pocket INS (phone app)

The inertial navigation from the pocket computer (`app/ins.py`, `app/deadreck.py`) as a stand-alone, offline web app
for a phone. It uses the phone's own gyro, accelerometer, compass and GPS. It runs on iPhone (Safari) and Android
(Chrome), with no server and no internet after the first install.

What it does:

- **Alignment**: hold the phone still, screen up, for 30 s (at sea 60 s, rocking allowed). Gyro offset and "up" are measured.
- **Gyro-stabilised heading**: a Kalman filter that trusts the gyro short term and the compass and GPS course slowly.
- **GPS spoof checks**: position jumps, speed changes nothing pushed, turns the gyro didn't feel, steps while GPS says
  you are standing still. A suspect GPS is not used (or only warned about, in the settings) and dead reckoning carries on.
- **Dead reckoning**: on foot by steps × step length (learned from GPS), at sea by speed × course (last good GPS, or typed in),
  with the course turned by every turn the gyro felt.
- Typed positions and waypoints (decimal, degrees + minutes, or DMS), distance and bearing, GPX export, red night mode.
- **Simulated sensors** ("Try with simulated sensors") to try it on a computer, including a fake GPS jump, speed lie and outage.

Limits: phones pause sensors in web apps when the screen locks, so the app keeps the screen on. The compass gives
magnetic north: set the magnetic variation in the settings. Phone browsers give no raw GNSS data, so checks that need
signal strengths are not possible.

## Install on a phone

The app must be served once over **https** (sensors and offline install need it). After that it works offline.

1. Open the https address in Safari (iPhone) or Chrome (Android).
2. iPhone: Share → *Add to Home Screen*. Android: menu → *Install app* / *Add to Home screen*.
3. Open it from the home screen and tap *Start sensors*; allow motion and location.

Hosting options: GitHub Pages (Settings → Pages → deploy from the branch, folder `/phone` is not offered, so use the
workflow in `.github/workflows/phone-pages.yml`), or drag the `phone/` folder onto any static host.
To test on a computer: `cd phone && python3 -m http.server` and open http://localhost:8000 (localhost counts as secure).

## Files

- `core/ins.js`: INS, spoof monitor, step detector and dead reckoning (no browser code; also runs in Node)
- `core/coords.js`: typed coordinates
- `app.js`: phone sensors and screen; `demo.js`: simulated sensors; `sw.js`: offline cache
- `tests/ins.test.mjs`: `node --test phone/tests/ins.test.mjs` (port of `tests/test_ins.py`)

When a file changes, bump `VERSION` in `sw.js` so installed copies update the next time they are online.
