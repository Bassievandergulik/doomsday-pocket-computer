#!/bin/bash
# Full-screen browser on the touchscreen. cage is a tiny Wayland kiosk compositor.
until curl -s -o /dev/null http://127.0.0.1:8080/; do sleep 1; done
BROWSER=$(command -v chromium || command -v chromium-browser)
exec cage -d -- "$BROWSER" --kiosk --noerrdialogs --disable-infobars --no-first-run \
  --disable-translate --disable-features=TranslateUI --overscroll-history-navigation=0 \
  --disk-cache-size=10000000 --renderer-process-limit=1 \
  --enable-features=OverlayScrollbar --password-store=basic http://127.0.0.1:8080/
