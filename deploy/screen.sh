#!/bin/bash
# Set up the Waveshare 3.5" RPi LCD (B) touchscreen for the kiosk. Run once, then reboot:
#   bash deploy/screen.sh
# deploy/install.sh runs this too (skip with SCREEN=hdmi). Undo: remove the
# "dtoverlay=waveshare35b-drm" line from config.txt on the SD card's boot partition.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
OVERLAYS="$(dirname "$CFG")/overlays"

echo "== 3.5\" touchscreen: kernel DRM driver overlay"
command -v dtc >/dev/null || sudo apt-get install -y device-tree-compiler
TMP=$(mktemp -d)
dtc -q -@ -I dts -O dtb -o "$TMP/waveshare35b-drm.dtbo" "$APP_DIR/deploy/waveshare35b-drm.dts"
sudo install -m 644 "$TMP/waveshare35b-drm.dtbo" "$OVERLAYS/waveshare35b-drm.dtbo"
rm -rf "$TMP"
# Waveshare's LCD-show script would have added its fbtft overlay: the two can't share the SPI bus
sudo sed -i -E 's/^(dtoverlay=waveshare35)/#\1/' "$CFG"
sudo sed -i -E 's/^#(dtoverlay=waveshare35b-drm)/\1/' "$CFG"
grep -q '^dtparam=spi=on' "$CFG" || echo 'dtparam=spi=on' | sudo tee -a "$CFG" >/dev/null
grep -q '^dtoverlay=waveshare35b-drm' "$CFG" || echo 'dtoverlay=waveshare35b-drm' | sudo tee -a "$CFG" >/dev/null

echo "== Boot messages and login prompt on the 3.5\" screen"
# Without a console on it the screen stays black until the kiosk starts (and when it can't)
CMDLINE="$(dirname "$CFG")/cmdline.txt"
if [ -f "$CMDLINE" ] && ! grep -q 'fbcon=map:' "$CMDLINE"; then
  sudo sed -i '1 s/$/ fbcon=map:1/' "$CMDLINE"
fi

echo "== Touch: map the touch panel onto the screen"
# Derived from Waveshare's X11 calibration for this panel (SwapAxes, 3932 300 294 3801 on a 0..4095 range).
# If touches land in the wrong place, fine-tune these six numbers and reboot.
sudo tee /etc/udev/rules.d/99-waveshare35b-touch.rules >/dev/null <<'RULE'
ATTRS{name}=="ADS7846 Touchscreen", ENV{LIBINPUT_CALIBRATION_MATRIX}="0 -1.1275 1.0826 1.1677 0 -0.0838"
RULE

echo "== Hide the mouse pointer"
# The HDMI port's CEC remote input reports mouse axes, so cage thinks a mouse is connected
# and draws a pointer. Ignore it: with only the touchscreen, cage hides the pointer.
echo 'KERNEL=="event*", ATTRS{name}=="vc4-hdmi", ENV{LIBINPUT_IGNORE_DEVICE}="1"' | \
  sudo tee /etc/udev/rules.d/99-doomsday-ignore-cec.rules >/dev/null

echo "== Colours: Waveshare's panel settings for the (B)"
# The kernel driver's start-up values are for the (A) panel and look washed-out grey on the (B).
# A small root service sends Waveshare's (B) values through the driver's debug interface.
for old in lcd-invert lcd-colors; do  # earlier versions of this service
  sudo systemctl disable --now "$old" 2>/dev/null || true
  sudo rm -f "/etc/systemd/system/$old.service" "/usr/local/bin/doomsday-$old"
done
sudo install -m 755 "$APP_DIR/deploy/lcd-init.sh" /usr/local/bin/doomsday-lcd-init
sudo tee /etc/systemd/system/lcd-init.service >/dev/null <<'UNIT'
[Unit]
Description=Waveshare 3.5" LCD (B) panel settings

[Service]
ExecStart=/usr/local/bin/doomsday-lcd-init
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable lcd-init

echo
echo "Screen set up. Reboot to use it:  sudo reboot"
