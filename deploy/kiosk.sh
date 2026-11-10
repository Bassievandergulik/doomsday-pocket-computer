#!/bin/bash
# Full-screen browser on the touchscreen. cage is a tiny Wayland kiosk compositor.
until curl -s -o /dev/null http://127.0.0.1:8080/; do sleep 1; done
BROWSER=$(command -v chromium || command -v chromium-browser)
# The 3.5" SPI touchscreen (deploy/screen.sh) is its own small display device without a GPU:
# draw only there, with the software renderer.
for c in /sys/class/drm/card[0-9]; do
  if [ "$(basename "$(readlink -f "$c/device/driver")")" = "ili9486" ]; then
    export WLR_DRM_DEVICES="/dev/dri/$(basename "$c")" WLR_RENDERER=pixman
  fi
done
exec cage -d -- "$BROWSER" --kiosk --noerrdialogs --disable-infobars --no-first-run \
  --disable-translate --disable-features=TranslateUI --overscroll-history-navigation=0 \
  --disk-cache-size=10000000 --renderer-process-limit=1 \
  --enable-features=OverlayScrollbar --password-store=basic "http://127.0.0.1:8080/?kiosk=1"
