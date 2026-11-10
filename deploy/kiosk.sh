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
# Touch-only device: hide the mouse pointer. cage draws one in the middle of the screen
# and CSS "cursor: none" can't reach it, so give cage and Chromium an invisible cursor theme.
BLANK="$HOME/.icons/doomsday-blank/cursors"
if [ ! -s "$BLANK/default" ]; then  # -s: redo an empty file left by an interrupted run
  mkdir -p "$BLANK"
  python3 - "$BLANK/default" <<'PY'
import struct, sys
n = 24  # one fully transparent 24x24 image in Xcursor format
img = struct.pack("<9I", 36, 0xFFFD0002, n, 1, n, n, 0, 0, 0) + b"\0" * (4 * n * n)
open(sys.argv[1], "wb").write(b"Xcur" + struct.pack("<6I", 16, 0x10000, 1, 0xFFFD0002, n, 28) + img)
PY
  for c in left_ptr arrow top_left_arrow pointer hand1 hand2 text xterm wait watch \
           progress left_ptr_watch crosshair grab grabbing move not-allowed help; do
    ln -sf default "$BLANK/$c"
  done
fi
export XCURSOR_THEME=doomsday-blank XCURSOR_SIZE=24
exec cage -d -- "$BROWSER" --kiosk --noerrdialogs --disable-infobars --no-first-run \
  --disable-translate --disable-features=TranslateUI --overscroll-history-navigation=0 --disable-smooth-scrolling \
  --disk-cache-size=10000000 --renderer-process-limit=1 \
  --enable-features=OverlayScrollbar --password-store=basic "http://127.0.0.1:8080/?kiosk=1"
